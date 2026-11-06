"""把各家 LLM 的流式分片，归一化成同一种事件形状。

设计原则：
- 归一化只做"形状统一"，不做状态机。上游给什么就记什么。
- 不认识的分片直接丢弃，不让它污染事件流。
- 所有函数都是纯函数，方便单测。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# 事件类型
START = "start"
THINKING = "thinking"
TEXT = "text"
TOOL = "tool"
USAGE = "usage"
DONE = "done"
ERROR = "error"

KINDS = (START, THINKING, TEXT, TOOL, USAGE, DONE, ERROR)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Event:
    seq: int
    ts: str
    kind: str
    text: str = ""
    name: str = ""
    tokens: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> "Event":
        d = json.loads(line)
        return cls(
            seq=d.get("seq", 0),
            ts=d.get("ts", ""),
            kind=d.get("kind", ""),
            text=d.get("text", ""),
            name=d.get("name", ""),
            tokens=d.get("tokens", 0),
            meta=d.get("meta") or {},
        )


# ---------------------------------------------------------------- SSE 解析
def split_sse(buffer: str) -> tuple[list[str], str]:
    """把累积缓冲切成若干完整事件块，返回 (块列表, 剩余不完整部分)。

    SSE 用空行分隔事件；跨 TCP 分片的情况必须靠这个函数兜住。
    """
    blocks: list[str] = []
    # 统一换行，避免 \r\n 造成切割失败
    buffer = buffer.replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n" in buffer:
        block, buffer = buffer.split("\n\n", 1)
        if block.strip():
            blocks.append(block)
    return blocks, buffer


def parse_sse_block(block: str) -> dict[str, Any] | None:
    """解析单个 SSE 块里的 JSON payload。`[DONE]` 和心跳返回 None。"""
    lines = [ln[5:].lstrip() for ln in block.split("\n") if ln.startswith("data:")]
    if not lines:
        return None
    raw = "\n".join(lines).strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


# ---------------------------------------------------------------- 各家归一化
def normalize_openai(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    """OpenAI / DeepSeek / 通义等兼容 chat.completions 的流。"""
    out: list[tuple[str, str, str]] = []
    for choice in payload.get("choices") or []:
        delta = choice.get("delta") or choice.get("message") or {}

        # DeepSeek-R1 等把思维链放在 reasoning_content
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            out.append((THINKING, reasoning, ""))

        content = delta.get("content")
        if isinstance(content, str) and content:
            out.append((TEXT, content, ""))

        for call in delta.get("tool_calls") or []:
            fn = call.get("function") or {}
            name = fn.get("name")
            if name:
                out.append((TOOL, "", str(name)))
    return out


def normalize_anthropic(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Anthropic Messages API 的流。"""
    out: list[tuple[str, str, str]] = []
    kind = payload.get("type")

    if kind == "content_block_start":
        block = payload.get("content_block") or {}
        if block.get("type") == "tool_use":
            out.append((TOOL, "", str(block.get("name", ""))))
        elif block.get("type") == "thinking":
            out.append((THINKING, "", ""))

    elif kind == "content_block_delta":
        delta = payload.get("delta") or {}
        if delta.get("type") == "thinking_delta":
            out.append((THINKING, str(delta.get("thinking", "")), ""))
        elif delta.get("type") == "text_delta":
            out.append((TEXT, str(delta.get("text", "")), ""))
        elif delta.get("type") == "input_json_delta":
            pass  # 工具参数，暂不展示

    return out


NORMALIZERS = {
    "openai": normalize_openai,
    "anthropic": normalize_anthropic,
}


def detect_provider(payload: dict[str, Any]) -> str:
    """按 payload 形状猜是哪家。猜不出就按 openai 处理。"""
    if "type" in payload and str(payload["type"]).startswith("content_block"):
        return "anthropic"
    if "message" in payload and isinstance(payload.get("message"), dict):
        if payload["message"].get("usage") is not None:
            return "anthropic"
    if payload.get("type") in ("message_start", "message_delta", "message_stop"):
        return "anthropic"
    return "openai"


def normalize(payload: dict[str, Any], provider: str | None = None) -> list[tuple[str, str, str]]:
    """统一入口，返回 (kind, text, name) 三元组列表。"""
    provider = provider or detect_provider(payload)
    fn = NORMALIZERS.get(provider, normalize_openai)
    return fn(payload)


# ---------------------------------------------------------------- usage
def extract_usage(payload: dict[str, Any], provider: str | None = None) -> dict[str, int] | None:
    """从分片里抠出 usage。没有就返回 None（别瞎猜）。"""
    usage = payload.get("usage")
    if usage is None and isinstance(payload.get("message"), dict):
        usage = payload["message"].get("usage")
    if not isinstance(usage, dict):
        return None

    provider = provider or detect_provider(payload)
    if provider == "anthropic":
        inp = int(usage.get("input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
    else:
        inp = int(usage.get("prompt_tokens") or 0)
        out = int(usage.get("completion_tokens") or 0)

    if inp == 0 and out == 0:
        return None
    return {"input": inp, "output": out, "total": inp + out}


def estimate_tokens(text: str) -> int:
    """没有 usage 时的粗估。中文按 1.5 字/token，其余按 4 字符/token。

    这个数字只用来显示"大概花了多少"，不能用来记账。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(round(cjk / 1.5 + other / 4))


class Normalizer:
    """带序号和 token 累加的状态化归一化器。"""

    def __init__(self, provider: str | None = None):
        self.provider = provider
        self.seq = 0
        self.usage: dict[str, int] | None = None
        self.estimated = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def feed(self, payload: dict[str, Any]) -> list[Event]:
        events: list[Event] = []
        if self.provider is None:
            self.provider = detect_provider(payload)

        for kind, text, name in normalize(payload, self.provider):
            tokens = 0
            if text:
                tokens = estimate_tokens(text)
                self.estimated += tokens
            events.append(
                Event(self.next_seq(), now(), kind, text=text, name=name, tokens=tokens)
            )

        usage = extract_usage(payload, self.provider)
        if usage:
            self.usage = usage
            events.append(
                Event(self.next_seq(), now(), USAGE, tokens=usage["total"], meta=usage)
            )
        return events

    def finish(self) -> list[Event]:
        meta: dict[str, Any] = {"estimated": self.estimated}
        if self.usage:
            meta["usage"] = self.usage
        return [Event(self.next_seq(), now(), DONE, tokens=0, meta=meta)]
