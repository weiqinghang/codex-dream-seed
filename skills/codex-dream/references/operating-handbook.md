# Dream 操作手册

本手册是 Dream Console、Codex Agent 和 README 共用的用户语义源。Dream 分析本地
Codex 协作并形成候选；Console 确定性地展示、决策和追踪；Codex Agent 负责语义审阅
与执行；Workspace 是三者共享的事实源。

## 1. 从哪里开始

首次进入空 Workspace 时，在 Codex 中发送“开始做梦”。Dream 完成后回到 Console：
先查看梦境和候选，再作出可追溯决定；若制定试用计划，复制带 `ACT-*` 的接续指令到
新的 Codex Session。Console 不会自行调用模型，也不会替代人工决定。

## 2. 五个页面

- 首页回答“现在最值得关注什么”，并提供首次三步指引和接续状态。
- 梦境回答“每轮何时发生、审阅什么、耗时和 Token 是否有可靠记录”。
- 推进看板回答“事项在闭环的哪一步、是否超 WIP、下一步是什么”。
- 改进追踪保留完整候选池、决定、落实、验证和终态。
- 知识库回答“哪些经验已沉淀、采用和验证到什么程度”。

## 3. 看板状态

看板只有五列：`待决策`、`试用落实`、`验证中`、`待收尾`、`完成`。
`handoff_pending` 是 Console 到 Codex 的接续状态，不是泳道。暂缓项仍保留在改进追踪，
到期后重新进入关注窗口；拒绝项进入完成并保留理由。

离开条件：待决策需要人工决定；试用落实需要已确认的落实记录和验证合同；验证中需要
达到复核窗口或出现需人工判断的反证；待收尾需要人工核对所有成功标准和关键负向证据；
完成必须有可追溯终态。

## 4. 动作、结果与可逆性

- 暂缓：不改变候选事实，到提醒日期后再评估，可重新决策。
- 拒绝：记录不采纳理由并进入终态；未来只能通过新的可追溯候选重新讨论。
- 制定试用：保存范围、载体、成功标准、失败信号和提醒日期，并生成 handoff。
- 调整验证：保留既有证据，修改样本目标或观察期限，不宣称成功。
- 重试 handoff：仅把 `failed` 恢复为 `handoff_pending`，保留每次失败和 retry 历史。
- 收尾：可固化成功、验证失败、证据不足继续观察，或调整验证合同。

## 5. Console 到 Codex 接续

复制指令必须包含唯一 `ACT-*`、安全 Workspace fingerprint 和 attempt。新 Session 先运行
`codex-dream doctor`，再运行指令中的 `codex-dream console-context ...`，核对 Workspace、
状态、范围、成功标准和新鲜度，最后才 `handoff-claim`。不得靠“刚才那项”或最近项猜测。

## 6. WIP、证据和收尾

待决策是 Inbox，没有 WIP 上限；其余活动列使用 Workspace 的 WIP 策略。进度只表示
合格样本数与目标的关系，证据总数表示信息充分度。正向、负向和不确定证据必须分别保留；
正向数量不能抵消关键反证。进度到 100% 也必须逐条判断成功标准后才能收尾。

## 7. 故障恢复

- handoff 失败：在 Console 查看原错误，填写原因后正式重试，或使用
  `codex-dream handoff-retry ACT-* --reason ... --source ... --request-id ...`。
- 页面可能陈旧：先看“最后更新时间”，点击刷新；写入成功但刷新失败时不要重复提交，
  先刷新或用 `console-context` 核对事实源。
- API 部分失败：已加载区块会保留；对失败区块重试，不需要重复写操作。
- 服务停止：运行 `codex-dream-console status`，再 `codex-dream-console start`。
- Workspace 不一致：比较 fingerprint；不一致时停止 claim，修正 `--workspace`、环境配置或
  默认指针后重新读取 Context。

## 8. UI 与 CLI / Agent 对照

| UI 动作 | CLI / Agent 能力 |
| --- | --- |
| 开始做梦 | 在 Codex 发送“开始做梦”，由 Dream Skill 路由 |
| 查看当前事实 | `codex-dream console-context [--handoff ACT-*] [--card ID]` |
| 领取接续 | `codex-dream handoff-claim ACT-* --expect-fingerprint ... --expect-attempt ...` |
| 写回完成 / 失败 | `handoff-complete` / `handoff-fail` |
| 重试失败接续 | `handoff-retry` |
| 服务管理 | `codex-dream-console start|status|stop` |
| 健康与隐私 | `codex-dream doctor` / `privacy-audit` / `verify` |

## 9. 本地运行与边界

Console 默认只监听 `127.0.0.1`。`state/`、真实 Session、原始消息、绝对 rollout 路径和
凭证不得进入可分享输出；报告只允许读取 Workspace 中由 Dream run 登记的文件。任何候选
接受、拒绝、应用、验证和终态都需要可追溯的人类决定。正常流程使用解析出的同一
Workspace；`--ledger` 等覆盖仅用于受控迁移或调试，不能形成平行事实源。
