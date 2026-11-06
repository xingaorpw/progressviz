"""归一化层的单元测试。全是纯函数，不需要网络。"""

from __future__ import annotations

import json
import unittest

from progressviz import events as E


class TestSplitSse(unittest.TestCase):
    def test_multiple_blocks(self):
        blocks, rest = E.split_sse("data: a\n\ndata: b\n\n")
        self.assertEqual(rest, "")
        self.assertEqual(len(blocks), 2)

    def test_partial_kept(self):
        blocks, rest = E.split_sse("data: a\n\ndata: b")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(rest, "data: b")

    def test_crlf_normalized(self):
        blocks, rest = E.split_sse("data: a\r\n\r\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(rest, "")

    def test_empty_blocks_ignored(self):
        blocks, _ = E.split_sse("\n\ndata: a\n\n\n\n")
        self.assertEqual(len(blocks), 1)


class TestParseBlock(unittest.TestCase):
    def test_json(self):
        self.assertEqual(E.parse_sse_block('data: {"a":1}'), {"a": 1})

    def test_done_marker(self):
        self.assertIsNone(E.parse_sse_block("data: [DONE]"))

    def test_comment_only(self):
        self.assertIsNone(E.parse_sse_block(": keep-alive"))

    def test_broken_json(self):
        self.assertIsNone(E.parse_sse_block("data: {oops"))

    def test_multiline_data(self):
        block = 'data: {"a":1,\ndata: "b":2}'
        self.assertEqual(E.parse_sse_block(block), {"a": 1, "b": 2})


class TestOpenAI(unittest.TestCase):
    def test_content(self):
        out = E.normalize_openai({"choices": [{"delta": {"content": "hi"}}]})
        self.assertEqual(out, [(E.TEXT, "hi", "")])

    def test_reasoning(self):
        out = E.normalize_openai({"choices": [{"delta": {"reasoning_content": "想"}}]})
        self.assertEqual(out, [(E.THINKING, "想", "")])

    def test_tool_call(self):
        payload = {"choices": [{"delta": {"tool_calls": [{"function": {"name": "grep"}}]}}]}
        self.assertEqual(E.normalize_openai(payload), [(E.TOOL, "", "grep")])

    def test_empty_delta_ignored(self):
        self.assertEqual(E.normalize_openai({"choices": [{"delta": {}}]}), [])

    def test_no_choices(self):
        self.assertEqual(E.normalize_openai({"usage": {}}), [])


class TestAnthropic(unittest.TestCase):
    def test_text_delta(self):
        payload = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
        self.assertEqual(E.normalize_anthropic(payload), [(E.TEXT, "hi", "")])

    def test_thinking_delta(self):
        payload = {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "嗯"}}
        self.assertEqual(E.normalize_anthropic(payload), [(E.THINKING, "嗯", "")])

    def test_tool_use_start(self):
        payload = {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "bash"}}
        self.assertEqual(E.normalize_anthropic(payload), [(E.TOOL, "", "bash")])

    def test_unknown_type(self):
        self.assertEqual(E.normalize_anthropic({"type": "ping"}), [])


class TestDetect(unittest.TestCase):
    def test_anthropic(self):
        self.assertEqual(E.detect_provider({"type": "content_block_delta"}), "anthropic")

    def test_openai_default(self):
        self.assertEqual(E.detect_provider({"choices": []}), "openai")


class TestUsage(unittest.TestCase):
    def test_openai(self):
        u = E.extract_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        self.assertEqual(u, {"input": 10, "output": 5, "total": 15})

    def test_anthropic(self):
        u = E.extract_usage(
            {"type": "message_delta", "usage": {"input_tokens": 3, "output_tokens": 7}},
            "anthropic",
        )
        self.assertEqual(u, {"input": 3, "output": 7, "total": 10})

    def test_missing(self):
        self.assertIsNone(E.extract_usage({"choices": []}))

    def test_zero_is_missing(self):
        self.assertIsNone(E.extract_usage({"usage": {"prompt_tokens": 0, "completion_tokens": 0}}))


class TestEstimate(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(E.estimate_tokens(""), 0)

    def test_ascii(self):
        self.assertEqual(E.estimate_tokens("a" * 40), 10)

    def test_cjk_higher_than_ascii(self):
        cjk = E.estimate_tokens("中" * 40)
        ascii_ = E.estimate_tokens("a" * 40)
        self.assertGreater(cjk, ascii_)


class TestNormalizer(unittest.TestCase):
    def test_seq_increments(self):
        n = E.Normalizer("openai")
        evs = n.feed({"choices": [{"delta": {"content": "a"}}]})
        evs += n.feed({"choices": [{"delta": {"content": "b"}}]})
        self.assertEqual([e.seq for e in evs], [1, 2])

    def test_usage_event(self):
        n = E.Normalizer("openai")
        evs = n.feed({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 6}})
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].kind, E.USAGE)
        self.assertEqual(evs[0].tokens, 10)

    def test_finish_reports_estimate(self):
        n = E.Normalizer("openai")
        n.feed({"choices": [{"delta": {"content": "hello world"}}]})
        done = n.finish()[0]
        self.assertEqual(done.kind, E.DONE)
        self.assertGreater(done.meta["estimated"], 0)
        self.assertNotIn("usage", done.meta)

    def test_finish_prefers_usage(self):
        n = E.Normalizer("openai")
        n.feed({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}})
        done = n.finish()[0]
        self.assertEqual(done.meta["usage"]["total"], 3)


class TestEventSerialization(unittest.TestCase):
    def test_roundtrip(self):
        ev = E.Event(3, "2026-01-01T00:00:00+00:00", E.TEXT, text="你好", tokens=2)
        back = E.Event.from_json(ev.to_json())
        self.assertEqual(back.to_dict(), ev.to_dict())

    def test_json_is_compact(self):
        ev = E.Event(1, "", E.TEXT, text="a")
        self.assertNotIn(", ", ev.to_json())


if __name__ == "__main__":
    unittest.main()
