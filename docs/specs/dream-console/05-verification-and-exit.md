# Dream Console 验证与退出契约 Spec

状态：`active`
适用范围：Console 用户可用性升级的完成判定

## 自动化验证

至少运行：

```text
python3 -m unittest tests.console_runtime_tests -v
python3 -m unittest discover -s tests -p "test_*.py" -v
```

并完成：

- 仓库要求的 Dream Skill 校验。
- 前端 JavaScript 语法检查。
- privacy audit。
- 相关 schema、CLI、API、锁、刷新和手册契约测试。

测试不得读取真实 `~/.codex/sessions`，只能使用合成 rollout 和合成 Workspace。

## 必测异常

- failed handoff retry/requeue 成功、非法状态、重复请求和并发冲突。
- 多 Workspace、错误 fingerprint、陈旧 `ACT-*`、事项不存在和状态变化。
- API 部分失败、写入成功但刷新失败、页面重新聚焦刷新。
- schema 不兼容、端口占用、重复启动、陈旧 PID 和服务异常退出。
- 报告目录穿越和未登记路径访问。
- Console Context 隐私裁剪。
- 手册、Skill 和 UI 状态定义漂移。

## 真实浏览器旅程

在真实浏览器验证：

1. 空 Workspace 首次指引。
2. 梦境列表时间和梦境序号降序。
3. 看板列、排序、WIP 和卡片详情。
4. 暂缓、拒绝和制定试用计划。
5. 新 Codex Session 通过 `ACT-*` 接续。
6. claim/complete/fail/retry 后的页面刷新。
7. 正负证据、进度、验收阻碍和下一步建议。
8. 成功、失败、证据不足和调整合同的收尾路径。
9. 使用指南和安全报告阅读。
10. 窄屏、空状态、错误状态和服务恢复。

## 交付纪律

- 保护已有未提交修改，不覆盖、回滚或夹带无关文件。
- 验证发现的问题必须在本 Goal 内修复并重跑相关检查。
- 完成后创建边界清晰、可回溯的 commit。
- 启动本地 Console 并保持运行，默认访问：

```text
http://127.0.0.1:8765/#home
```

## 禁止退出

- 不得在分析、设计、单项实现、测试首次失败或阶段性汇报后退出。
- 不得以难度、耗时或单次失败标记 blocked。
- 不得在五项 P0 中静默删减范围。
- 不得以测试通过替代真实浏览器旅程。
- 不得以页面存在替代 Console→Codex→Console 闭环。

## 完成条件

只有以下条件全部成立，Goal 才能完成：

- 五项 P0 均实现并验证。
- 用户旅程和手册契约成立，既有行为无回退。
- 自动化、隐私和真实浏览器验证通过。
- 改动已 commit。
- Console 服务已启动并可访问。
- 最终报告列明完成内容、验证证据、commit、真实限制和访问地址。
