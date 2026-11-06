"""Web 回放界面：读 JSONL，通过 SSE 推给浏览器。

不做"实时接入任意运行"，是因为那需要常驻服务 + 鉴权，超出了 v0.1 的范围。
回放已经能解决 90% 的问题：事后复盘、给别人看、写文章时截图。
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .store import read_events, summarize

WEB_DIR = Path(__file__).resolve().parent / "webui"


class _WebHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    @property
    def event_file(self) -> Path:
        return self.server.event_file  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            return self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/api/summary":
            return self._json(summarize(self.event_file))
        if path == "/api/events":
            return self._sse()
        self.send_error(404)

    # ---------------------------------------------------------------- 输出
    def _file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self.send_error(404, "web/index.html 不存在")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: object) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        try:
            delay = getattr(self.server, "delay", 0.012)
            for event in read_events(self.event_file):
                line = f"data: {event.to_json()}\n\n".encode()
                self.wfile.write(line)
                self.wfile.flush()
                if delay > 0:
                    time.sleep(delay)
            # 结束哨兵只发命名事件，不要再带 data —— 否则会被当成第 N+1 条事件
            self.wfile.write(b"event: end\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], event_file: Path, delay: float = 0.012):
        super().__init__(addr, _WebHandler)
        self.event_file = event_file
        self.delay = delay


def serve_file(
    event_file: str | Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    delay: float = 0.012,
) -> WebServer:
    return WebServer((host, port), Path(event_file), delay)
