# 参与贡献

感谢你愿意花时间。这个项目不大，规则也简单。

## 先跑起来

```bash
git clone https://github.com/xingaorpw/progressviz.git
cd progressviz
pip install -e .
python -m progressviz demo              # 不需要 API key
python -m unittest discover -s tests -t . -v
```

测试必须全绿再提交。

## 提 Issue

有用的 bug 报告长这样：

```
环境：Windows 11 / Python 3.12
命令：python -m progressviz proxy --upstream https://api.openai.com
现象：代理返回 200，但终端没有任何事件
预期：应该看到 thinking / text / tool
补充：我用的客户端是 XXX，请求头里有 Content-Encoding: gzip
```

- 带上**完整命令**和**完整报错**
- 说明上游是哪家、用的什么客户端
- 如果是事件解析错，附一段脱敏后的 SSE 原文

## 提 PR

- 一个 PR 只做一件事
- 改了逻辑就加测试，改了行为就更新 README
- 提交信息用 `feat:` / `fix:` / `docs:` / `refactor:` 开头
- 中文注释和中文文档都可以，跟现有代码保持一致

## 几个硬约定

**不要引入第三方依赖。** 现在的卖点是「零依赖、放进任何环境都能跑」。
想加 `requests` / `rich` / `flask` 之前先开 issue 讨论——大概率会被拒。

**不要破坏字节透传。** 代理必须让客户端拿到和直连完全一样的字节流。
`tests/test_proxy.py::test_forwards_bytes_and_records_events` 守着这条。

**不要把估算值当精确值。** 没有 `usage` 的时候只能估算，那就必须标记
`tokens_source: estimate`。把估算值伪装成真实值，比不显示更糟。

**不要为了过测试改断言。** 测试挂了先确认是实现错了还是测试写错了。
把断言放宽到「能过」不是修复。

**新增上游要加测试。** 至少覆盖：正文增量、推理增量、工具调用、usage 提取。

## 可以做的事

见 README 末尾「可以继续做的方向」。适合上手的：

- 给 `tool` 事件补参数和返回值
- 支持更多上游的归一化
- 把 token 按步骤归因

## License

提交的代码默认按 [MIT](LICENSE) 授权。
