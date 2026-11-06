"""存储层测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from progressviz import events as E
from progressviz.store import EventStore, read_events, summarize


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "run.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_creates_dirs(self):
        with EventStore(self.path) as s:
            s.append(E.Event(1, E.now(), E.TEXT, text="hi"))
        self.assertTrue(self.path.exists())

    def test_roundtrip(self):
        with EventStore(self.path) as s:
            s.append(E.Event(1, E.now(), E.TOOL, name="grep"))
            s.append(E.Event(2, E.now(), E.TEXT, text="结果"))
        got = list(read_events(self.path))
        self.assertEqual([e.kind for e in got], [E.TOOL, E.TEXT])
        self.assertEqual(got[1].text, "结果")

    def test_bad_lines_skipped(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"seq":1,"kind":"text","text":"ok"}\n{broken\n', encoding="utf-8")
        got = list(read_events(self.path))
        self.assertEqual(len(got), 1)

    def test_missing_file_yields_nothing(self):
        self.assertEqual(list(read_events(Path(self.tmp.name) / "nope.jsonl")), [])

    def test_summarize_uses_usage(self):
        with EventStore(self.path) as s:
            s.append(E.Event(1, E.now(), E.TEXT, text="a"))
            s.append(E.Event(2, E.now(), E.USAGE, tokens=100, meta={"total": 100}))
            s.append(E.Event(3, E.now(), E.DONE, meta={"estimated": 5, "usage": {"total": 100}}))
        info = summarize(self.path)
        self.assertEqual(info["tokens"], 100)
        self.assertEqual(info["tokens_source"], "usage")
        self.assertEqual(info["events"], 3)
        self.assertEqual(info["by_kind"]["text"], 1)

    def test_summarize_falls_back_to_estimate(self):
        with EventStore(self.path) as s:
            s.append(E.Event(1, E.now(), E.TEXT, text="a"))
            s.append(E.Event(2, E.now(), E.DONE, meta={"estimated": 42}))
        info = summarize(self.path)
        self.assertEqual(info["tokens"], 42)
        self.assertEqual(info["tokens_source"], "estimate")

    def test_summarize_empty_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(summarize(self.path)["events"], 0)

    def test_duration_skips_blank_ts(self):
        with EventStore(self.path) as s:
            s.append(E.Event(0, "", E.START))
            s.append(E.Event(1, "2026-01-01T00:00:00+00:00", E.TEXT, text="a"))
            s.append(E.Event(2, "2026-01-01T00:00:03+00:00", E.DONE))
        self.assertAlmostEqual(summarize(self.path)["duration_s"], 3.0, places=2)


if __name__ == "__main__":
    unittest.main()
