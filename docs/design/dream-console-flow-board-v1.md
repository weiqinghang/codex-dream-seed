# Dream Console 推进 Board 与用户旅程（V1）

状态：0.4.0 已实现并完成本地端到端验收。Board 是主推进视图，单项时间线是详情视图；
owner/blocker overlay 与 intake-vs-closeout 趋势保留为后续增强，不阻塞本版闭环。

## 1. Outcome

Dream Console 要帮助用户限制进行中工作，而不只是持续发现和采纳改进。用户打开 Console
后，应能在一个视图内判断：哪里堆积、哪项停留过久、什么已经可以验收、什么应调整或结束，
以及开始一项新试用会挤占哪一项既有承诺。

Console 保持确定性边界：它依据可解释规则计算 WIP、老化和缺口，不调用模型、不替用户作出
语义决策，也不直接修改项目或环境。需要分析或执行时，仍通过 Console → Codex handoff 接续。

## 2. 现有数据能否支持

结论：现有 V2 模型可以支持第一版 Board 和真实 WIP 盘点，但不能完整支持梦境阶段耗时、
逐条验收进度、阻塞责任与可配置 WIP 治理。第一版应复用现有事实源生成只读投影，并把缺口
作为后续故事补齐，不能新造一套平行生命周期。

### 2.1 已可直接或确定性派生

| 需求 | 当前来源 | 结论 |
| --- | --- | --- |
| Dream 身份、标题、范围、起止时间 | `dream_runs` | 支持 |
| 用户体感、原本预期、证据核对结果 | `scope_json.user_anchor`、`summary_json.user_anchor_result` | 支持 native Dream；历史导入记录允许未知 |
| 候选身份、状态、范围、项目、提出时间 | knowledge item `candidates[]` | 支持 |
| 试用目标、状态、开始时间 | `adoptions[]` | 支持 |
| 验证状态、开始时间、最大天数、目标样本 | `validations[].contract` | 支持 |
| 已观察、eligible、compliant、正反证据数 | `validations[].evidence[]` | 支持确定性聚合 |
| Console handoff 状态与试用提醒日期 | `user_actions` | 支持由 Console 发起的试用 |
| 当前生命周期与下一步基础文案 | `ConsoleService._lifecycle` | 支持，但需提升为统一 Board projection |
| 状态 WIP 数量 | 上述实体的当前状态 | 支持确定性计算 |

在私有 Workspace 上进行的只读审计确认上述字段已经能形成真实 WIP 和“建议验收”信号；
真实 ID、数量和 Dream 结果不进入可分发 seed。测试只使用 synthetic fixtures。这说明 Board
不需要等待新模型即可暴露未闭环负担。

### 2.2 仍缺少的信息

| 缺口 | 影响 | 推荐补法 |
| --- | --- | --- |
| Dream 只有 `active/completed`，没有阶段事件 | 无法显示同步、复盘、持久化、隐私审计各阶段耗时与失败点 | 新增 append-only `dream_run_events`，由现有 CLI 边界写入 |
| 没有直接的 Candidate → Dream lineage | 卡片不能稳定回答“由哪次 Dream 发现” | 通过 `candidate.task_refs` 与 `dream_run_tasks` 派生；无法派生时显示未知，不伪造 |
| 成功标准只有文本数组，没有逐条状态 | 只能显示样本进度，不能声称验收项已满足 | 增加独立、可审计的 criterion assessment，不覆盖原 contract |
| 没有 owner、blocked reason、blocked since | 无法区分等待用户、等待样本和无主停滞 | 增加 operational control overlay；不得写回知识成熟度状态 |
| WIP limit 与 aging threshold 未配置 | 只能显示数量，不能给出稳定超限建议 | 增加 workspace-local board policy，提供建议默认值并允许用户调整 |
| 非 Console 建立的旧试用没有 reminder | 无法统一提醒 | 允许缺省；首次用户操作时补齐，不回填猜测日期 |
| 没有 WIP override / snooze 决定 | 用户无法有意识地超限 | 复用 `user_actions` 记录带理由的 override、defer 与 closeout 决定 |

