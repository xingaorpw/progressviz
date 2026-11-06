"""事件落盘：一行一个 JSON，追加写，可以边写边读。

用 JSONL 而不是 SQLite，是因为：
- 崩溃只会丢最后一行，不会损坏整个文件
- `tail -f` 就能看，不需要任何客户端
- 回放时按行读，天然是流式的
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable, Iterator

from .events import Event


class EventStore:
    """线程安全的 JSONL 追加写入器。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = self.path.open("a", encoding="utf-8", newline="\n")

    def append(self, event: Event) -> None:
        line = event.to_json()
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def extend(self, events: Iterable[Event]) -> None:
        with self._lock:
            for e in events:
                self._fh.write(e.to_json() + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_events(path: str | Path) -> Iterator[Event]:
    """逐行读事件。坏行跳过而不是抛异常——半截写入是真实会发生的。"""
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield Event.from_json(line)
            except (ValueError, KeyError):
                continue


def summarize(path: str | Path) -> dict[str, object]:
    """统计一次运行：事件数、token、耗时、步骤分布。"""
    events = list(read_events(path))
    if not events:
        return {"events": 0, "tokens": 0, "duration_s": 0.0, "by_kind": {}}

    by_kind: dict[str, int] = {}
    for e in events:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1

    usage_event = next((e for e in events if e.kind == "usage"), None)
    done_event = next((e for e in events if e.kind == "done"), None)

    done_meta = done_event.meta if done_event and isinstance(done_event.meta, dict) else {}
    estimated = int(done_meta.get("estimated", 0) or 0)

    if usage_event is not None:
        total = usage_event.tokens or int(
            (usage_event.meta or {}).get("total", 0) if isinstance(usage_event.meta, dict) else 0
        )
        source = "usage"
    elif estimated:
        total = estimated
        source = "estimate"
    else:
        total = 0
        source = "unknown"

    return {
        "events": len(events),
        "tokens": total,
        "tokens_source": source,
        "duration_s": round(_duration(events), 2),
        "by_kind": by_kind,
        "path": str(path),
    }


def _duration(events: list[Event]) -> float:
    from datetime import datetime

    def parse(ts: str) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None

    stamps = [d for d in (parse(e.ts) for e in events) if d is not None]
    if len(stamps) < 2:
        return 0.0
    return max(0.0, (stamps[-1] - stamps[0]).total_seconds())
