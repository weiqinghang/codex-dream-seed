# Dream Console 改进承诺闭环：Implementation Design 与 Architecture Readiness

状态：`review candidate`
需求状态：[`#13`](https://github.com/weiqinghang/codex-dream-seed/issues/13) 仍为
`Backlog` / `backlog::shaping`
产品契约：
[`../../design/dream-console-commitment-closure-v1.md`](../../design/dream-console-commitment-closure-v1.md)
差距与切片：
[`06-commitment-closure-gap-and-slicing.md`](06-commitment-closure-gap-and-slicing.md)

本文把已经批准的产品契约转换为可委派、可独立验收的工程合同。它不实施产品代码，不代表
Requirement 已经 Ready，不决定稳定版本或 Milestone，也不替代 GitHub Issue 与唯一 Project
Status。

## 1. 决策摘要

1. **Projection first**：Slice 1 只从现有 Candidate、User Action、Adoption、Validation 和
   lifecycle timeline 派生承诺 read model，不写 Workspace，不新增第二套生命周期。
2. **确认动作是身份锚点**：V1 的 `commitment_id` 使用用户确认试用计划时创建的根
   `ACT-*`。调整只增加同一承诺的版本；不同假设或范围必须形成新的确认动作和新的承诺。
3. **状态名不是业务事实**：`proven` 只表示验证证据结论，`rolled_back` 只表示历史状态声明；
   它们不能单独证明有效固化完成或真实回滚完成。
4. **保守兼容**：历史记录缺少身份、日期、时区或验证证据时显示 `unknown`。投影可以用内部
   `projection_key` 保持卡片稳定并保守计数，但不得猜测或写回业务身份。
5. **真实终态只有三类**：有效固化完成、人工无效结束、已验证回滚。证据不足、继续观察、
   调整继续、handoff 失败、回滚 requested/pending/failed 都继续占用 WIP。
6. **到期事实统一但不覆盖历史**：trial reminder、Validation 期限和 override review date
   统一投影为 due 状态；每次延期追加新决定，不修改旧日期和旧理由。
7. **依赖保持独立且不伪造 Ready**：公共读取必须满足
   [`#12`](https://github.com/weiqinghang/codex-dream-seed/issues/12) 的只读安全合同。#12 尚未完成
   时，#13 即使通过方案审阅也继续保持 Backlog/Shaping；真实回滚执行与验证由
   [`#8`](https://github.com/weiqinghang/codex-dream-seed/issues/8) 提供，#8 只在 Slice 4
   进入 Ready 前成为硬门。

## 2. 当前实现事实与不得伪造的能力

当前实现已经提供：

- Candidate 的人的 `accepted|rejected|superseded` 决定；
- 确认试用后创建的 `enter_trial` User Action、trial plan、Board snapshot 与 handoff attempt；
- `planned|applied|rolled_back` Adoption；
- `pending|validating|proven|failed|inconclusive` Validation；
- Validation contract adjustment history、逐项 criterion assessment 与人的 decision source；
- Workspace-local Board policy、带理由的 trial WIP override；
- Candidate → Action → Adoption → Validation 的确定性 Board 投影。

当前实现不能证明：

- 同一 Candidate 下的业务假设、范围或版本必然属于同一承诺；
- `proven` 之后目标载体已经完成固化和必要验证；
- `rolled_back` 之前目标载体已经实际撤销并验证；
- `inconclusive` 是人工继续观察、调整继续还是历史上的“结束为未定”；
- `reminder_date`、Validation 最大天数和 override review date 已形成统一、可恢复的期限事实；
- Console 公共读取没有隐式初始化或修改 SQLite；该安全缺陷仍由 #12 跟踪。

因此实现必须从事实组合派生业务语义，不能把已有状态字段改名后直接宣称满足新契约。

## 3. 承诺领域模型

### 3.1 Read model 合同

每个承诺投影至少返回：

| 字段 | 类型 / 值 | 合同 |
| --- | --- | --- |
| `commitment_id` | `ACT-*` 或 `unknown` | 根确认动作；不从标题、Candidate 文本或最近记录猜测 |
| `projection_key` | 稳定内部字符串 | 历史身份未知时用于刷新稳定与保守计数，不对外冒充业务身份 |
| `identity_status` | `known|unknown|conflicted` | 多条根动作或断裂 lineage 必须显式冲突 |
| `root_action_id` | `ACT-*|unknown` | 与 `commitment_id` 同锚点，便于 handoff/审计追踪 |
| `candidate_id` | `CAN-*|unknown` | 原始候选 |
| `current_version` | 正整数或 `unknown` | 确认计划为版本 1；每次有效调整递增 |
| `version_lineage` | 版本数组 | 包含 parent、发生时间、人的来源、假设和范围摘要 |
| `confirmed_at` | UTC timestamp 或 `unknown` | 根确认动作的 `created_at` |
| `stage` | 现有 Board stage | UI 位置，不等于终态事实 |
| `active` | `true|false|unknown` | WIP 计数以此为准 |
| `terminal` | `true|false|unknown` | 只由本节规定的终态证据派生 |
| `release_reason` | 见 3.4 | 释放原因，不复用底层状态名 |
| `due` | 见第 5 节 | 统一期限投影及来源 |
| `rollback_state` | 见第 7 节 | 与 #8 的执行接口状态 |
| `source_refs` | 稳定 ID 集合 | 只含 `ACT-*`、`CAN-*`、`ADP-*`、`VAL-*` 等裁剪 ID |
| `warnings` | 枚举集合 | `legacy_unknown`、`identity_conflict`、`unverified_rollback` 等 |

`projection_key` 不能写入公开知识或被当作未来业务外键。它只允许由已有稳定 ID 组合形成，例如
身份未知的历史链路可使用最靠后的 `VAL-*`、`ADP-*` 或 `CAN-*` 作为本地投影键。

### 3.2 身份与并行规则

- 用户确认试用计划、系统成功建立根 `enter_trial` action 后，该根 `ACT-*` 成为
  `commitment_id`，`confirmed_at` 使用其 `created_at`。
- 同一次承诺的继续观察、合同调整、证据追加、handoff retry 和复核延期都引用同一个根
  `ACT-*`，不得分配新承诺。
- “调整继续”生成 `current_version + 1`，保留旧版本、旧证据和 parent version。
- 用户确认不同假设、不同目标载体或不同作用范围的并行实验时，必须形成新的根确认动作；
  即使它们来自同一 Candidate，也分别占用 `1` WIP。
- 标题、文本相似度、Knowledge ID、Candidate ID、Adoption ID 或 Validation ID 均不能单独
  合并两个承诺。
- 一个根动作链接到多个互相不兼容的 Candidate/范围时，`identity_status=conflicted`，投影
  fail closed：不合并、不释放、进入“最需要解阻”。

### 3.3 版本不变量

每个已知身份的版本记录至少包含：

- `version`、`parent_version`；
- `hypothesis`、`scope`、`target_carrier` 的裁剪摘要；
- `effective_at`、`decision_source`、`reason`；
- 对应 Validation contract version 或稳定引用；
- `next_review_at` 或明确的 `unknown`。

版本号只在人的“调整继续”决定成功持久化后递增。重复请求使用同一 idempotency key 返回原结果；
stale `expected_version` 必须拒绝。失败写入、页面重试或 handoff retry 不得凭空增加版本。

### 3.4 Active、terminal 与释放原因

用户确认试用计划后 `active=true`。只有下列事实之一成立才允许
`active=false`、`terminal=true`：

| `release_reason` | 必需事实 | 明确不足的事实 |
| --- | --- | --- |
| `effective_solidified` | 人选择有效固化；目标载体落实完成；必要验证完成且可追溯 | 仅 `Validation=proven`、仅 handoff completed |
| `invalid_ended` | 人选择无效结束；理由、证据摘要、决定来源和版本完整 | 仅负向证据、仅 `inconclusive`、系统自动判断 |
| `rollback_verified` | 人选择回滚；#8 执行成功；目标状态验证成功 | 仅请求回滚、handoff completed、`Adoption=rolled_back` |

缺少终态证明时：

- `terminal=false`，`active=true`；
- `release_reason=null` 或 `unknown`；
- 进入收尾或解阻入口；
- 不允许通过换列、改状态名、延期或删除期限释放容量。

### 3.5 保守计数

- 已知 `commitment_id` 按身份去重，同一承诺所有版本合计为 `1`。
- 不同根动作分别计数，即使 Candidate 或标题相同。
- 历史身份未知但存在活动试用事实时，每条不重叠的最下游链路保守计为 `1`，同时显示
  `identity_status=unknown`；不得为了降低 WIP 猜测合并。
- 同一稳定下游链路在不同 Board/API 中必须使用同一 `projection_key`，避免重复计数。
- `decision_pending` Inbox 与真实终态不计活动 WIP；到期未决定、handoff 失败、回滚未验证
  仍计数。

## 4. Projection-first 与最小持久化阈值

### 4.1 决策表

| 所需事实 / 行为 | 先用现有事实派生 | 允许的最小持久化 | 触发持久化或 Schema 评审的阈值 |
| --- | --- | --- | --- |
| 身份、confirmed-at | 根 `enter_trial ACT-*` 与 `created_at` | 无 | 无根动作或根动作冲突时只显示 unknown；不得补写 |
| 同一承诺版本 | Validation contract history + 完成的 adjust action | 新 action payload 引用 root/version | 现有记录无法保证 parent/version/CAS 时才增加 append-only 字段 |
| active / WIP | Action、Adoption、Validation 与 closeout 事实组合 | 无 | 只有跨刷新不能稳定重建且合成反例证明歧义时评审 |
| 真实终态 | human action + 执行/验证证据组合 | append-only closeout/verification action | 不能用现有 User Action 安全表达幂等与证据引用时评审 |
| trial / validation due | trial plan、started-at、max days | append-only schedule/extension action | 需要保存人的新复核点和延期历史时允许最小写入 |
| override review | 现有 override reason 和 Board snapshot | append-only override decision，补齐 review date 与 impacted IDs | 现有 snapshot 缺字段，必须从首次新 override 起写；历史保持 unknown |
| rollback state | 根 rollback action / handoff / #8 verification | 仅保存 #8 定义的 operation reference 与结果 | 不得在 #13 自建逆操作引擎或把 `rolled_back` 当验证 |
| 首页三维与流量 | 上述 read model 与事件 | 无派生缓存 | 性能测量证明实时投影不可接受后才评审可重建缓存 |

### 4.2 持久化门

任何实现 PR 若要改变 Workspace、Knowledge Schema 或 SQLite schema，必须同时提交：

1. 一个合成反例，证明 projection-only 无法无歧义恢复必需事实；
2. 被拒绝的无 Schema 方案及原因；
3. 最小字段/事件/约束定义，且不复制 Candidate/Adoption/Validation 全量数据；
4. 相邻迁移、dry-run、备份、恢复和旧引擎 fail-closed 合同；
5. 历史缺失值仍为 `unknown`，迁移不得推测生成身份、时区、期限或验证结果；
6. macOS、Linux、Windows 与 Python 3.9–3.13 的迁移/读写矩阵；
7. 独立 Reviewer 对数据丢失、错误合并、隐式写入和不可逆回退的反证。

允许优先增加现有 `user_actions.payload_json` 的版本化、append-only action 类型；只有需要数据库级
唯一性、外键或原子不变量且应用层 CAS 无法可靠保证时，才允许最小 SQLite 结构变化。派生缓存
不是事实源，必须可删除并从 canonical facts 完整重建。

## 5. Due、overdue、override review 与延期历史

### 5.1 统一期限来源

每个承诺可以同时存在：

1. `trial_reminder`：确认试用计划时选择的日期；
2. `validation_window`：Validation `started_at + max_validation_days`；
3. `override_review`：每次 WIP 超限决定的最晚复核日期；
4. `human_review`：继续观察或调整继续时选择的下一复核点。

read model 保留全部开放来源，并以最早未解决 deadline 作为 `effective_due_at`。不能用更晚的
新期限覆盖更早的未解决义务。

### 5.2 时间、时区与显示

- 持久 timestamp 使用带时区的 ISO 8601，并规范化为 UTC `Z`。
- 人选择的日历日期必须同时保存 IANA timezone；不保存机器当前 timezone 的隐式假设。
- date-only deadline 使用该时区“所选日期之后的第一个 00:00”作为 UTC exclusive deadline：
  所选日期内显示 `due_today`，下一本地日开始后显示 `overdue`。
- Validation duration 从带时区 `started_at` 加整数天得到精确 deadline；UI 同时显示用户时区
  下的日期。
- 无法解析、缺 timezone 或历史 date-only 字段不得默认为本机时区，返回 `unknown`。
- 所有计算接收显式 `now` / clock，禁止测试依赖真实 `date.today()`。

统一状态：

- `unknown`：历史字段不足或格式冲突；
- `unscheduled`：新合同要求复核点但尚未成功保存；
- `upcoming`：未进入 due-soon window；
- `due_soon`：进入可配置且确定性的提前窗口；
- `due_today`：用户本地日期到期；
- `overdue`：超过 exclusive deadline，返回非负 `overdue_days`；
- `resolved`：对应义务已有新决定或真实终态。

### 5.3 延期与幂等

每次延期必须是新记录，包含：

- `commitment_id`、`version`、原 due record reference；
- 新日期、IANA timezone、规范化 deadline；
- `reason`、`decision_source`、`decided_at`；
- `request_id` / idempotency key 与 `expected_version`。

同一 `request_id` 重放返回已存在结果；不同请求若使用 stale version 必须拒绝。页面刷新失败后
先读回 action，再决定是否重试。不得原地更新旧 due、复用旧理由、自动滚动日期或静默续期。

### 5.4 Override 审计

新的 override 决定至少保存：

- 被超限的阶段；
- 当时 limit、实际量和本次动作后的实际量；
- 全部受影响承诺的稳定 ID；
- 释放容量方案或为何仍需超限；
- override reason、最晚复核日期、timezone；
- 人的决定来源、发生时间、根 action 和当前版本。

到达 review date 后，该 override 进入 due read model 和 Human Closeout Gate。延期必须追加新
override review 决定。软约束不得变成自动拒绝，也不得在字段缺失时静默放行。

## 6. Human Closeout Gate 兼容映射

### 6.1 五选方向

| 人的方向 | 新业务事实 | 现有状态兼容 | WIP |
| --- | --- | --- | --- |
| 有效固化 | `solidification_requested → applying → verified` | `proven` 只是证据输入；verified 前不终态 | verified 后释放 |
| 调整继续 | 新 version + 新复核点 | `validation_contract_adjusted` 可复用 | 始终占 `1` |
| 继续观察 | 新复核点 + reason | `validation_continue` 可复用 | 始终占 `1` |
| 无效结束 | human `invalid_end` 决定 | 有 decision source 的 `failed` 可兼容投影 | 释放，不计有效采纳 |
| 回滚 | `requested → pending → failed|verified` | 依赖 #8；legacy `rolled_back` 不足 | verified 后释放 |

### 6.2 旧状态的诚实解释

| 旧事实 | 新投影 | 禁止推断 |
| --- | --- | --- |
| `pending|validating` | active validation | 不自动选择继续或结束 |
| `proven` | evidence outcome proven；需要有效固化落实/验证 | 不等于 completed 或 adopted |
| `failed` + traceable human decision | invalid ended | 不计有效采纳 |
| `inconclusive` | `closeout_direction=unknown`、active、需要人重新选择 | 不当作无效结束，不释放 |
| `Adoption=rolled_back`，无 #8 verified evidence | `legacy_unverified`、active、warning | 不证明目标已恢复 |
| handoff `completed`，无 Adoption/Validation | active + blocked | 不等于试用落实或终态 |
| handoff `failed` | active + blocked | 不释放 |

状态迁移必须保留原词作为 `source_status`，UI 使用新的业务标签并显示兼容警告；不得重写历史文件
来制造新事实。

## 7. 回滚接口与 #8 边界

#13 只负责 closeout 选择、承诺 WIP 和状态投影，不实现逆操作。接口合同为：

1. 人选择“回滚”后创建或引用一个带 `commitment_id`、version、target carrier、attempt 和
   verification contract 的 rollback operation/handoff；
2. `requested|pending|claimed|failed` 均为活动承诺，失败可按正式 retry 保留 attempt history；
3. #8 在执行前提供只读预览并校验目标、fingerprint、attempt 和漂移；
4. #8 执行实际撤销并完成结果验证后，提供稳定 operation reference、verified timestamp 和
   裁剪结果；
5. #13 只在读到该 verified evidence 后投影 `release_reason=rollback_verified`；
6. 普通 handoff `completed`、字符串 `rolled_back` 或 Console toast 不能替代 verified evidence。

若 #8 尚未提供 verified 接口，Slice 4 只能交付 requested/pending/failed 的闭环与持续占 WIP，
不得临时发明“一键回滚”或降级验收。

## 8. #12 只读边界

所有新增 GET、Board、Home、Context、due 和 flow read model 必须：

- 使用 #12 规定的 SQLite URI `mode=ro` 与 `PRAGMA query_only=ON`；
- 在读取前检查数据库存在性和 schema 兼容性；
- 缺库、不兼容或无法只读打开时 fail closed；
- 不调用 `initialize()`、不创建目录/数据库、不执行 DDL、不更新 schema metadata；
- 读取 knowledge JSON 时不创建 index、summary、timeline 或默认字段；
- 用逻辑 dump/hash 或等价证据证明读取前后 Workspace 不变。

#12 的实现不并入 #13 Slice。当前 `origin/develop` 的公共读取仍存在调用写入式
`initialize()` 的路径，#12 也仍为 OPEN / Backlog / Shaping；因此没有可作为实施基线的
canonical 修复或完成 writeback。

在 #12 的实现合并、默认集成分支读回、Issue writeback 和唯一 Project 状态共同证明完成前：

- #13 必须继续保持 Backlog / `backlog::shaping`；
- Slice 1 也保持 Backlog / `backlog::shaping`，不得进入实施；
- “architecture ready but dependency blocked”只能作为普通说明，不能新建状态、标签或平行
  workflow；
- Reviewer PASS 或本设计 PR 合并都不能替代依赖事实，也不能把“实施 PR 标记 blocked”冒充
  Ready。

#12 完成后，Slice 1 必须直接复用其 canonical 只读入口，不得复制临时 helper。写动作仍走
显式锁、审计和幂等路径。

## 9. 历史 Workspace 与迁移/回滚

### 9.1 历史降级

- 缺根 action：`commitment_id=unknown`，保守计数，不生成新 ID。
- 缺 `confirmed_at`、timezone、due 或 next review：显示 `unknown` / `unscheduled`。
- `inconclusive` 或 legacy `rolled_back`：不释放，要求人的新决定或 verified rollback evidence。
- lineage 断裂或多根冲突：`identity_status=conflicted`，进入解阻入口。
- API 不省略未知字段；使用明确 `null` 加 `status=unknown`，避免客户端把缺失理解为 false。

### 9.2 迁移

若持久化门触发：

- 只支持相邻版本迁移，先 dry-run、再显式 apply；
- 迁移前创建可恢复备份并记录 manifest/checksum；
- 迁移只复制和校验已有事实，不生成推测值；
- 新引擎读取旧版本时提示 migration required；旧引擎读取新版本时 fail closed；
- 中断后能够识别未完成 migration，不允许部分版本继续写；
- 验证 ID 唯一性、lineage 完整性、事件数量、原始事实 checksum 和只读投影等价性。

回滚采用备份恢复或明确的相邻逆迁移；若逆迁移会丢失新事实，则禁止自动降级并要求用户选择
保留新 Workspace 或从备份恢复。产品代码回滚不等于 Workspace 数据回滚。

## 10. 首页、Board 与结果流量的共同 read model

首页、Board、详情和 Console Context 必须消费同一承诺集合，不能各自实现计数或终态判断。

三维推荐使用确定性原因：

- **最值得收尾**：due/overdue、证据已足、关键反证、继续占用容量收益低；
- **最需要解阻**：identity conflict、handoff failed、missing contract、unscheduled、rollback
  failed、长期无新证据；
- **容量 / 释放容量方案**：当前各阶段 capacity、受影响承诺以及只有三种真实终态才能释放的
  可解释方案。

同一承诺跨维度去重为一张主卡，保留全部 reason codes。每维允许为空，不使用黑盒总分保证
“Top 3”。

结果流量从事件事实派生并分开展示：

- `trial_confirmed`；
- `effective_solidified`；
- `adjusted_continue`；
- `invalid_ended` / `rollback_verified`；
- `due_undecided`。

不得把 `proven`、handoff completed、rollback requested 或卡片移入 done 计入有效采纳；不得
生成单一闭环率。成对流量可以展示，但必须可回到具体承诺、版本、决定和证据。

## 11. Slice 依赖与实施 WIP

| Slice | GitHub 子项 | 目标 | 前置依赖 | 初始治理状态 |
| --- | --- | --- | --- | --- |
| 1 | [#15](https://github.com/weiqinghang/codex-dream-seed/issues/15) | 承诺 read model 与计数不变量 | #12 完成、合并、默认分支读回与 writeback；本设计 | Backlog / shaping；依赖满足后才成为首个实施 WIP |
| 2 | [#16](https://github.com/weiqinghang/codex-dream-seed/issues/16) | 软约束与 override review | Slice 1 | Backlog / shaping |
| 3 | [#17](https://github.com/weiqinghang/codex-dream-seed/issues/17) | 站内 due/overdue 闭环 | Slice 1；Slice 2 的 review due 事实 | Backlog / shaping |
| 4 | [#18](https://github.com/weiqinghang/codex-dream-seed/issues/18) | 五选 Gate 与真实终态 | Slice 1、3；Slice 4 Ready 前必须有 #8 verified rollback 接口 | Backlog / shaping |
| 5 | [#19](https://github.com/weiqinghang/codex-dream-seed/issues/19) | 三维首页与结果流量 | Slice 1–4 | Backlog / shaping |
| 6 | [#20](https://github.com/weiqinghang/codex-dream-seed/issues/20) | 下一次 Dream/Skill 提醒 | Slice 3 的统一 due read model | Backlog / shaping；不阻塞 MVP |

默认一次只有一个 Slice 进入实施 WIP。#12 完成前，父 #13 和 Slice 1 都不进入 Ready。#12
完成并读回后，父 #13 才具备“可立即开始首个 Slice”的必要条件；届时首先只推进 Slice 1。
后续 Slice 在前一 Slice 完成验证与 writeback、依赖成立后再推进。#8 不阻塞 Slice 1–3，
但在 Slice 4 进入 Ready 前必须完成 verified rollback 接口及其证据。Slice 6 不阻塞 Slice 1–5
MVP，也不扩展到邮件、系统通知或常驻后台服务。

## 12. 每个 Slice 的验证合同

所有实现 Slice 必须：

1. 只使用纯合成 Workspace、项目和稳定测试 ID；
2. 先建立领域不变量与反例测试，再改实现；
3. 运行 Console runtime tests、完整 unittest、bundled Skill validation、前端语法、
   privacy audit 与 `git diff --check`；
4. 对受影响的 API/UI 做真实浏览器旅程；
5. 在 Linux、macOS、Windows 与 Python 3.9–3.13 支持矩阵验证；
6. 由独立 Reviewer 反证身份错误合并/重复计数、证据不足释放 WIP、静默延期、请求回滚冒充
   已回滚、状态名伪造事实、历史猜测回填、只读隐式写入和单一闭环率。

额外必测：

- 同一承诺多版本只计 `1`，同 Candidate 的并行范围/假设分别计数；
- handoff pending/claimed/failed/completed-without-adoption 均不释放；
- `proven` 未落实、`inconclusive`、legacy `rolled_back` 均不错误释放；
- timezone 跨日、夏令时、闰日、重复提交、stale version、刷新失败后重试；
- override 影响清单、期限、旧记录和延期历史完整；
- 页面空态、unknown、超限、逾期、多重触发、窄屏和键盘访问；
- 读模型调用前后 SQLite/Knowledge 逻辑内容不变。

## 13. 隐私与安全

- 运行时事实只存在用户 Workspace；仓库 fixture 纯合成。
- API、浏览器证据、Issue、PR 和可分享工件只使用稳定裁剪 ID、枚举、时间和摘要。
- 不返回原始消息、真实 Session 标识、绝对用户路径、私有知识正文、目标文件内容、凭证或
  未裁剪 rollback evidence。
- 目标载体指纹和恢复证据按 #8 放在私有 `state/`；公开 Knowledge/Report 只保留必要摘要。
- 写动作需要本机 action token、Workspace lock、expected version、idempotency key 和人的
  decision source；读动作不获取写锁来掩盖隐式写入。

## 14. 兼容、发布与 feature rollout 风险

- `develop` 是允许不完整集成的开发渠道；Slice 合并不代表稳定产品可用。
- Slice 1 的纯 read model 可以先落地，但在 Slice 5 完成前不得把局部 API 宣传成完整承诺闭环。
- 不建立永久双写或第二套状态。若阶段性需要 capability flag，只能作为 Workspace-local、
  可移除的展示门，canonical facts 始终是现有生命周期与新 append-only 决定。
- 旧 Workspace 按第 9 节诚实降级；新 schema 不允许被旧引擎静默写入。
- 稳定发布前必须完成全 OS/Python 矩阵、浏览器旅程、迁移/恢复演练、文档/Skill 同步和独立
  release review。
- 稳定版本、Milestone、发布时间和是否分阶段启用仍由产品所有者决定；不得移动 `v0.4.0`，
  产品代码晋升必须推进 `product` 并创建匹配的新 immutable annotated tag。
- feature rollout 的主要风险是：部分 Slice UI 暴露、旧/新状态混算、迁移后无法降级、#8/#12
  依赖未满足、不同操作系统时区行为不一致。发布门必须逐项给出证据，不能以 CI green 代替。

## 15. Ready gate

#13 只有在以下事实全部读回后才可由 Supervisor 决定推进 Ready：

- 本设计在 `develop` 成为 canonical，并链接到 #13；
- Slice 1–6 均有唯一 GitHub 子 Issue、稳定 AC、验证合同、依赖和兼容边界；
- 父子关系、首个 Slice 和单 Slice WIP 规则可从 GitHub 恢复；
- #12 已完成实现、合并、默认集成分支读回和结构化 writeback，使 Slice 1 可以合法立即开始；
- #8/#12 边界明确，没有把依赖复制进 #13；#8 在 Slice 4 Ready 前另行验门；
- independent Reviewer 对本设计、最终 diff 和 GitHub 状态返回 PASS；
- PR CI、完整测试、Skill validation、privacy 与 live governance audit 通过；
- #13 固定字段完整，仍未伪造稳定版本或 Milestone 决策。

产品契约 `approved`、文档 `review candidate`、Reviewer PASS、测试 green 或 PR merged 任一
单独事实都不等于 Ready。当前 #12 未完成，所以 Phase 2 即使其余门全部通过，#13 仍保持
Backlog / `backlog::shaping`，只在普通进展说明中记录方案已成形但依赖未满足。未经依赖读回与
Supervisor 最终核验，不修改 #13 Project Status 或 `backlog::ready-for-dev` 标签。

## 16. AC 映射

| 父 AC | 工程承载 |
| --- | --- |
| AC-CC-01 | 第 1、10、13 节；Console 只投影/决策，Codex 执行 |
| AC-CC-02 | 第 3、4 节；根 action 身份、版本 lineage、三类释放原因 |
| AC-CC-03 | 第 10 节；三维确定性 read model 与去重原因 |
| AC-CC-04 | 第 3.5、5.4 节；分阶段 policy、Inbox/终态排除、软约束 |
| AC-CC-05 | 第 5 节；完整 override record、复核日期、append-only 延期 |
| AC-CC-06 | 第 5、10、12 节；统一 due 状态、刷新恢复和浏览器旅程 |
| AC-CC-07 | 第 6、7 节；五选 Gate 与 #8 verified rollback |
| AC-CC-08 | 第 10 节；五类流量与禁止单一闭环率 |
| AC-CC-09 | 第 11 节 Slice 6；只在下一次主动触发提醒 |
| AC-CC-10 | 第 4、8、9、12–15 节；合成、隐私、迁移、矩阵和发布门 |
