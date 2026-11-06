"""命令行入口。"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import threading
from pathlib import Path

from . import __version__
from .demo import start as start_fake
from .events import Event
from .proxy import ProxyConfig, serve_in_thread
from .store import EventStore, read_events, summarize
from .term import TermRenderer
from .web import serve_file


def cmd_demo(args: argparse.Namespace) -> int:
    fake, url = start_fake()
    threading.Thread(target=fake.serve_forever, daemon=True).start()

    store = EventStore(args.store) if args.store else None
    if store:
        store.append(Event(0, "", "start", meta={"demo": True, "upstream": url}))

    renderer = TermRenderer()

    def on_event(event: Event) -> None:
        renderer.handle(event)
        if store:
            store.append(event)

    config = ProxyConfig(url, provider="openai", on_event=on_event)
    server, _ = serve_in_thread(config, "127.0.0.1", args.port)

    print(f"假上游 {url}")
    print(f"代理   http://127.0.0.1:{args.port}  →  发一个 fake 请求\n")

    try:
        conn = http.client.HTTPConnection("127.0.0.1", args.port, timeout=60)
        body = json.dumps(
            {
                "model": "demo",
                "stream": True,
                "messages": [{"role": "user", "content": "修复 /api/feed 的条数 bug"}],
            }
        )
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        while resp.read1(4096):
            pass
        conn.close()
    finally:
        server.shutdown()
        fake.shutdown()
        if store:
            store.close()

    if args.store:
        print(f"\n事件已写入 {args.store}\n")
        print(json.dumps(summarize(args.store), ensure_ascii=False, indent=2))
    return 0


def cmd_proxy(args: argparse.Namespace) -> int:
    store = EventStore(args.store) if args.store else None
    renderer = TermRenderer()

    def on_event(event: Event) -> None:
        renderer.handle(event)
        if store:
            store.append(event)

    config = ProxyConfig(args.upstream, provider=args.provider, on_event=on_event)
    server = serve_in_thread(config, args.host, args.port)[0]

    print(f"代理已启动  http://{args.host}:{args.port}  →  {args.upstream}")
    if args.store:
        print(f"事件写入    {args.store}")
    print("把调用方的 base_url 指到上面这个地址即可。Ctrl-C 退出。\n")

    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.shutdown()
        if store:
            store.close()
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    renderer = TermRenderer()
    count = 0
    for event in read_events(args.file):
        renderer.handle(event)
        count += 1
    if count == 0:
        print(f"没有读到任何事件：{args.file}", file=sys.stderr)
        return 1
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    print(json.dumps(summarize(args.file), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if not Path(args.file).exists():
        print(f"文件不存在：{args.file}", file=sys.stderr)
        return 1
    server = serve_file(args.file, args.host, args.port, delay=args.delay)
    print(f"回放界面  http://{args.host}:{args.port}  ←  {args.file}")
    print("Ctrl-C 退出。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="progressviz",
        description="把 AI 的工作过程变成能看的进度。",
    )
    p.add_argument("--version", action="version", version=f"progressviz {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("demo", help="零配置演示（内置假上游，不花钱）")
    d.add_argument("--port", type=int, default=8787)
    d.add_argument("--store", default="runs/demo.jsonl", help="事件写到哪里")
    d.set_defaults(func=cmd_demo)

    x = sub.add_parser("proxy", help="启动流式代理，旁边记事件")
    x.add_argument("--upstream", required=True, help="例如 https://api.openai.com")
    x.add_argument("--port", type=int, default=8787)
    x.add_argument("--host", default="127.0.0.1")
    x.add_argument("--provider", default=None, choices=["openai", "anthropic"])
    x.add_argument("--store", default="runs/session.jsonl")
    x.set_defaults(func=cmd_proxy)

    r = sub.add_parser("render", help="把事件文件重放到终端")
    r.add_argument("file")
    r.set_defaults(func=cmd_render)

    s = sub.add_parser("summary", help="统计一次运行")
    s.add_argument("file")
    s.set_defaults(func=cmd_summary)

    w = sub.add_parser("serve", help="启动 Web 回放界面")
    w.add_argument("file")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--delay", type=float, default=0.012, help="每条事件之间的间隔秒数，0 表示不等待")
    w.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except AttributeError:
            pass
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)
