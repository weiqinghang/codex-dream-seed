# Dream Console 改进承诺闭环：0.4.0 Gap Analysis 与交付切片

状态：`planned`
分析基线：稳定产品 `v0.4.0`
产品契约：
[`../../design/dream-console-commitment-closure-v1.md`](../../design/dream-console-commitment-closure-v1.md)

唯一 Requirement：
[`#13 需求：建立 Dream Console 改进承诺闭环`](https://github.com/weiqinghang/codex-dream-seed/issues/13)

## 1. 基线与证据口径

`v0.4.0` 的 peeled commit 为稳定产品事实。当前 `origin/develop` 相对该 tag 只有需求治理类
repo-operations 变化；`codex_dream/`、`schemas/` 与 bundled Skill 产品面未发生变化。因此
本分析以当前可读产品代码和合成测试作为 `v0.4.0` 行为证据，不把后续治理提交误当成产品能力。

主要证据面：

- `codex_dream/console.py`：Board 列、WIP policy、advisory、候选确认、Validation 收尾。
- `codex_dream/knowledge.py`：Candidate、Adoption、Validation 状态、合同调整和 human decision
  要求。
- `codex_dream/console_static/app.js`：首页注意力列表、Board Advisor、WIP override 与 Closeout UI。
- `tests/test_console.py`：WIP、到期、合同调整、终态和合成隐私边界的可执行证据。
- `README.md` 与 canonical operating handbook：0.4.0 对用户公开的现有语义。

本阶段没有读取真实 Workspace、真实 Session 或私有知识，也不以历史验收记录替代当前代码证据。

### 1.1 与 active Spec 01 的关系

[`01-user-journey-and-state-semantics.md`](01-user-journey-and-state-semantics.md) 的“首页边界”
记录了 0.4.0 实施时的真实决策条件：当时“WIP 超限时把首页改成收尾行动中心”只有方案，缺少
更晚、可追溯的产品确认，因此该轮不得重做首页。该文字仍是有效历史事实，不需要回写或改写。

2026-07-29 批准的 Product Definition 与对应 GitHub Requirement Issue 构成此后新的、
可追溯确认，允许后续按本 Spec 的 Slice 1–5 打磨三维首页和承诺闭环。确认只改变未来需求边界：

- 不把 0.4.0 描述成已经具备三维首页或完整到期闭环；
- 不重开 Spec 01 已交付的基础用户旅程；
- 不因产品批准而自动进入 Ready-for-Dev；Requirement 仍须在唯一 Project 中保持
  `Backlog` / `backlog::shaping`，直到 Heavy Ready gate 和独立方案审阅成立；
- 后续实现若与 Spec 01 的基础状态语义冲突，必须显式解决兼容关系，不能以“新契约”名义静默
  回退既有行为。

## 2. 已具备的可复用基础

| 契约面 | 0.4.0 已有事实 | 可复用结论 |
| --- | --- | --- |
| Console 边界 | Console 明确不调用模型、不做语义判断、不修改目标项目；执行经 handoff 回到 Codex | 直接保留 |
| Board 与 WIP | 五列 Board；待决策无上限；活动列可配置 WIP；主卡按 Candidate 链路去重 | 可作为承诺投影基础 |
| 占用起点 | 用户确认试用计划后立即形成 `ACT-*` handoff 并进入 `trial_active` | 与契约起点基本一致 |
| 调整版本 | `validation_contract_adjusted` 保存旧合同历史，原 Validation 继续使用同一身份 | 可支持“同一承诺调整仍为 1” |
| 软约束 | 试用落实达到容量时要求 `wip_override_reason`，不会把候选静默改成终态 | 保留软门禁方向 |
| 到期信号 | Validation 达到样本目标或 `max_validation_days` 后进入 `closeout`，生成确定性 advisory | 可作为站内到期入口 |
| 人工收尾 | 最终 Validation 状态需要 `decision_source`；UI 要求逐条复核成功标准 | 可作为 Human Closeout Gate 基础 |
| 结果终态 | `proven`、`failed`、`inconclusive`、`rolled_back` 等可形成终态展示 | 需要重新校准产品含义 |
| 隐私 | Board/Context 输出稳定 ID 与裁剪字段，测试使用合成 Workspace | 继续沿用 |

## 3. 契约差距

### GAP-CC-01：没有显式、稳定的“承诺”计数合同

当前 Board 通过 Candidate → Adoption → Validation 的最靠后实体去重，能够覆盖多数单链路场景，
但没有把“同一承诺调整”和“不同假设/范围并行”定义为可验证身份规则。不同实现路径可能错误合并
或重复计数；终态释放也依赖底层实体状态，尚未逐项证明符合新契约。

需要：

- 建立确定性的 commitment identity / lineage 规则，优先从现有稳定 ID 派生；
- 明确 confirmed-at、active、terminal 与 release reason；
- 用合成 fixture 覆盖同一合同调整、范围拆分、并行假设、handoff 失败、到期未决和回滚待验证。

### GAP-CC-02：首页没有三个平衡维度

当前首页 `attention` 主要从候选和待复核事项中按统一优先分数截取最多 5 项；Board Advisor
则简单取前三条 advisory。它们没有分别保证“最值得收尾”“最需要解阻”“容量/释放容量方案”的
覆盖，也没有去重后展示多重触发原因。

需要独立、确定性的三维推荐 read model；每维允许为空，同一卡合并展示原因，完整池仍留在 Board。

### GAP-CC-03：override 审计字段不完整

当前进入试用达到 `trial_active` 上限时要求 `wip_override_reason`，并保存 Board counts、
超限列和 closeout card IDs 快照。仍缺：

- 明确受影响承诺清单，而不只是待收尾卡 ID；
- 最晚复核日期；
- 针对全部相关活动阶段的统一超限事实；
- 到期后的重新决策与禁止静默延期；
- 对“实际量已经超限”与“本次动作将达到/越过上限”的一致边界定义。

### GAP-CC-04：到期只有进入 `closeout`，没有站内闭环

当前 `max_validation_days` 能触发 aging advisory，但卡片没有统一的 due-at、即将到期、逾期天数、
override review due 等状态。`reminder_date` 保存在试用计划中，却没有成为 Board/Home 的完整
确定性提醒输入。继续/调整可以更新观察期限，但没有要求新的复核日期，也没有显式防止静默滚动。

需要把到期、逾期、复核与延期历史建成可恢复的 Workspace 事实，并贯穿 API、首页、Board、详情
和刷新恢复。

### GAP-CC-05：Human Closeout Gate 选项和语义不足

当前 UI 提供继续观察、调整合同、结束为失败、结束为未定和确认固化。它接近人的终局决策，
但仍有以下差距：

- `proven` 会直接进入完成，不能证明目标载体已完成固化和必要验证；
- `failed` / `inconclusive` 的命名与“无效结束 / 继续观察”产品语义未完全对齐；
- 没有显式“回滚”选择及其 pending/failed/verified 执行状态；
- `rolled_back` 当前可以作为 Adoption 状态写入，但不证明目标载体实际恢复。

可靠业务回滚应复用 Issue #8 的独立方案，不在本需求中伪造一键回滚。闭环实现可以先建立
“请求回滚并继续占用 WIP”的 human-gated 状态；只有 #8 所定义的执行与验证完成后进入已验证回滚。

### GAP-CC-06：结果流量未按契约拆分

现有页面显示生命周期和列计数，但没有稳定地分开展示进入试用、有效固化、调整继续、无效结束/
已验证回滚、到期未决定。也没有明确禁止把 `proven`、handoff completed 或失败结论混算为
“闭环/采纳”。

需要基于事件而非当前卡片数量生成互斥、可追溯的结果流量，并用成对视图替代单一闭环率。

### GAP-CC-07：下一次 Dream/Skill 提醒尚未形成

试用计划写入 `reminder_channel=console_and_next_codex`，但当前 Skill/CLI 没有把到期、逾期、
override 复核到期作为下一次触发时的统一提醒合同。这是优先增强，不阻塞站内 MVP。

## 4. 建议交付切片

切片按依赖顺序交付；每片都必须有独立 Issue/PR 或在 Heavy 父 Issue 下建立可追踪子项，
不得把本 Spec 当成平行 workflow 状态。

### Slice 1：承诺 read model 与计数不变量（MVP）

目标：先让“什么占 1 WIP、何时释放”成为确定性、可测试事实。

- 定义 commitment identity / version lineage、confirmed-at 和 release reason。
- 从现有 Candidate/Adoption/Validation/User Action 派生；只有证据不足时才增加最小持久结构。
- Board、Context 与详情使用同一计数器。
- 覆盖同一承诺调整、不同范围/假设并行、handoff 失败、到期未决和终态释放。
- 历史缺失字段显示 unknown，不猜测回填。

### Slice 2：完整软约束与 override 复核（MVP）

目标：让用户可以有意识地超限，同时留下可恢复的复核义务。

- 分阶段 policy 继续 Workspace-local 配置；Inbox/终态排除。
- 确认前展示受影响承诺和释放容量选项。
- 保存原因、最晚复核日期、当时上限/实际量、受影响承诺、决定来源。
- 到期后重新进入 Human Gate；每次延期追加新记录。
- 不自动提高上限、不硬阻塞、不静默放行。

### Slice 3：Console 站内到期/逾期闭环（MVP）

目标：完成从“提醒出现”到“人的新决定或终态”的站内闭环。

- 统一 trial reminder、validation max days 与 override review due 的确定性 due read model。
- 提供即将到期、到期、逾期天数和延期历史。
- 首页、Board、详情、刷新恢复使用同一事实源。
- 到期未决定继续占用 WIP。
- 覆盖跨日、时区边界、重复提交、刷新失败和历史缺失值。

### Slice 4：Human Closeout Gate 与真实终态（MVP）

目标：让人能选择五种方向，并使状态名称与业务事实一致。

- 有效固化：分离“证据成立”与“载体已落实并验证”。
- 调整继续：保留承诺身份和版本历史，仍占 `1` WIP。
- 继续观察：要求原因和下一复核点，仍占 `1` WIP。
- 无效结束：形成失败结论、释放 WIP、不计有效采纳。
- 回滚：创建可领取、可重试、可验证的执行流程；验证完成前不释放 WIP。实际逆操作依赖
  Issue #8 的方案与验收。

### Slice 5：首页三维平衡与结果流量（MVP）

目标：把有限容量的决策真正放到首页。

- 分别产生收尾、解阻、容量/释放容量建议，每维允许为空。
- 同一承诺去重并展示全部触发原因。
- 分开展示进入试用、有效固化、调整继续、无效结束/已验证回滚、到期未决定。
- 不显示单一闭环率；保留进入试用 vs 终态、有效固化 vs 无效结束等成对流量。
- 通过真实浏览器验证空态、超限、逾期、多重触发、窄屏与键盘访问。

### Slice 6：下一次 Dream/Skill 触发提醒（优先增强）

目标：用户下一次主动使用 Dream/Codex 时，不遗漏已到期的承诺。

- 在触发时读取隐私裁剪的 due/overdue/override-review context。
- 只提醒，不自动启动模型之外的后台工作，不改变承诺状态。
- 与 Console 使用同一稳定 ID、日期和 next action。
- 不阻塞 Slice 1–5 的站内 MVP；不扩展为邮件、系统通知或常驻服务。

## 5. 验证策略

每个 MVP 切片至少需要：

1. 纯合成 Workspace 的领域/数据库/Console 契约测试；
2. `python3 -m unittest tests.console_runtime_tests -v`；
3. `python3 -m unittest discover -s tests -p "test_*.py" -v`；
4. bundled Skill 校验、前端语法检查、privacy audit 与 `git diff --check`；
5. 真实浏览器旅程，覆盖确认占用、超限、到期/逾期、延期、五种 closeout 决定和刷新恢复；
6. 独立 Reviewer 以错误释放 WIP、静默延期、自动替人决定、把请求当执行完成、隐私泄漏和
   历史兼容回退为反证方向审查。

若引入 Schema/Workspace 变化，还必须提供相邻迁移、旧版本读写边界、支持 OS/Python 矩阵和
稳定发布计划。测试通过只构成验证证据，不自动代表 Ready、Done 或稳定发布。

## 6. 残余依赖与决策边界

- 可靠“回滚”执行依赖 Issue #8；本需求不得把状态改写冒充目标载体恢复。
- Issue #12 的只读数据库修复与本需求互不重复；后续实现应避免在只读投影中重新引入隐式写入。
- 生产部署、多用户审批、Console 内模型、后台推送和自动提高 WIP 均保持非目标。
- 稳定发布前必须回到产品所有者确认版本与发布窗口。
