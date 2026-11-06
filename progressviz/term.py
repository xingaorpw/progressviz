"""终端渲染器：把事件流打印成能看的进度。

不引入 rich/textual，是因为这个工具的定位是"零依赖、放进任何环境都能跑"。
颜色用 ANSI，检测到非 TTY 或 NO_COLOR 就自动关。
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

from .events import DONE, ERROR, TEXT, THINKING, TOOL, USAGE, Event

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"


def supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


class TermRenderer:
    def __init__(self, stream: TextIO | None = None, color: bool | None = None):
        self.stream = stream or sys.stdout
        self.color = supports_color(self.stream) if color is None else color
        self._at_line_start = True
        self._thinking = False
        self.steps = 0

    # ---------------------------------------------------------------- 内部
    def _c(self, code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def _write(self, text: str) -> None:
        if not text:
            return
        self.stream.write(text)
        self.stream.flush()
        self._at_line_start = text.endswith("\n")

    def _newline_if_needed(self) -> None:
        if not self._at_line_start:
            self._write("\n")

    # ---------------------------------------------------------------- 渲染
    def handle(self, event: Event) -> None:
        kind = event.kind

        if kind == THINKING:
            if not self._thinking:
                self._newline_if_needed()
                self._write(self._c(MAGENTA, "◆ 思考  "))
                self._thinking = True
            self._write(self._c(DIM, event.text))

        elif kind == TEXT:
            if self._thinking:
                self._write("\n")
                self._thinking = False
            self._write(event.text)

        elif kind == TOOL:
            self._newline_if_needed()
            self._thinking = False
            self.steps += 1
            self._write(self._c(CYAN, f"⚙ {event.name}\n"))

        elif kind == USAGE:
            self._newline_if_needed()
            inp = event.meta.get("input", 0)
            out = event.meta.get("output", 0)
            self._write(
                self._c(
                    DIM,
                    f"   token  in {inp:,} · out {out:,} · 合计 {event.tokens:,}\n",
                )
            )

        elif kind == DONE:
            self._newline_if_needed()
            meta = event.meta if isinstance(event.meta, dict) else {}
            usage = meta.get("usage")
            if usage:
                total = int(usage.get("total", 0))
                tag = ""
            else:
                total = int(meta.get("estimated", 0))
                tag = self._c(YELLOW, " (估算)")
            self._write(
                self._c(GREEN, f"✓ 完成") + f"  {self.steps} 个工具调用 · {total:,} token{tag}\n"
            )

        elif kind == ERROR:
            self._newline_if_needed()
            self._write(self._c(RED, f"✕ {event.text}\n"))
