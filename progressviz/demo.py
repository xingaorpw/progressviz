"""一个假的 OpenAI 兼容上游，用来零成本演示和集成测试。

没有它的话，任何人想试这个工具都得先准备 API key —— 那就没人会试。
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .events import normalize_openai


def _delta(**kwargs: Any) -> dict[str, Any]:
    return {"choices": [{"delta": kwargs, "index": 0}]}


def script() -> list[tuple[float, dict[str, Any]]]:
    """一次真实的调试过程，拆成流式分片。"""
    return [
        (0.06, _delta(reasoning_content="用户报了两个现象，方向相反，说明同一段逻辑的两个分支都有问题。")),
        (0.10, _delta(reasoning_content="先看 /api/feed 的实现。")),
        (0.06, _delta(content="我先看一下 ")),
        (0.06, _delta(content="`server.py` 里 ")),
        (0.06, _delta(content="`/api/feed` 的处理逻辑。\n\n")),
        (0.08, _delta(content="问题出在这里：缓存命中时直接返回 `stored[:k]`，")),
        (0.08, _delta(content="完全没考虑 `k` 变大；缓存不足时又生成完整 `k` 条再拼接，导致超过 `k`。\n\n")),
        (0.10, _delta(reasoning_content="修法是先算差额，最后统一截断。")),
        (0.05, _delta(content="改成先补差额、再截断：\n\n")),
        (0.05, _delta(content="```python\n")),
        (0.05, _delta(content="need = max(0, k - len(stored))\n")),
        (0.05, _delta(content="stored += picks[:need]\n")),
        (0.05, _delta(content="return stored[:k]\n")),
        (0.05, _delta(content="```\n")),
        (
            0.12,
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "run_tests", "arguments": "{}"}}
                            ]
                        },
                        "index": 0,
                    }
                ]
            },
        ),
        (0.20, _delta(content="测试通过了，49 个用例全绿。")),
        (
            0.05,
            {
                "choices": [],
                "usage": {"prompt_tokens": 1840, "completion_tokens": 427, "total_tokens": 2267},
            },
        ),
    ]


class _FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/__health"):
            payload = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        try:
            for delay, payload in script():
                time.sleep(delay)
                self.wfile.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class FakeUpstream(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start(host: str = "127.0.0.1", port: int = 0) -> tuple[FakeUpstream, str]:
    server = FakeUpstream((host, port), _FakeHandler)
    actual_port = server.server_address[1]
    return server, f"http://{host}:{actual_port}"


def count_script_events() -> int:
    """演示脚本会产出多少条归一化事件（文档和测试用）。"""
    return sum(len(normalize_openai(p)) for _, p in script())