## 3. Board 信息架构

Board 的列表示状态，卡片表示当前需要管理的工作对象；项目或作用范围可以作为泳道和筛选器。
一个改进线程只在最靠后的有效阶段显示一张主卡，避免 Candidate、Adoption、Validation 重复计入
WIP。卡片保留所有关联 ID，进入详情后展示完整生命周期。

| Column | 主实体 | 进入条件 | 离开条件 | 建议初始 WIP |
| --- | --- | --- | --- | --- |
| 待决策 Inbox | CAN | candidate 为 proposed，且未处于有效 defer | 拒绝、暂缓或确认试用 | 不设上限，不计活动 WIP |
| 试用落实 | ACT/ADP/CAN | 试用已确认，正在接续或落实；或 applied 但尚无 validation | 建立 validation、回滚或结束 | 3 |
| 验证中 | VAL | validation pending/validating | proven、failed 或 inconclusive | 5 |
| 待收尾 | VAL/ACT | 样本已达目标、期限到期、冲突证据或接续失败 | 用户确认继续、调整、固化或结束 | 3 |
| 已暂缓 | CAN | 用户设置的 defer 仍有效 | 提醒到期后重新进入待决策，或用户提前恢复 | 不计 WIP |
| 已结束 | 任意 | completed/rejected/superseded/rolled_back/proven 等终态 | 只保留近期窗口 | 不计 WIP |

WIP 数量必须按主卡去重。Dream 运行过程在独立“梦境”页面观察，不占改进承诺 WIP；尚未被
用户拉入试用的候选是 Inbox，也不占 WIP。默认限制是建议值，不是强制政策；用户可以超限，
但必须看到被挤占的既有承诺，并为 override 留下理由。

列内排序不修改事实状态。用户可以选择：价值与影响面从高到低（先比较显式 `value_impact`，
再比较 session/project/cross_project/global 作用范围）、提出时间早到晚或晚到早、来源 Dream
提及次数从多到少。卡片必须显示相同指标，使排序理由可见。

## 4. 卡片契约

每张卡在不展开时必须回答五个问题：是什么、在哪、多久、缺什么、下一步是什么。

```json
{
  "card_id": "VAL-0042",
  "entity_type": "validation",
  "stage": "closeout",
  "title": "限制进行中工作验证",
  "scope": "global",
  "projects": ["cross-project"],
  "age_days": 7,
  "health": "attention",
  "progress": {"current": 3, "target": 3, "unit": "eligible_tasks"},
  "evidence_summary": {"positive": 3, "negative": 0, "inconclusive": 0},
  "acceptance": {"status": "review_required", "missing": ["human_final_decision"]},
  "next_action": "确认固化、调整或结束验证",
  "source_dream_ids": ["DREAM-0040"],
  "related_ids": ["KD-0041", "CAN-0042", "ADP-0042", "VAL-0042"]
}
```

浏览器响应不得包含原始 Session 文本、完整本地路径或 Session UUID。无法从事实源可靠计算的
字段必须返回 `unknown` 或空列表，不能用最近更新时间冒充阶段开始时间。

## 5. 确定性 Advisor

Advisor 只根据公开规则产生建议，并同时返回触发证据：

1. `wip_exceeded`：列 WIP 超过建议限制；优先建议处理最接近完成和最老的卡片。
2. `closeout_ready`：eligible 样本达到目标，但 Validation 尚未进入终态。
3. `aging`：当前阶段停留超过合同期限或 workspace policy。
4. `missing_acceptance`：已经应用，但没有 Validation 或成功标准。
5. `stalled`：长时间没有新证据、next action、owner 或 blocker reason。
6. `intake_outpaces_closeout`：窗口期内进入试用数持续高于 proven/ended 数。

排序固定为：可立即收尾 → 超期/阻塞 → 缺验收 → 计划调整 → 新候选。Console 提供“回到
Codex 处理”指令，不自行执行建议。

