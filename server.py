#!/usr/bin/env python3
"""Minimal scenic-asset admin and immutable published manifests (stdlib only)."""
import argparse
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import struct
import tempfile
import threading
import uuid
import wave
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get("SCENIC_DEMO_DATA_DIR", ROOT / "runtime"))
DB = RUNTIME / "scenic.db"
ASSETS = RUNTIME / "assets"
EXPORTS = RUNTIME / "exports"
MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".m4a": "audio/mp4", ".mp4": "video/mp4", ".webm": "video/webm"
}
PUBLISH_LOCK = threading.Lock()
MAX_UPLOAD = 512 * 1024 * 1024


@contextmanager
def database():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def make_png(rgb):
    width, height = 32, 18
    pixels = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(name, data):
        return (struct.pack(">I", len(data)) + name + data
                + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def make_wav(frequency):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"".join(
            struct.pack("<h", int(10000 * math.sin(2 * math.pi * frequency * i / 8000)))
            for i in range(4000)))
    return buf.getvalue()


def attach(db, station, category, file_id, title):
    position = db.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM station_material WHERE station_id=? AND category_code=?",
        (station, category)).fetchone()[0]
    item_id = "m_" + uuid.uuid4().hex[:12]
    db.execute("INSERT INTO station_material VALUES (?,?,?,?,?,?)",
               (item_id, station, category, file_id, title, position))
    return item_id


