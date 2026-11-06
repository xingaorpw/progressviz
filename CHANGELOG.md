# Changelog

所有值得注意的变更都记在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.0] - 2026-11-06

首个可用版本。

### Added

- **流式代理**：把 `base_url` 指过来就能用，字节原样透传，旁边解析 SSE 记事件。
  不改调用方任何代码。
- **事件归一化**：OpenAI 兼容（含 DeepSeek 的 `reasoning_content`）和 Anthropic
  Messages 两种格式统一成 `thinking / text / tool / usage / done / error`。
- **终端渲染器**：思考用紫色、工具调用用青色，结束时打印 token 汇总。
  检测到非 TTY 或 `NO_COLOR` 自动关色。
- **JSONL 存储**：一行一个事件，追加写，崩溃只丢最后一行。
- **Web 回放**：`progressviz serve` 把 JSONL 通过 SSE 推给浏览器，左侧步骤列表，
  右侧详情。
- **零配置演示**：`progressviz demo` 自带假上游，不花钱、不需要 API key。
- **命令**：`demo` / `proxy` / `render` / `summary` / `serve`。
- 51 个测试，CI 覆盖 Ubuntu + Windows、Python 3.9 + 3.12，外加端到端冒烟任务。

### Fixed

- `summarize()` 在没有 `usage` 事件时错误地返回 0，估算值回退分支永远不生效。
- Web 回放的 SSE 结束哨兵带了 `data: {}`，被前端当成第 N+1 条事件。
- Web 回放用 `EventSource` 会在连接关闭后自动重连，导致整段事件重放两遍。
  改成 `fetch` + `reader` 手动读流。

[Unreleased]: https://github.com/xingaorpw/progressviz/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/xingaorpw/progressviz/releases/tag/v0.1.0
