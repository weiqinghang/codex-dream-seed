# Dream Console 用户可用性升级 Goal

在新 Codex Session 中选择 Terra `high`，从仓库根目录执行以下目标：

```text
/goal

# Goal

## Objective
从现有实现继续完成 Dream Console 用户可用性升级，使陌生用户能够独立完成首次启动、做梦、决策、Codex 接续、失败恢复、验证和收尾。

## Source Of Truth
按顺序读取并执行：
1. `docs/specs/dream-console/01-user-journey-and-state-semantics.md`
2. `docs/specs/dream-console/02-handoff-recovery-and-console-context.md`
3. `docs/specs/dream-console/03-workspace-runtime-and-refresh.md`
4. `docs/specs/dream-console/04-operating-handbook-and-onboarding.md`
5. `docs/specs/dream-console/05-verification-and-exit.md`

同时遵守 `AGENTS.md`、当前代码、测试和既有设计文档。先检查 branch、git status 和 worktree，复用实际承载 Console 改动的工作树，保护所有已有修改。

## Scope
依次完成五份 Spec 的实现、文档、自动化验证、真实浏览器旅程和本地服务启动。五份 Spec 共同构成完整验收合同，不得只完成其中一部分。

## Out Of Scope
- 不使用或引入 Playbook。
- 不修改其他项目。
- 不读取或提交真实 Session、原始消息、UUID、绝对路径或私有 Workspace 状态。
- 不恢复已删除的看板列，不在缺少后续明确确认时重做首页信息架构。

## Operating Rules
- 使用仓库原生执行循环；根任务直接实施，不重复进行八 Agent 审计。最终高风险变更确需独立验证时，最多使用一个 Reviewer。
- 若 Spec 与当前实现冲突，先以可追溯证据判断是实现缺口还是 Spec 已过期；只有新的产品取舍、不可逆数据操作或外部权限问题才请求用户决定。
- 不覆盖用户修改，不静默缩减范围，不在分析、设计、阶段性汇报或测试首次失败处退出。

## Exit Conditions
严格满足 `05-verification-and-exit.md` 后才能标记完成。最终必须给出 P0/P1 对照、测试和浏览器证据、commit、真实限制、运行中的服务及 `http://127.0.0.1:8765/#home`。
```
