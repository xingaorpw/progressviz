"""估算「AI 工作过程可视化」四种设计的 token 成本。

核心区分（这是整件事的关键）：
  观察  = 读已经产生的流式事件     -> 0 额外 token
  自述  = 让模型汇报自己在干什么   -> 额外输出，而且永久留在历史里
  回注  = 把进度日志塞回 prompt    -> 额外输入，还可能击穿 prompt cache

数字全部可复现，改下面的常量就能试别的规模。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---- 可调参数 -------------------------------------------------------------
TURNS = 20          # 一个任务多少轮
BASE = 2000         # system prompt + 任务描述
TOOL_OUT = 500      # 每轮工具返回 / 文件内容
MODEL_OUT = 400     # 每轮模型输出
CACHE_PRICE = 0.1   # 命中 prompt cache 的输入按 10% 计价
CACHE_RATIO = 0.9   # 稳定前缀里 90% 能命中缓存

NARRATION = 250     # 让模型自述进度时，每轮多写的 token
LOG_STEP = 100      # 进度日志每轮增长多少 token


@dataclass
class Result:
    name: str
    total_in: int = 0
    total_out: int = 0
    cost: float = 0.0
    note: str = ""


def simulate(name: str, *, narrate: bool = False, log: str = "none") -> Result:
    """log: none / end（追加在末尾）/ middle（插在历史中间，击穿缓存）"""
    r = Result(name)
    history = BASE          # 历史会一直累积
    log_tokens = 0

    for i in range(TURNS):
        # 本轮要发给模型的输入
        if log == "end":
            log_tokens = LOG_STEP * (i + 1)
            prompt = history + log_tokens
            cacheable = history          # 前缀没被改动，缓存仍然有效
        elif log == "middle":
            log_tokens = LOG_STEP * (i + 1)
            prompt = history + log_tokens
            cacheable = BASE             # 只有 base 稳定，历史被挤到后面
        else:
            prompt = history
            cacheable = history

        cached = int(cacheable * CACHE_RATIO)
        r.total_in += prompt
        r.cost += cached * CACHE_PRICE + (prompt - cached)

        out = MODEL_OUT + (NARRATION if narrate else 0)
        r.total_out += out

        # 历史增长：工具返回 + 模型输出（自述的也算，会复利）
        history += TOOL_OUT + out

    return r


def main() -> None:
    base = simulate("A 纯观察（推荐）")
    rows = [
        base,
        simulate("B 模型自述进度", narrate=True),
        simulate("C 进度回注到末尾", log="end"),
        simulate("D 进度回注到中间", log="middle"),
    ]

    print(f"\n任务规模：{TURNS} 轮，每轮工具返回 {TOOL_OUT}，"
          f"模型输出 {MODEL_OUT}，起始上下文 {BASE}\n")

    head = f"{'方案':<18}{'输入':>10}{'输出':>9}{'合计':>10}{'相对 A':>10}{'等效成本':>10}"
    print(head)
    print("-" * len(head.encode("gbk", "ignore")))

    b_in, b_out = base.total_in, base.total_out
    b_tok = b_in + b_out
    for r in rows:
        tok = r.total_in + r.total_out
        delta = (tok / b_tok - 1) * 100
        print(
            f"{r.name:<18}{r.total_in:>10,}{r.total_out:>9,}{tok:>10,}"
            f"{delta:>+9.1f}%{r.cost:>10,.0f}"
        )

    print("\n等效成本 = 命中缓存的部分按 10% 计价后的加权值（越小越便宜）")

    # 中断能省多少
    print("\n—— 中途打断能省多少 ——")
    saved_out = int(MODEL_OUT * 0.7)
    print(f"在第 {TURNS} 轮 30% 处打断，省下约 {saved_out} 输出 token + 后续整轮的工具调用")
    print(f"如果一轮 800 输出、打断 5 次：省 {int(800 * 0.7 * 5):,} token，"
          f"而且省掉的是白干的活")

    # 缓存击穿的真实倍数
    print("\n—— 回注位置的差别 ——")
    c, d = rows[2], rows[3]
    print(f"同样多的日志，放末尾 {c.cost:,.0f}，插中间 {d.cost:,.0f}，"
          f"贵 {d.cost / c.cost:.1f}x")
    print("原因：插在中间会让后面整段历史失去缓存，全部按原价重算。")


if __name__ == "__main__":
    main()
