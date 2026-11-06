"""Progress Viz 的 UI 回归测试。

没有浏览器自动化框架，就用 headless Edge 灌一段驱动脚本，
等虚拟时间走到目标点，dump DOM，断言结构。

每个用例跑一遍独立的 HTML 副本，互不干扰。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "index.html"
WORK = ROOT / "_tmp"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge() -> str:
    for p in EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    raise SystemExit("找不到 Edge")


EDGE = find_edge()


def render(name: str, driver: str, budget: int) -> str:
    """把驱动脚本注进去，跑一段虚拟时间，返回去掉 script/style 的 DOM。"""
    html = SRC.read_text(encoding="utf-8")
    if driver:
        html = html.replace("</body>", f"<script>{driver}</script></body>")
    assert "</body>" in html

    WORK.mkdir(exist_ok=True)
    page = WORK / f"{name}.html"
    page.write_text(html, encoding="utf-8")

    out = WORK / f"{name}.dom.html"
    with out.open("w", encoding="utf-8") as fh:
        subprocess.run(
            [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--virtual-time-budget={budget}", "--dump-dom", page.as_uri()],
            stdout=fh,
            stderr=subprocess.DEVNULL,
            timeout=180,
        )
    raw = out.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"<script>.*?</script>", "", raw, flags=re.S)
    raw = re.sub(r"<style>.*?</style>", "", raw, flags=re.S)
    return raw


def text_of(dom: str, el_id: str) -> str:
    m = re.search(rf'id="{el_id}">([^<]*)<', dom)
    return m.group(1) if m else ""


def statuses(dom: str) -> list[str]:
    return [m for _, m in re.findall(r'data-i="(\d+)"[^>]*data-status="(\w+)"', dom)]


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))


# ---------------------------------------------------------------- 用例
def case_gate() -> None:
    dom = render("gate", "", 16000)
    check("失败时弹出介入面板", 'class="gate"' in dom)
    for label in ("改指令重跑", "让它自己想", "停在这里"):
        check(f"面板有「{label}」", label in dom)
    check("有倒计时", "后自动选择" in dom)
    st = statuses(dom)
    check("失败的步骤标成 failed", st.count("failed") == 1, str(st))


def case_full_run() -> None:
    dom = render("full", "", 34000)
    check("跑完状态为完成", text_of(dom, "statusText") == "完成", text_of(dom, "statusText"))
    check("总共 11 个步骤", len(statuses(dom)) == 11, str(len(statuses(dom))))
    check("token 合计 8240", text_of(dom, "fTokens") == "8,240", text_of(dom, "fTokens"))
    check("出现成本归因", 'class="attr"' in dom)
    check("归因 11 行", dom.count('class="attr-row') == 11, str(dom.count('class="attr-row')))
    check("归因结论正确", "2.9" in dom)


def case_edit_branch() -> None:
    driver = """
      const iv = setInterval(() => {
        const b = document.querySelector('.gate button[data-choice="edit"]');
        if (b) { b.click(); clearInterval(iv); }
      }, 120);
    """
    dom = render("edit", driver, 40000)
    check("走人工路径后出现「按人工提示调整」", "按人工提示调整" in dom)
    check("走人工路径后出现「改测试断言」", "改测试断言" in dom)
    check("默认路径被替换掉（无「分析失败」）", "分析失败" not in dom)
    check("默认路径被替换掉（无「更新测试」）", "更新测试" not in dom)
    check("替换后仍是 11 步", len(statuses(dom)) == 11, str(len(statuses(dom))))
    check("人工路径也能跑到完成", text_of(dom, "statusText") == "完成", text_of(dom, "statusText"))


def case_abort() -> None:
    driver = "setTimeout(() => document.getElementById('abortBtn').click(), 7000);"
    dom = render("abort", driver, 26000)
    check("中断后状态为已中断", text_of(dom, "statusText") == "已中断", text_of(dom, "statusText"))
    used = text_of(dom, "fTokens").replace(",", "")
    check("中断后 token 少于全量", used.isdigit() and int(used) < 8240, used)
    check("中断后没有归因面板", 'class="attr"' not in dom)


def case_replay() -> None:
    driver = """
      setTimeout(() => {
        const b = document.getElementById('replayBtn');
        b.click();
        setTimeout(() => b.click(), 40);
        setTimeout(() => b.click(), 80);
      }, 9000);
    """
    dom = render("replay", driver, 45000)
    check("连点三次重放不崩", len(statuses(dom)) == 11, str(len(statuses(dom))))
    check("重放后能跑到完成", text_of(dom, "statusText") == "完成", text_of(dom, "statusText"))
    check("归因只出现一份", dom.count('class="attr-row') == 11, str(dom.count('class="attr-row')))


def case_pause() -> None:
    driver = "setTimeout(() => document.getElementById('pauseBtn').click(), 6000);"
    a = render("pause_a", driver, 12000)
    b = render("pause_b", driver, 24000)
    check("暂停后状态为已暂停", text_of(a, "statusText") == "已暂停", text_of(a, "statusText"))
    ea, eb = text_of(a, "elapsed"), text_of(b, "elapsed")
    check("暂停后计时不再增长", ea == eb, f"{ea} -> {eb}")
    check("暂停后步骤不再推进", statuses(a) == statuses(b))


def case_theme() -> None:
    dom = render("theme", "", 2000)
    check("默认亮色主题", 'data-theme="light"' in dom)
    check("有主题切换按钮", 'id="themeBtn"' in dom)


def main() -> int:
    cases = [
        ("默认流程", case_theme),
        ("失败拦截", case_gate),
        ("完整跑通", case_full_run),
        ("人工改指令分支", case_edit_branch),
        ("中断分支", case_abort),
        ("连续重放", case_replay),
        ("暂停", case_pause),
    ]
    for title, fn in cases:
        print(f"\n▶ {title}")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(f"{title} 执行异常", False, repr(e))

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 62)
    for name, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        extra = f"  [{detail}]" if detail and not ok else ""
        print(f"  {mark}  {name}{extra}")
    print("=" * 62)
    print(f"{passed}/{len(RESULTS)} 通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
