# Handoff 恢复与 Console Context Spec

状态：`active`
适用范围：Console 与 Dream Agent 的可恢复接续

## 目标

让 Console 中确认的事项可以被任意新的 Codex Session 唯一定位、安全领取、完成、失败并恢复，同时让 Agent 读取与用户一致的隐私裁剪当前状态。

## Handoff 状态契约

支持的主路径：

`handoff_pending → claimed → completed`

支持的失败路径：

`handoff_pending|claimed → failed → handoff_pending`

`failed → handoff_pending` 必须通过正式 retry/requeue 动作完成，不允许直接修改数据库。

### Retry/Requeue 要求

- 输入至少包含 `ACT-*`、重试原因和可追溯的人类/Agent 来源。
- 保留原错误、失败时间、历史 attempt、claim 信息和每次重试记录。
- 增加 attempt 计数和最新 retry 时间。
- 拒绝非 `failed` 状态、重复请求、未知事项和并发冲突。
- retry 只恢复接续资格，不宣称试用、采用或验证已经完成。
- CLI、Console API、UI 和 Skill 必须使用同一数据面实现。

## 唯一定位指令

Console 复制指令必须包含稳定 `ACT-*`，并要求 Codex：

1. 运行 Workspace 解析/健康检查；
2. 读取指定 action 的 Console Context；
3. 核对状态、新鲜度、范围和成功标准；
4. 再执行 claim。

禁止只复制“继续处理我刚才确认的事项”。多个 Workspace、多个 handoff 或多个卡片时不得靠最近项猜测。

## `console-context` 只读能力

提供公开、确定性、隐私裁剪且可测试的 CLI/服务能力，建议命令：

```text
codex-dream console-context [--handoff ACT-*] [--card <stable-id>]
```

至少输出：

- `generated_at`
- Workspace 安全短 fingerprint 与解析来源
- Board 各列 `count/limit`
- 当前 WIP 和超限情况
- 待收尾事项
- 主要 Advisor 建议
- 相关卡片的稳定 ID、标题、状态和 `next_action`
- 指定 handoff 的范围、trial plan、成功标准、状态和 attempt
- 快照是否可能陈旧

不得输出：

- 真实 Session UUID
- 原始 rollout 路径或用户绝对路径
- 原始消息、私有 capsule 或凭证
- 未经裁剪的 Workspace 内部记录

## 新鲜度与歧义

- handoff 创建时保存必要的 Board 快照：所在列、WIP、是否超限、当时优先收尾事项。
- claim 前重新读取当前 Context，并显示快照与当前状态的差异。
- action 已完成、失败、被重新排队或范围变化时，旧复制指令不得静默执行。
- 没有 pending handoff 时，Agent 应返回当前 Advisor/待收尾摘要，而不是只说“没有事项”。

## 验收

- 新 Codex Session 不依赖聊天历史即可领取正确 `ACT-*`。
- failed handoff 可以从 UI 与 CLI 恢复，且历史完整。
- 多 Workspace、多 action、陈旧指令、重复 claim 和并发 retry 均 fail closed。
- Console Context 通过隐私审计和契约测试。