def initialize():
    for path in (RUNTIME, ASSETS, EXPORTS):
        path.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS scenic (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS station (
                id TEXT PRIMARY KEY, scenic_id TEXT NOT NULL REFERENCES scenic(id),
                name TEXT NOT NULL, position INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS category (
                code TEXT PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS file (
                id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                size INTEGER NOT NULL, sha256 TEXT UNIQUE NOT NULL, mime TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS station_material (
                id TEXT PRIMARY KEY, station_id TEXT NOT NULL REFERENCES station(id),
                category_code TEXT NOT NULL REFERENCES category(code),
                file_id TEXT NOT NULL REFERENCES file(id), title TEXT NOT NULL,
                position INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS release (
                scenic_id TEXT NOT NULL REFERENCES scenic(id), version INTEGER NOT NULL,
                published_at TEXT NOT NULL, manifest TEXT NOT NULL,
                PRIMARY KEY (scenic_id,version));
        """)
        if db.execute("SELECT COUNT(*) FROM scenic").fetchone()[0]:
            return
        db.executemany("INSERT INTO scenic (id,name) VALUES (?,?)", [
            ("A", "青山景区"), ("B", "古镇景区"), ("C", "湖畔景区")])
        db.executemany("INSERT INTO station VALUES (?,?,?,?)", [
            ("A-S01", "A", "游客中心", 1), ("A-S02", "A", "山顶观景台", 2),
            ("B-S01", "B", "古镇入口", 1),
            ("C-S01", "C", "湖心站", 1), ("C-S02", "C", "大桥站", 2)])
        db.executemany("INSERT INTO category VALUES (?,?,?)", [
            ("gallery", "景点图片", 1), ("guide_audio", "讲解音频", 2),
            ("guide_video", "介绍视频", 3), ("safety_audio", "安全播报", 4)])
        samples = [
            ("A-S01", "gallery", "游客中心图片", make_png((31,130,98)), ".png"),
            ("A-S01", "guide_audio", "中文讲解音频", make_wav(440), ".wav"),
            ("A-S02", "gallery", "观景台图片", make_png((41,96,164)), ".png"),
            ("B-S01", "gallery", "古镇入口图片", make_png((169,111,57)), ".png"),
            ("C-S01", "gallery", "湖心站图片", make_png((39,148,176)), ".png"),
            ("C-S02", "guide_audio", "大桥站音频", make_wav(523), ".wav")]
        for station, category, title, content, ext in samples:
            sha = hashlib.sha256(content).hexdigest()
            file_id = "f_" + uuid.uuid4().hex[:12]
            filename = sha + ext
            (ASSETS / filename).write_bytes(content)
            db.execute("INSERT INTO file VALUES (?,?,?,?,?)",
                       (file_id, filename, len(content), sha, MIME[ext]))
            attach(db, station, category, file_id, title)
    for scenic in ("A", "B", "C"):
        publish(scenic)


def publish(scenic_id):
    with PUBLISH_LOCK, database() as db:
        row = db.execute("SELECT * FROM scenic WHERE id=?", (scenic_id,)).fetchone()
        if not row:
            raise ValueError("Unknown scenic")
        version = row["version"] + 1
        stations = []
        lookup = {}
        for station in db.execute(
                "SELECT id,name FROM station WHERE scenic_id=? ORDER BY position,id",
                (scenic_id,)):
            entry = {"id": station["id"], "name": station["name"], "categories": []}
            stations.append(entry)
            lookup[station["id"]] = entry
        files = {}
        groups = {}
        for item in db.execute("""
            SELECT m.id, m.station_id, m.title, c.code, c.name AS category_name,
                   f.id AS file_id, f.path, f.size, f.sha256, f.mime
            FROM station_material m
            JOIN station s ON s.id=m.station_id
            JOIN category c ON c.code=m.category_code
            JOIN file f ON f.id=m.file_id
            WHERE s.scenic_id=?
            ORDER BY s.position,c.position,m.position,m.id
        """, (scenic_id,)):
            key = (item["station_id"], item["code"])
            if key not in groups:
                group = {"code": item["code"], "name": item["category_name"], "items": []}
                lookup[item["station_id"]]["categories"].append(group)
                groups[key] = group
            groups[key]["items"].append({
                "id": item["id"], "title": item["title"], "fileId": item["file_id"]})
            files[item["file_id"]] = {
                "url": "/assets/" + item["path"], "size": item["size"],
                "sha256": item["sha256"], "mimeType": item["mime"]}
        manifest = {"schemaVersion": 1, "scenicId": scenic_id,
                    "scenicName": row["name"], "version": version,
                    "stations": stations, "files": files}
        body = json.dumps(manifest, ensure_ascii=False, indent=2)
        db.execute("INSERT INTO release VALUES (?,?,?,?)",
                   (scenic_id, version, datetime.now(timezone.utc).isoformat(), body))
        db.execute("UPDATE scenic SET version=? WHERE id=?", (version, scenic_id))
    (EXPORTS / f"{scenic_id}-v{version}.json").write_text(body + "\n", encoding="utf-8")
    return manifest


class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, payload, mime="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def respond(self, status, obj):
        self.send_data(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        params = parse_qs(url.query)
        if path == "/":
            return self.send_data(200, (ROOT / "web/index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/health":
            return self.respond(200, {"ok": True})
        if path.startswith("/assets/"):
            name = path[len("/assets/"):]
            if not re.fullmatch(r"[0-9a-f]{64}\.(png|jpg|jpeg|webp|mp3|wav|m4a|mp4|webm)", name):
                return self.respond(404, {"error": "Not found"})
            file = ASSETS / name
            if not file.is_file():
                return self.respond(404, {"error": "Not found"})
            size = file.stat().st_size
            start = 0
            end = size - 1
            status = 200
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
                if not match:
                    return self.send_data(416, b"", headers={"Content-Range": f"bytes */{size}"})
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
                if start >= size or end < start or end >= size:
                    return self.send_data(416, b"", headers={"Content-Range": f"bytes */{size}"})
                status = 206
            headers = {"Accept-Ranges": "bytes", "ETag": '"' + name[:64] + '"'}
            if status == 206:
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            self.send_response(status)
            self.send_header("Content-Type", MIME[file.suffix])
            self.send_header("Content-Length", str(end-start+1))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                with file.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        with database() as db:
            if path == "/api/scenics":
                return self.respond(200, [dict(r) for r in db.execute(
                    "SELECT id,name,version FROM scenic ORDER BY id")])
            if path == "/api/stations":
                return self.respond(200, [dict(r) for r in db.execute(
                    "SELECT id,name FROM station WHERE scenic_id=? ORDER BY position",
                    (params.get("scenicId", [""])[0],))])
            if path == "/api/categories":
                return self.respond(200, [dict(r) for r in db.execute(
                    "SELECT code,name FROM category ORDER BY position")])
            if path == "/api/materials":
                return self.respond(200, [dict(r) for r in db.execute("""
                    SELECT m.id,m.title,m.category_code AS categoryCode,
                           f.id AS fileId,f.path,f.size,f.mime
                    FROM station_material m JOIN file f ON f.id=m.file_id
                    WHERE m.station_id=? ORDER BY m.position
                """, (params.get("stationId", [""])[0],))])
            match = re.fullmatch(r"/api/scenics/([A-Za-z0-9_-]+)/manifest", path)
            if match:
                record = db.execute("""
                    SELECT r.manifest FROM release r JOIN scenic s
                    ON s.id=r.scenic_id AND s.version=r.version
                    WHERE s.id=?
                """, (match.group(1),)).fetchone()
                if record:
                    return self.send_data(200, record["manifest"].encode("utf-8"))
        return self.respond(404, {"error": "Not found"})

    def do_POST(self):
        url = urlsplit(self.path)
        match = re.fullmatch(r"/api/scenics/([A-Za-z0-9_-]+)/publish", url.path)
        if match:
            try:
                data = publish(match.group(1))
                return self.respond(200, {"scenicId": data["scenicId"], "version": data["version"]})
            except ValueError as error:
                return self.respond(404, {"error": str(error)})
        if url.path != "/api/materials":
            return self.respond(404, {"error": "Not found"})
        params = parse_qs(url.query)
        station = params.get("stationId", [""])[0]
        category = params.get("categoryCode", [""])[0]
        title = params.get("title", [""])[0].strip()
        extension = Path(params.get("filename", [""])[0]).suffix.lower()
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not title or len(title) > 120 or extension not in MIME or not 0 < length <= MAX_UPLOAD:
            self.close_connection = True
            return self.respond(400, {"error": "Bad title or unsupported file (max 512 MB)"})
        with database() as db:
            if (not db.execute("SELECT 1 FROM station WHERE id=?", (station,)).fetchone()
                or not db.execute("SELECT 1 FROM category WHERE code=?", (category,)).fetchone()):
                self.close_connection = True
                return self.respond(400, {"error": "Unknown station or category"})
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=ASSETS, suffix=".part", delete=False) as out:
                temporary = Path(out.name)
                remaining = length
                digest = hashlib.sha256()
                while remaining:
                    block = self.rfile.read(min(65536, remaining))
                    if not block:
                        raise ValueError("Incomplete upload")
                    out.write(block)
                    digest.update(block)
                    remaining -= len(block)
            sha = digest.hexdigest()
            with database() as db:
                row = db.execute("SELECT id FROM file WHERE sha256=?", (sha,)).fetchone()
                if row:
                    file_id = row["id"]
                else:
                    file_id = "f_" + uuid.uuid4().hex[:12]
                    name = sha + extension
                    os.replace(temporary, ASSETS / name)
                    temporary = None
                    db.execute("INSERT INTO file VALUES (?,?,?,?,?)",
                               (file_id, name, length, sha, MIME[extension]))
                item_id = attach(db, station, category, file_id, title)
            self.respond(201, {"id": item_id, "fileId": file_id})
        except ValueError as error:
            self.respond(400, {"error": str(error)})
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def do_DELETE(self):
        match = re.fullmatch(r"/api/materials/(m_[0-9a-f]+)", urlsplit(self.path).path)
        if not match:
            return self.respond(404, {"error": "Not found"})
        with database() as db:
            result = db.execute("DELETE FROM station_material WHERE id=?", (match.group(1),))
        return self.respond(200 if result.rowcount else 404,
                            {"deleted": True} if result.rowcount else {"error": "Not found"})


def serve(host="127.0.0.1", port=8765):
    initialize()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Demo running at http://{host}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    options = parser.parse_args()
    serve(options.host, options.port)
