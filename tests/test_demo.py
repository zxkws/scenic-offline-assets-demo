import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["SCENIC_DEMO_DATA_DIR"] = cls.temp.name
        sys.path.insert(0, str(ROOT))
        import server
        cls.server = server
        server.initialize()
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.url = "http://127.0.0.1:" + str(cls.http.server_port)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.temp.cleanup()
        del os.environ["SCENIC_DEMO_DATA_DIR"]

    def setUp(self):
        # Each test sees the original three scenic areas and v1 release.
        with self.server.database() as db:
            for table in ("station_material", "release", "file", "station", "category", "scenic"):
                db.execute("DELETE FROM " + table)
        self.server.initialize()

    def fetch(self, path, method="GET", data=None, headers=None):
        with urlopen(Request(self.url + path, method=method, data=data,
                             headers=headers or {}), timeout=8) as r:
            return json.loads(r.read())

    def json_request(self, path, method, body):
        return self.fetch(path, method, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          {"Content-Type": "application/json"})

    def failure(self, code, action):
        with self.assertRaises(HTTPError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        return json.loads(caught.exception.read())["error"]

    def test_admin_page_and_script(self):
        with urlopen(self.url + "/") as response:
            self.assertIn(b'/app.js', response.read())
        with urlopen(self.url + "/app.js") as response:
            self.assertIn(b'/api/categories', response.read())

    def test_seed_and_publish(self):
        scenics = self.fetch("/api/scenics")
        self.assertEqual(len(scenics), 3)
        before = self.fetch("/api/scenics/A/manifest")
        self.assertEqual(len(before["stations"]), 2)
        self.assertTrue(before["files"])
        self.assertEqual(before["version"], 1)
        self.assertEqual(self.fetch("/api/categories")[0]["mediaType"], "image")
        self.fetch("/api/scenics/A/publish", "POST", b"")
        after = self.fetch("/api/scenics/A/manifest")
        self.assertEqual(after["version"], 2)
        self.assertEqual(before["files"], after["files"])

    def test_upload_publish_offline_and_incremental(self):
        import urllib.parse
        content = b"fake demo png content"
        q = urllib.parse.urlencode({"stationId": "A-S01", "categoryCode": "gallery",
                                    "title": "新图片", "filename": "test.png"})
        result = self.fetch("/api/materials?" + q, "POST", content)
        before = self.fetch("/api/scenics/A/manifest")
        self.assertNotIn(result["fileId"], before["files"])
        self.fetch("/api/scenics/A/publish", "POST", b"")
        after = self.fetch("/api/scenics/A/manifest")
        self.assertIn(result["fileId"], after["files"])
        meta = after["files"][result["fileId"]]
        with urlopen(self.url + meta["url"]) as r:
            self.assertEqual(r.read(), content)
        self.assertEqual(meta["sha256"], hashlib.sha256(content).hexdigest())
        with urlopen(Request(self.url + meta["url"], headers={"Range": "bytes=3-7"})) as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.read(), content[3:8])
        device = Path(self.temp.name) / "device"
        command = [sys.executable, str(ROOT / "client.py"), "--server", self.url, "--dir", str(device)]
        first = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertIn("ready offline", first.stdout)
        second = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertIn("0 files to download", second.stdout)
        self.assertEqual(json.loads((device / "A/active.json").read_text())["version"], after["version"])

    def test_category_crud_publish_and_incremental(self):
        created = self.json_request("/api/categories", "POST", {
            "code": "background_music", "name": "背景音乐", "mediaType": "audio"})
        self.assertEqual(created["position"], 5)
        self.assertEqual(created["mediaType"], "audio")
        self.failure(409, lambda: self.json_request("/api/categories", "POST", {
            "code": "background_music", "name": "重复", "mediaType": "audio"}))
        self.failure(400, lambda: self.json_request("/api/categories", "POST", {
            "code": "X-bad", "name": "bad", "mediaType": "audio"}))
        self.failure(400, lambda: self.json_request("/api/categories", "POST", {
            "code": "test_other", "name": "bad", "mediaType": "pdf"}))

        q = urlencode({"stationId": "A-S01", "categoryCode": "background_music",
                       "title": "循环音乐", "filename": "music.wav"})
        mismatch = urlencode({"stationId": "A-S01", "categoryCode": "background_music",
                              "title": "不允许图片", "filename": "photo.png"})
        self.failure(400, lambda: self.fetch("/api/materials?" + mismatch, "POST", b"png"))
        created_item = self.fetch("/api/materials?" + q, "POST", self.server.make_wav(660))
        old_manifest = self.fetch("/api/scenics/A/manifest")
        self.assertNotIn(created_item["fileId"], old_manifest["files"])

        self.fetch("/api/scenics/A/publish", "POST", b"")
        current = self.fetch("/api/scenics/A/manifest")
        self.assertIn(created_item["fileId"], current["files"])
        cats = current["stations"][0]["categories"]
        music = next(c for c in cats if c["code"] == "background_music")
        self.assertEqual(music["mediaType"], "audio")
        self.assertEqual(music["items"][0]["title"], "循环音乐")
        self.failure(409, lambda: self.json_request("/api/categories/background_music", "PATCH",
                                                    {"mediaType": "image"}))
        self.failure(409, lambda: self.fetch("/api/categories/background_music", "DELETE"))
        self.failure(400, lambda: self.json_request("/api/categories/background_music", "PATCH",
                                                    {"code": "another_code"}))

        updated = self.json_request("/api/categories/background_music", "PATCH",
                                    {"name": "行车背景音乐", "position": 1})
        self.assertEqual(updated["position"], 1)
        self.assertEqual(next(c for c in self.fetch("/api/categories")
                              if c["code"] == "background_music")["name"], "行车背景音乐")
        # Draft edits are invisible until the scenic is published again.
        self.assertEqual(next(c for c in self.fetch("/api/scenics/A/manifest")["stations"][0]["categories"]
                              if c["code"] == "background_music")["name"], "背景音乐")
        self.fetch("/api/scenics/A/publish", "POST", b"")
        refreshed = self.fetch("/api/scenics/A/manifest")
        self.assertEqual(refreshed["stations"][0]["categories"][0]["name"], "行车背景音乐")
        self.assertEqual(refreshed["files"], current["files"])

        device = Path(self.temp.name) / "category-device"
        command = [sys.executable, str(ROOT / "client.py"), "--server", self.url,
                   "--dir", str(device)]
        subprocess.run(command, capture_output=True, text=True, check=True)
        again = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertIn("0 files to download", again.stdout)

        self.fetch("/api/materials/" + created_item["id"], "DELETE")
        self.fetch("/api/categories/background_music", "DELETE")
        self.assertFalse(any(c["code"] == "background_music" for c in self.fetch("/api/categories")))
        # Previously published data stays intact, until explicitly republished.
        self.assertIn(created_item["fileId"], self.fetch("/api/scenics/A/manifest")["files"])
        self.fetch("/api/scenics/A/publish", "POST", b"")
        self.assertNotIn(created_item["fileId"], self.fetch("/api/scenics/A/manifest")["files"])

    def test_legacy_database_migration(self):
        # An existing sqlite database must gain the new field without losing data.
        with tempfile.TemporaryDirectory() as old_dir:
            db_path = Path(old_dir) / "scenic.db"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE scenic (id TEXT PRIMARY KEY,name TEXT,version INTEGER)")
                db.execute("INSERT INTO scenic VALUES ('A','旧景区',2)")
                db.execute("CREATE TABLE category (code TEXT PRIMARY KEY,name TEXT,position INTEGER)")
                db.execute("INSERT INTO category VALUES ('guide_audio','讲解音频',1)")
                db.execute("INSERT INTO category VALUES ('gallery','图片',2)")
            env = dict(os.environ, SCENIC_DEMO_DATA_DIR=old_dir)
            script = """import server
server.initialize()
with server.database() as db:
    values = dict(db.execute("SELECT code,media_type FROM category"))
    assert values == {"guide_audio": "audio", "gallery": "image"}
    assert db.execute("SELECT version FROM scenic WHERE id='A'").fetchone()[0] == 2
"""
            subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                           capture_output=True, text=True, check=True)

if __name__ == "__main__":
    unittest.main()
