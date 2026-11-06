"""代理层集成测试：真的起一个假上游，真的走一遍 HTTP。"""

from __future__ import annotations

import http.client
import json
import threading
import unittest

from progressviz import demo
from progressviz.events import DONE, ERROR, TEXT, THINKING, TOOL, USAGE
from progressviz.proxy import ProxyConfig, serve_in_thread

REQUEST = json.dumps(
    {"model": "demo", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
)


def rtt(handler):
    """把假上游和代理都拉起来，返回 (proxy_port, events, cleanup)。"""
    fake, url = demo.start()
    threading.Thread(target=fake.serve_forever, daemon=True).start()

    captured = []
    config = ProxyConfig(url, provider="openai", on_event=captured.append)
    proxy, _ = serve_in_thread(config, "127.0.0.1", 0)
    port = proxy.server_address[1]

    def cleanup():
        proxy.shutdown()
        fake.shutdown()

    return port, captured, cleanup


class TestProxyRoundtrip(unittest.TestCase):
    def test_forwards_bytes_and_records_events(self):
        port, captured, cleanup = rtt(None)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request(
                "POST", "/v1/chat/completions", body=REQUEST,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            raw = resp.read()
            conn.close()
        finally:
            cleanup()

        self.assertEqual(resp.status, 200)
        # 字节必须原样透传：客户端拿到的东西和没代理时完全一样
        self.assertIn(b"data: [DONE]", raw)
        self.assertIn("测试通过".encode(), raw)

        kinds = [e.kind for e in captured]
        self.assertIn(THINKING, kinds)
        self.assertIn(TEXT, kinds)
        self.assertIn(TOOL, kinds)
        self.assertIn(USAGE, kinds)
        self.assertEqual(kinds[-1], DONE)

    def test_usage_numbers_are_exact(self):
        port, captured, cleanup = rtt(None)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request("POST", "/v1/chat/completions", body=REQUEST,
                         headers={"Content-Type": "application/json"})
            conn.getresponse().read()
            conn.close()
        finally:
            cleanup()

        usage = next(e for e in captured if e.kind == USAGE)
        self.assertEqual(usage.meta["input"], 1840)
        self.assertEqual(usage.meta["output"], 427)
        self.assertEqual(usage.tokens, 2267)

    def test_events_are_ordered(self):
        port, captured, cleanup = rtt(None)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request("POST", "/v1/chat/completions", body=REQUEST,
                         headers={"Content-Type": "application/json"})
            conn.getresponse().read()
            conn.close()
        finally:
            cleanup()

        seqs = [e.seq for e in captured]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)), "seq 不能重复")

    def test_tool_name_captured(self):
        port, captured, cleanup = rtt(None)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request("POST", "/v1/chat/completions", body=REQUEST,
                         headers={"Content-Type": "application/json"})
            conn.getresponse().read()
            conn.close()
        finally:
            cleanup()

        tools = [e for e in captured if e.kind == TOOL]
        self.assertEqual([t.name for t in tools], ["run_tests"])


class TestProxyFailure(unittest.TestCase):
    def test_unreachable_upstream_returns_502(self):
        captured = []
        # 127.0.0.1 上一个确定没有服务的端口
        config = ProxyConfig("http://127.0.0.1:9", on_event=captured.append, timeout=1)
        proxy, _ = serve_in_thread(config, "127.0.0.1", 0)
        port = proxy.server_address[1]
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("POST", "/v1/chat/completions", body=REQUEST,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
        finally:
            proxy.shutdown()

        self.assertEqual(resp.status, 502)
        self.assertTrue(any(e.kind == ERROR for e in captured))

    def test_bad_upstream_url_rejected(self):
        with self.assertRaises(ValueError):
            ProxyConfig("not-a-url")


if __name__ == "__main__":
    unittest.main()
