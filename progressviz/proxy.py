"""流式反向代理：字节原样转发，旁边解析 SSE 记事件。

为什么是代理而不是 SDK 包装：
- 不改调用方任何代码，换个 base_url 就行
- 对前端、脚本、别的语言都一视同仁
- 拿到的就是最原始的流，不会因为 SDK 抽象丢掉细节
"""

from __future__ import annotations

import codecs
import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit

from .events import ERROR, Event, Normalizer, parse_sse_block, split_sse

# 逐跳头不能转发，否则会破坏连接语义
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


class ProxyConfig:
    def __init__(
        self,
        upstream: str,
        provider: str | None = None,
        on_event: Callable[[Event], None] | None = None,
        timeout: float = 300.0,
    ):
        u = urlsplit(upstream)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError(f"upstream 必须是 http(s)://host[:port]，收到 {upstream!r}")
        self.upstream = upstream
        self.scheme = u.scheme
        self.host = u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.base_path = u.path.rstrip("/")
        self.provider = provider
        self.on_event = on_event
        self.timeout = timeout

    def connect(self) -> http.client.HTTPConnection:
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.host, self.port, timeout=self.timeout)

    def join(self, path: str) -> str:
        return self.base_path + path if self.base_path else path

    def emit(self, event: Event) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 - 渲染器出错不能拖垮转发
            pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        self._forward("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._forward("POST")

    # ---------------------------------------------------------------- 核心
    def _forward(self, method: str) -> None:
        cfg: ProxyConfig = self.server.cfg  # type: ignore[attr-defined]

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        # 关键：让上游不要压缩，否则我们解析的是 gzip 字节
        headers["Accept-Encoding"] = "identity"

        try:
            conn = cfg.connect()
            conn.request(method, cfg.join(self.path), body=body, headers=headers)
            resp = conn.getresponse()
        except Exception as exc:  # noqa: BLE001
            self._fail(f"upstream 连接失败: {exc}")
            return

        self.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() in HOP_BY_HOP:
                continue
            self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        normalizer = Normalizer(cfg.provider)
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buf = ""

        try:
            while True:
                chunk = resp.read1(4096)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break

                buf += decoder.decode(chunk)
                blocks, buf = split_sse(buf)
                for block in blocks:
                    payload = parse_sse_block(block)
                    if payload is None:
                        continue
                    for event in normalizer.feed(payload):
                        cfg.emit(event)

            # 末尾可能还有一个没有空行结尾的块
            tail = decoder.decode(b"", final=True)
            buf += tail
            if buf.strip():
                payload = parse_sse_block(buf)
                if payload is not None:
                    for event in normalizer.feed(payload):
                        cfg.emit(event)
        finally:
            for event in normalizer.finish():
                cfg.emit(event)
            conn.close()

    def _fail(self, message: str) -> None:
        cfg: ProxyConfig = self.server.cfg  # type: ignore[attr-defined]
        cfg.emit(Event(0, "", ERROR, text=message))
        try:
            payload = message.encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception:  # noqa: BLE001
            pass


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], config: ProxyConfig):
        super().__init__(addr, _Handler)
        self.cfg = config


def serve(config: ProxyConfig, host: str = "127.0.0.1", port: int = 8787) -> ProxyServer:
    return ProxyServer((host, port), config)


def serve_in_thread(config: ProxyConfig, host: str, port: int) -> tuple[ProxyServer, threading.Thread]:
    server = serve(config, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
