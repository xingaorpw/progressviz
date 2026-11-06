"""CI 冒烟检查：demo 跑完后，产物必须满足这些条件。"""

from __future__ import annotations

import sys

from progressviz.store import read_events, summarize


def main(path: str = "runs/ci.jsonl") -> int:
    events = list(read_events(path))
    info = summarize(path)

    problems = []
    if len(events) < 10:
        problems.append(f"事件太少: {len(events)}")
    if info["tokens"] != 2267:
        problems.append(f"token 对不上: {info['tokens']} != 2267")
    if info["tokens_source"] != "usage":
        problems.append(f"token 来源应为 usage，实际 {info['tokens_source']}")

    kinds = info["by_kind"]
    for kind in ("thinking", "text", "tool", "usage", "done"):
        if not kinds.get(kind):
            problems.append(f"缺少事件类型: {kind}")

    if problems:
        print("冒烟检查失败：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(info, file=sys.stderr)
        return 1

    print("冒烟检查通过")
    print(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