## 6. 端到端用户旅程

1. 用户在 Codex 中开始一次 Dream，确认 user anchor、范围和排除项。
2. Dream 运行状态和历史留在“梦境”页面，不占改进承诺 WIP。
3. Dream 完成后，新候选进入“待决策 Inbox”，并保留来源 Dream。
4. 用户打开 Console，先看到 WIP 总览、最老卡片和最多三个确定性建议。
5. 用户按价值/影响面、提出时间或 Dream 提及次数排序，并结合项目/范围筛选。
6. 用户打开卡片详情，查看状态时间线、证据、反例、成功标准、范围和下一步后果。
7. 对候选，用户选择暂缓、拒绝或进入试用；WIP 已满时，Console 先展示需要收尾或调整的
   既有卡片，并要求记录超限理由。
8. 进入试用后，Console 生成 handoff 并进入“试用落实”；Codex 领取后建立 Adoption 和 Validation，并回写结果。
9. 后续 Dream 将新证据追加到 Validation；Board 更新样本进度、正反证据和阶段年龄。
10. 达到目标、到期或出现冲突信号时，卡片进入“待收尾”，而不是无限留在“验证中”。
11. 用户选择继续、调整、固化或结束；最终决定必须可追溯，卡片才进入“已结束”。
12. 首页持续展示采纳与完成的流量差，帮助用户在开始新试用前管理已有承诺。

## 7. 用户故事与迭代顺序

### Slice 1：Board read model 与真实 WIP（现在）

**作为** Dream 用户，**我希望** Console 返回按状态去重的卡片、WIP 数量和可解释建议，
**从而**先看见当前负担，而不修改任何知识状态。

验收：

- `/api/board` 返回稳定列、主卡、WIP count/limit 和 advisories。
- Candidate/Adoption/Validation 只显示最靠后的主卡；终态不计 WIP。
- Validation 进度只统计 `eligibility=eligible` 的证据。
- 样本达到目标时产生 `closeout_ready`；WIP 超限时产生 `wip_exceeded`。
- 私有路径、原始消息和 Session UUID 不进入响应。

### Slice 2：Board 页面与筛选

**作为**用户，**我希望**按列浏览卡片并按项目、范围、健康度筛选，**从而**快速找到拥塞点。

验收：响应式 Board、Inbox 与活动 WIP 分离、列头 WIP/上限/最老年龄、可解释排序、卡片五问
元数据、键盘可访问、窄屏列表退化。

### Slice 3：Dream 阶段事件与单卡时间线

**作为**用户，**我希望**看到一次 Dream 在同步、复盘、持久化和隐私审计各阶段的耗时，
**从而**区分正常长任务和真正停滞。

验收：append-only phase events、安全失败/恢复状态、历史 Dream 明确标记阶段未知、详情时间线。

### Slice 4：WIP policy 与软门禁

**作为**用户，**我希望**调整每列建议上限，并在超限采纳时看到代价，**从而**有意识地管理承诺。

验收：workspace-local policy、默认建议值、带理由 override、无静默阻塞、完整审计。

### Slice 5：验收项与收尾动作

**作为**用户，**我希望**逐条复核成功标准并选择继续、调整、固化或结束，**从而**让试用形成终态。

验收：criterion assessment 与原 contract 分离、最终决定 human-gated、调整保留旧版本证据。

### Slice 6：老化、阻塞和计划调整

**作为**用户，**我希望**系统指出长期无进展、缺 owner/next action 或计划失真的卡片，**从而**及时
收尾或缩小范围。

验收：blocker/owner overlay、aging thresholds、intake-vs-closeout 趋势、最多三个首页建议。

## 8. 非目标

- 不把 Console 变成新的 workflow controller 或项目管理系统。
- 不让浏览器调用模型、自动采纳、自动固化或修改目标项目。
- 不把 Dream、Candidate、Adoption、Validation 压成一个不可追溯的状态字段。
- 不用 Token 总量或卡片数量单独判断质量；它们只是提示进一步复核的信号。
