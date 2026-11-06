"""Web 回放层测试。"""

from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from pathlib import Path

from progressviz import events as E
from progressviz.store import EventStore
from progressviz.web import serve_file


class TestWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "run.jsonl"
        with EventStore(cls.path) as s:
            s.append(E.Event(1, E.now(), E.TEXT, text="hello"))
            s.append(E.Event(2, E.now(), E.USAGE, tokens=10, meta={"total": 10}))
            s.append(E.Event(3, E.now(), E.DONE, meta={"estimated": 0, "usage": {"total": 10}}))

        cls.server = serve_file(cls.path, "127.0.0.1", 0)
        import threading

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def get(self, path: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        conn.close()
        return status, body

    def test_index_served(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())

    def test_summary(self):
        status, body = self.get("/api/summary")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["events"], 3)
        self.assertEqual(data["tokens"], 10)

    def test_events_stream(self):
        status, body = self.get("/api/events")
        self.assertEqual(status, 200)
        self.assertIn(b"data: ", body)
        self.assertIn(b"event: end", body)
        lines = [ln for ln in body.split(b"\n") if ln.startswith(b"data: {")]
        self.assertEqual(len(lines), 3)

    def test_404(self):
        status, _ = self.get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
