# Requirements governance

## Purpose and source of truth

这套机制只管理 Codex Dream Seed 作为工具本身的需求与仓库运营事项。GitHub Issue 是需求
状态的唯一事实源；代码、PR、文档和审计报告是证据，不建立平行 backlog。真实梦境、知识、
Session 与个人 Workspace 永远不属于这里。

首版目标是用最低治理成本维持可恢复、可追踪的单维护者流程。规则的机器可读部分位于
`.github/requirements-governance.json`。

## Playbook inheritance and explicit exclusions

复用 Playbook 已熟悉的核心语义：

- Issue、Milestone；
- `sizing::micro|standard|heavy`；
- `backlog::idea|shaping|ready-for-dev|parked`；
- `workflow::backlog|ready|doing|verify|writeback|done`；
- Acceptance、Spec/Plan、Writeback。

首版明确不复用：

- Backbone、Story Map、`delivery::*`；
- 多角色编排、Delivery Runner、授权收据；
- 完整 ACTOR、Artifact Index、Architecture Baseline；
- 批量 Shaping、Agent 运行审计、GitHub Project 与自动状态机器人。

这些排除项不是改名或重造，而是针对单维护者仓库裁掉团队协作和自动交付复杂度。

## Repository boundary

治理资产只存在于 `.github/`、`docs/project/`、`scripts/`、`tests/`、`CONTRIBUTING.md`、
`AGENTS.md` 和 README 的贡献入口。它不得成为 `codex_dream` 包命令，不得进入 bundled
Skill、wheel、用户 Workspace、Knowledge Schema 或 Console。

repo-operations 资产需要进入默认 `product` 分支，GitHub 表单才会生效；这不修改 package
version、不移动或创建稳定 tag，也不构成新的 Dream 产品发布。因此纯 repo-operations
提交可以使 `product` HEAD 位于当前稳定产品 tag 之后；该例外只适用于未改变 package、
runtime、bundled Skill、Schema 或 Workspace 行为的提交。产品代码晋升仍必须创建与晋升
提交匹配的新不可变 tag。`develop` 仍是开发集成渠道。

## Lifecycle

每个 Open Issue 必须且只能有一个 workflow、一个 backlog maturity 和一个 sizing 标签。

```text
workflow::backlog
  → workflow::ready
  → workflow::doing
  → workflow::verify
  → workflow::writeback
  → workflow::done
  → close
```

| State | Entry | Exit |
| --- | --- | --- |
| Backlog | 已有脱敏 Issue、唯一标签 | 正在打磨或 parked；满足 Ready gate 后推进 |
| Ready | `backlog::ready-for-dev`；固定字段完整；Standard/Heavy 有 Spec/Plan | 建立实施分支/PR 或执行记录 |
| Doing | 实施已开始且仍符合 Issue 范围 | 实现完成，证据可逐项核对 |
| Verify | Acceptance 与验证材料已提供 | 独立验证通过 |
| Writeback | PR 用 `Related to #N` 合并 | 结构化回写完成且默认分支读回通过 |
| Done | Writeback 与读回完成 | 人工关闭 |

禁止在 Writeback 前使用 `Fixes #N` 或 `Closes #N`。关闭后若事实失效，应重新打开，设置与
当前事实一致的唯一标签，并评论说明原因。

Ready 及其后续 Doing、Verify、Writeback、Done 的稳定字段为 Summary、Why Now、Scope In、Scope Out、Acceptance Criteria、
Verification Plan、Privacy / Data Boundary、Compatibility / Release Impact、Spec / Plan。
GitHub Issue Form 生成三级标题，人工卡可使用二级标题；审计器按标题文本识别。字段不得
仅含空白、HTML comment、`TBD`、`N/A`、`_No response_` 或模板占位符。前八项始终必填；
Standard/Heavy 的 Spec/Plan 必填，Micro 可写 `Not required for Micro: <reason>`。

## Sizing and Milestones

- Micro：局部、低风险、一个清晰验收面；Issue 可兼任 Spec/Plan。
- Standard：跨多个文件或存在兼容性风险；必须有 Issue 内或链接的 Spec/Plan。
- Heavy：跨边界、高影响或难回退；必须有 Spec/Plan 与独立方案/交付审阅。

需求属于明确版本、阶段或多 Issue 交付目标时必须进入 Milestone。独立 repo-ops、调研或
parked 项可不设，但需在 Issue 解释。Sizing 代表工作与风险轮廓，不代表优先级。

