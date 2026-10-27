import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
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

    def fetch(self, path, method="GET", data=None):
        with urlopen(Request(self.url + path, method=method, data=data), timeout=8) as r:
            return json.loads(r.read())

    def test_seed_and_publish(self):
        scenics = self.fetch("/api/scenics")
        self.assertEqual(len(scenics), 3)
        before = self.fetch("/api/scenics/A/manifest")
        self.assertEqual(len(before["stations"]), 2)
        self.assertTrue(before["files"])
        self.assertEqual(before["version"], 1)
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

if __name__ == "__main__":
    unittest.main()
