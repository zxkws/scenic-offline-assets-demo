#!/usr/bin/env python3
"""PC simulator of the Android client: offline manifests + hash-based incremental download."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

def get(url, headers=None):
    with urlopen(Request(url, headers=headers or {}), timeout=30) as response:
        return response.read()

def valid(path, meta):
    if not path.is_file() or path.stat().st_size != meta["size"]:
        return False
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            h.update(block)
    return h.hexdigest() == meta["sha256"]

def sync(server, destination):
    destination.mkdir(parents=True, exist_ok=True)
    scenics = json.loads(get(urljoin(server, "/api/scenics")))
    for scenic in scenics:
        sid = scenic["id"]
        folder = destination / sid
        store = folder / "files"
        store.mkdir(parents=True, exist_ok=True)
        manifest = json.loads(get(urljoin(server, f"/api/scenics/{sid}/manifest")))
        pending = []
        for meta in manifest["files"].values():
            suffix = Path(meta["url"]).suffix
            target = store / (meta["sha256"] + suffix)
            if valid(target, meta):
                continue
            pending.append((meta, target))
        print(f"{sid}: version {manifest['version']} / {len(pending)} files to download")
        for meta, target in pending:
            part = target.with_suffix(target.suffix + ".part")
            size = part.stat().st_size if part.exists() else 0
            # Complete valid .part may remain after a crash before rename.
            if size == meta["size"] and valid(part, meta):
                os.replace(part, target)
                continue
            # A full-length but corrupted .part (or oversized one) cannot
            # be resumed: HTTP Range would begin beyond the end (416).
            if size >= meta["size"]:
                part.unlink()
                size = 0
            headers = {"Range": f"bytes={size}-"} if size else {}
            request = Request(urljoin(server, meta["url"]), headers=headers)
            with urlopen(request, timeout=60) as response:
                status = response.status
                # A server may ignore Range. Never append a complete response to a partial file.
                expected_range = f"bytes {size}-"
                if status != 206 or not response.headers.get("Content-Range", "").startswith(expected_range):
                    size = 0
                with part.open("ab" if size else "wb") as out:
                    while True:
                        block = response.read(65536)
                        if not block:
                            break
                        out.write(block)
            if not valid(part, meta):
                # Avoid making every subsequent run fail on a corrupt .part.
                part.unlink(missing_ok=True)
                raise RuntimeError(f"Hash mismatch: {meta['url']}")
            os.replace(part, target)
        # Only commit the new manifest after ALL referenced files have been validated.
        if not all(valid(store / (m["sha256"] + Path(m["url"]).suffix), m)
                   for m in manifest["files"].values()):
            raise RuntimeError("Incomplete scenic version " + sid)
        active = folder / "active.json"
        temporary = folder / "active.json.tmp"
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, active)
        print(f"{sid}: ready offline, {len(manifest['files'])} files")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://127.0.0.1:8765")
    p.add_argument("--dir", default="runtime/device")
    args = p.parse_args()
    sync(args.server, Path(args.dir))