## NFR-RM contract

| ID | Verifiable requirement | Failure condition |
| --- | --- | --- |
| NFR-RM-001 | GitHub 是唯一需求状态源 | 仍维护并行本地 Todo |
| NFR-RM-002 | Open Issue 标签唯一且组合合法 | `RG-001..003` 任一失败 |
| NFR-RM-003 | Issue、PR、Acceptance、验证和合并可追踪 | PR 无关联或 Done/close 前无 `RG-008` Writeback |
| NFR-RM-004 | GitHub 与仓库不含真实私有数据 | `RG-007` 命中且未人工排除 |
| NFR-RM-005 | 日常维护成本保持最小 | 需要额外 Project、机器人或重复状态载体 |
| NFR-RM-006 | 状态可从 GitHub 历史和 Writeback 恢复 | reopen 无原因或状态无法重建 |
| NFR-RM-007 | repo-ops 不伪造产品发布 | package/runtime/Skill/Schema/Workspace 被改变，或既有稳定 tag 被移动 |
| NFR-RM-008 | 规则集中且可演进 | 出现多份互相冲突的权威契约 |
| NFR-RM-009 | 治理不侵入 Dream 产品 | 资产进入包、Skill、Schema 或 Workspace |
| NFR-RM-010 | 核心规则可迁移 | 离线规则直接依赖 GitHub 网络 |

## Structured writeback

Writeback 的唯一机器可读载体是 Issue comment。评论包含
`<!-- requirements-writeback:v1 -->`，以及以下非空三级标题：

- Pull Request
- Merge Commit
- Acceptance Evidence
- Verification
- Residual Risks（没有时明确写 `None`）

Issue 先完成 Writeback 和默认分支回读，再添加 `workflow::done`，最后人工关闭。

## Read-only auditor

`scripts/audit_requirements_governance.py` 默认不写文件或远端状态：

```bash
python3 scripts/audit_requirements_governance.py --snapshot synthetic.json
python3 scripts/audit_requirements_governance.py --repo weiqinghang/codex-dream-seed
```

离线快照为 `{issues: [], pull_requests: []}`。Issue 含 `number`、`title`、`state`、`labels[]`、
`body`、`comments[{body}]`；PR 含 `number`、`state`、`body`、`merged_commit`、
`title`、`comments[{body}]`。PR comments 合并普通评论与代码审阅评论；live 模式只用
`gh api --method GET` 转换成相同结构。

输出为 `{version, source, status, findings[]}`；finding 含 `rule_id`、`severity`、
`subject`、`message`。退出码 `0` 表示 clean，`1` 表示发现治理问题，`2` 表示输入、
manifest 或只读采集失败。

| Rule | Meaning |
| --- | --- |
| RG-001 | workflow 标签唯一 |
| RG-002 | sizing 标签唯一 |
| RG-003 | backlog 标签唯一，Ready 及以后必须保持 `ready-for-dev` |
| RG-004 | Ready 及以后固定字段保持完整，占位符判定不区分大小写 |
| RG-005 | closed Issue 已 Done |
| RG-006 | 从 PR #4 起，所有状态的 PR 都有 `Related to #N` 且不含 closing keyword；#1/#2 是治理启用前历史 |
| RG-007 | Issue/PR 标题、正文及评论中 UUID、绝对用户路径、Session 路径或密钥的高风险候选 |
| RG-008 | Done/closed 有结构化 Writeback |

`RG-007` 不回显敏感值，也不自动删除或上传内容。命中时阻止 Ready/Done，并由维护者判断
假阳性。公开快照必须本身是合成或已脱敏数据。

## Requirement migration and recovery

把本地需求迁移到 GitHub 时：

1. 将问题、边界、建议和 Acceptance 脱敏后创建 GitHub Issue；
2. 读回 Issue 的正文、标签与状态；
3. 只有读回成功后才删除本地 Todo；
4. 若创建或读回失败，保留 Todo；若删除失败，在 Issue 标记迁移未完成。

删除完成后 GitHub Issue 是唯一状态源，不保留已迁移 Todo 的活跃副本。

## Evolution threshold

至少经过两个版本周期、10–20 个真实 Issue、一次 Milestone 收口，并出现第二个确有相同
需求的仓库后，才评估通用化。届时先确认规则没有硬编码本仓的标签、路径或发布分支，再决定
是否抽取 Skill 或平台适配器；在此之前只维护本仓机制。
