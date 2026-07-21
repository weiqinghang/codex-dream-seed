# Codex Dream Seed

Codex Dream Seed 是一套本地优先、跨项目、增量运行的 Codex 协作复盘框架。

它读取本机可访问的 Codex session，寻找三类值得长期积累的知识：

1. 已被证据证明有效、值得保留的实践；
2. 多次出现、可能抽象成 Skill、脚本、模板、检查器或规则的重复工作；
3. 当时已有信息下本可以更直接完成的绕路。

它不是一个“自动纠错机器人”。第一阶段只生成带证据的候选，不会自行修改你的
项目、`AGENTS.md`、Skills 或自动化。候选的接受、拒绝、采用和最终验证始终需要
可追溯的人工决定。

> 当前版本为 `0.4.0`，适合本地试用和框架共建。默认只支持 Codex 本机 rollout
> JSONL，且不会把 session 内容上传到任何外部服务。

## 为什么同时提供项目和 Skill

Codex Dream 不是一段提示词，而是三层系统：

```text
用户说“开始做梦”
        │
        ▼
Codex Dream Skill          语义控制面：审阅、判断、聚合、报告、人工确认门
        │
        ▼
codex-dream Python CLI     确定性数据面：发现、游标、指纹、任务树、知识生命周期
        │
        ▼
用户自己的 Workspace       私有 state + 可选择共享的 knowledge / reports
```

- **项目内核**保证增量状态、文件一致性、隐私检查和生命周期可以测试、复现和升级；
- **Skill**告诉 Codex 如何做需要上下文判断的语义复盘；
- **Workspace**属于每位用户，保存其私有运行状态和个人知识资产。

你不需要在本项目源码目录里“做梦”。安装 CLI 和 Skill 后，在任意位置初始化自己的
workspace 即可。

## 核心能力

- 同时发现 `~/.codex/sessions/` 与 `~/.codex/archived_sessions/`；
- 按最近更新时间选择范围，旧 session 后续追加内容也会重新进入待审阅队列；
- 使用稳定 session ID，而不是把 rollout 文件路径当作身份；
- 使用行号与 SHA-256 指纹区分 `new`、`append` 和 `reconcile`；
- 把 Codex 原生 parent/sub-agent rollouts 合并成一个任务树案例；
- 私有状态与可分享知识分开存储；
- 使用稳定 `KD/OBS/CAN/DEC/ADP/VAL/EVD` ID 和追加式时间线；
- 将知识成熟度、候选决定、采用状态和验证结果保持为四条独立生命周期；
- 在分享或提交前扫描 session UUID、绝对用户路径、rollout 路径和常见密钥格式；
- 测试全部使用合成 session，不读取真实历史。

## 环境要求

- Python 3.9 或更高版本；
- 本机安装并使用过 Codex；
- Codex 数据默认位于 `~/.codex`，也可以通过 `CODEX_HOME` 或 `dream.toml` 修改。

项目核心只使用 Python 标准库。构建和安装使用 `setuptools`。

支持 macOS、Linux 和 Windows。仓库 CI 会在三个系统上运行完整单元测试；Windows
路径、权限差异和 PowerShell 安装入口由专门测试覆盖。

## Clone 后由 Codex 自动引导

从 GitHub clone 后，可以直接在仓库目录告诉 Codex：

```text
安装并初始化 Codex Dream。
```

仓库 `AGENTS.md` 会让 Codex 先执行只读计划：

```bash
python3 scripts/bootstrap.py
```

Windows PowerShell 使用：

```powershell
py scripts\bootstrap.py
```

计划确认目标是本仓库 bundled Skill、已有 Dream workspace 或空目录后，Codex 会在该
安装请求授权内执行：

```bash
python3 scripts/bootstrap.py --apply
```

Bootstrap 会自动：

1. 优先使用 `uv tool`，其次 `pipx`，最后回退到 `pip --user` 安装三个 CLI；
2. 原子安装或升级 `skills/codex-dream`，避免重复嵌套目录；
3. 复用已有默认 workspace，或初始化 `~/Documents/codex-dream-workspace`；
4. 注册本机默认 workspace 并运行 `doctor`；
5. 只读预览最近 30 天的 session 数量，然后停在人工确认门。

默认运行不写任何内容。Bootstrap 不会自动建立首次 ledger，不会读取语义消息，也不会
接受或应用知识候选。需要自定义位置时传入 `--workspace <path>`。

## 手动安装项目内核

克隆后建议使用虚拟环境或 `pipx`。开发模式示例：

```bash
git clone https://github.com/weiqinghang/codex-dream-seed.git
cd codex-dream-seed
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

Windows PowerShell：

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e .
```

安装后会提供四个命令：

```text
codex-dream             workspace、session ledger、增量游标和隐私检查
codex-dream-review      生成私有任务树审阅卡
codex-dream-knowledge   管理知识、候选、采用和验证生命周期
codex-dream-console     启动只监听本机回环地址的 Dream Console
```

## 手动安装可选 Skill

将项目中的 `skills/codex-dream` 安装到你的 Codex Skills 目录。最直接的本地方式是：

```bash
cp -R skills/codex-dream ~/.codex/skills/codex-dream
```

Windows PowerShell：

```powershell
Copy-Item -Recurse skills\codex-dream "$HOME\.codex\skills\codex-dream"
```

手动复制只适合首次安装；已有 Skill 的升级使用 Bootstrap，避免平台差异和目录嵌套。

Skill 只包含语义工作流和参考协议，不保存任何用户数据。安装后可以对 Codex 说：

```text
使用 $codex-dream 开始做梦。先只读预览最近 30 天，再等我确认是否初始化。
```

也可以不安装 Skill，直接按本 README 的命令使用 CLI；但完整的语义审阅仍需要 Agent
遵循 `skills/codex-dream/references/` 中的协议。

## 创建个人 Workspace

选择一个不会与本项目源码混在一起的目录，并将它注册为本机默认 workspace：

```bash
codex-dream init ~/Documents/codex-dream-workspace --set-default
```

生成结构：

```text
~/Documents/codex-dream-workspace/
├── dream.toml                范围、节奏和 Codex 数据位置
├── .gitignore                强制忽略私有 state
├── state/                    私有：SQLite、UUID、路径、capsule、迁移备份
├── knowledge/
│   ├── index.json            稳定 ID 分配与索引
│   └── items/                脱敏知识及完整生命周期
└── reports/
    ├── weekly/               周期聚合报告
    └── reviews/              必要的专项审阅
```

先检查环境：

```bash
codex-dream doctor
```

`doctor` 会返回实际 workspace 及其解析来源。之后无论当前位于普通项目、受治理项目还是
本 seed 源码仓，`codex-dream`、`codex-dream-review` 和 `codex-dream-knowledge` 都会使用
同一个默认 workspace。当前目录只影响项目指令上下文，不会隐式把复盘范围限制为当前
项目，也不会成为新的数据目录。

workspace 解析顺序为：

```text
显式 --workspace
  → CODEX_DREAM_WORKSPACE
  → 当前目录或其父目录中的已初始化 Dream workspace
  → codex-dream set-default 注册的本机默认值
```

如果全部缺失，命令会失败并要求选择 workspace，不会在当前业务项目中静默初始化。
可以随时查看或切换本机默认值：

```bash
codex-dream show-default
codex-dream set-default ~/Documents/codex-dream-workspace
```

需要临时使用另一套 workspace 时，使用 `--workspace <path>`；需要对一个 shell 会话
覆盖默认值时，设置 `CODEX_DREAM_WORKSPACE`。

## Workspace 与知识结构升级

引擎版本、workspace schema 与 knowledge schema 是三个不同概念。只有持久化结构发生
变化时才提升 schema；普通实现调整不必制造新的知识结构版本。当前新 workspace 使用：

```text
workspace_schema = 2
knowledge_schema = 1
```

正式升级只注册相邻迁移，例如 `V0 -> V1`、`V1 -> V2`。一个落后 5～6 个版本的
workspace 由 CLI 规划并顺次执行完整迁移链；每一步使用其发布时固定的语义，整条链在
临时目录完成并通过最终不变量检查后，才原子替换为目标 workspace。任何一步失败都不
修改来源 workspace。

不要让 Agent 在现场把多个迁移脚本临时合并成一个“大迁移”。如果未来确实需要性能
优化，可以发布一个经过等价性测试的快照导入器，但它应是一项新的、版本化的正式能力，
而不是临时改写迁移事实。

从 V1 文件式 workspace 升级到 V2 SQLite 私有状态层，先只读预览：

```bash
codex-dream migrate \
  --source ~/Documents/codex-dream-workspace \
  --target ~/Documents/codex-dream-workspace-v2
```

确认 `migration_path` 为 `workspace-v1-to-v2-sqlite`、数量正确且 `can_apply` 为
`true` 后，再追加 `--apply`。V1 的三个 JSONL 会保存在目标的
`state/legacy-v1/` 中作为回退证据，运行状态由 `state/dream.sqlite3` 接管。来源目录
不会被修改；只有目标通过 SQLite 完整性、生命周期、计数和隐私验证后才能切换默认指针。

从更早的无版本 workspace 迁移时，仍可提供私有消歧文件：

```bash
codex-dream migrate \
  --source <legacy-workspace> \
  --target <new-workspace> \
  --resolutions <private-resolution.json>
```

预览中的 `can_apply` 为 `true` 后再应用：

```bash
codex-dream migrate \
  --source <legacy-workspace> \
  --target <new-workspace> \
  --resolutions <private-resolution.json> \
  --apply

codex-dream --workspace <new-workspace> verify
```

目标必须尚不存在；含真实路径和人工消歧内容的迁移记录写入被 Git 忽略的 `state/`。
脱敏的 schema 迁移历史写入 `knowledge/migration-history.jsonl`。详细协议见
[`docs/schema-migrations.md`](docs/schema-migrations.md)。

如果你的 Codex 数据不在默认位置，编辑 `dream.toml`：

```toml
[source]
codex_home = "~/.codex"
```

## 第一次做梦：必须先预览

第一次初始化分两步。先运行只读预览：

```bash
codex-dream \
  --since-days 30 \
  sync --dry-run
该命令只输出 session、sub-agent、任务树和待审数量，不创建 ledger，也不打印 session
原文。确认数量和路径范围合理后，再建立 30 天基线：

```bash
codex-dream \
  --since-days 30 \
  sync
```

然后只深度审阅最近 7 天；其余基线按周回填，避免一次把全部历史塞进上下文：

```bash
codex-dream \
  --since-days 7 \
  pending

codex-dream-review
```

## 追踪每一次梦境

Schema V2 把一次做梦变成正式的 `DREAM-*` 周期。确定本次范围后开始记录：

在读取 Session 之前，Codex 会先询问用户近期哪个项目、哪个环节做得好或不好，以及实际
体感和原本预期。这个回答是本轮优先调查的假设，不是预设结论；如果没有特别关注，也要
明确记录用户选择了默认复盘。`run-start` 会拒绝没有 `user_anchor` 的新周期。

```bash
codex-dream run-start \
  --title "最近 7 天增量复盘" \
  --scope '{"days":7,"projects":["backlog-gate"],"user_anchor":{"status":"provided","captured_from":"user_response","project":"backlog-gate","stage":"执行与收口","polarity":"negative","felt_result":"过程绕路且效果不符合预期","expected_result":"更直接地完成可靠闭环"}}'
```

没有特别关注时使用
`"user_anchor":{"status":"none","captured_from":"user_response","reason":"用户明确选择默认复盘"}`。
这只表示用户已经回答并选择默认范围，不能用来跳过启动提问。

语义审阅结束后关联实际处理的脱敏 `TASK-*`，并在报告通过隐私检查后完成周期：

```bash
codex-dream run-link DREAM-0003 TASK-0101 TASK-0102
codex-dream run-complete DREAM-0003 \
  --report reports/weekly/2026-07-16-incremental-dream.md \
  --summary '{"reviewed":2,"new_candidates":1,"user_anchor_result":{"status":"conflicting","supporting_task_refs":["TASK-0101"],"counterevidence_task_refs":["TASK-0102"],"evidence_gap":"缺少下一轮真实任务验证"}}'
```

历史 `reports/weekly/*.md` 在 V1→V2 迁移时会恢复为 `imported_report` 梦境记录；不会
为缺失的历史范围或任务关系编造事实。

## 本地 Dream Console

启动 Console：

```bash
codex-dream-console
```

`develop` 的 0.4.0 线提供经过端到端验收的 Console Flow Board。默认打开
`http://127.0.0.1:8765`。Console 是 Codex 的轻量复盘伴侣，提供首页注意力窗口、推进泳道、
WIP/老化/收尾建议、梦境时间线、改进追踪和知识库。它不调用模型、不做语义判断，也不修改目标项目。
首页最多展示 5 项，但完整候选池仍保留在“改进追踪”中；排序同时考虑近期触发和长期
累积负担。

推进看板按 Dream、Candidate、Adoption、Validation 的现有事实源去重，每列显示 WIP、当前
Workspace 上限与最老年龄。用户可以按项目、范围和健康度筛选。WIP 策略保存在 Workspace
本地；超限进入试用不会被静默禁止，但必须留下覆盖理由。Validation 达标或到期后进入“待收尾”，
用户逐条复核成功标准，再选择继续、调整合同、确认固化或结束。所有写入都需要页面启动时生成的
本地 token、人工理由和 `ACT-*` 审计记录。

Dream 运行失败时可保留历史并恢复：

```bash
codex-dream run-fail DREAM-0001 --error "依赖暂时不可用"
codex-dream run-resume DREAM-0001 --reason "依赖已经恢复"
```

用户可暂缓、拒绝候选，或在确认作用范围、预期固化载体、观察期限和成功标准后制定试用
计划。计划确认后只会进入 `等待 Codex 接续`，不会被伪装成已经开始实验。页面会明确提示
用户回到 Codex，并提供接续指令：

```text
继续处理我刚才在 Dream Console 中确认的事项。
```

Codex 侧通过以下命令读取、领取和回写交接：

```bash
codex-dream handoff-list --status handoff_pending
codex-dream handoff-claim ACT-000001
codex-dream handoff-complete ACT-000001 \
  --result '{"outcome":"trial_started","adoption_id":"ADP-0001","validation_id":"VAL-0001"}'
```

服务拒绝绑定非回环地址；接口不会把原始消息、完整项目路径或 Session UUID 返回浏览器。
所有人工操作都必须填写原因，正式决定通过知识领域校验写入 `timeline.jsonl`，并在 SQLite
留下 `ACT-*` 审计记录。

Windows PowerShell 同样运行 `codex-dream-console`；若用户脚本目录尚未进入 `PATH`，可用
`py -m codex_dream.console`。

## 增量游标怎样工作

`pending` 为每个 rollout 输出以下模式：

- `new`：从未审阅，从第 1 行开始；
- `append`：游标仍匹配，只读取少量重叠语境和新增事件；
- `reconcile`：文件缩短、游标事件消失或指纹不匹配，必须重新审阅；
- 没有变化且指纹匹配：不进入待审列表。

每个 rollout 独立保存游标，但 parent 与 sub-agent 共享同一个 `review_unit_id`。聚合时
一个任务树只能算一个独立案例，不能把多个 sub-agent 错算成多次重复模式。

## 完成语义审阅后再 Checkpoint

先把脱敏观察或知识写入 workspace，并运行：

```bash
codex-dream privacy-audit
```

只有报告或知识项已经持久化且隐私检查通过，才能为实际审阅过的 rollout 推进游标：

```bash
codex-dream \
  checkpoint SESSION_ID \
  --through-line 180 \
  --context-capsule "TASK-0001 已完成脱敏审阅；结论见 OBS-0001。" \
  --observation OBS-0001
```

`context_capsule` 保存在被 Git 忽略的 `state/` 中，可以包含下一次增量续读需要的私有
语境，但仍不应包含密钥。安静 24 小时或行数足够只表示“适合审阅”，不等于已完成
语义审阅，不能据此自动 checkpoint。

## 知识与候选生命周期

Codex Dream 把四种状态分开：

```text
knowledge: observed → emerging → established → retired
candidate: proposed → accepted | rejected | superseded
adoption:  planned → applied | rolled_back
validation: pending → validating → proven | failed | inconclusive
console handoff: handoff_pending → claimed → completed | failed
```

Console handoff 是独立的操作状态：`completed` 只表示 Codex 已经处理这次交接，不表示改进
已经验证成功。只有用户确认的载体已经应用，并且验证状态为 `proven`，页面才显示“已完成”。

- 首次出现的行为只是 `observed`；
- 至少两个独立案例后才考虑 `emerging`；
- 通常至少三个案例且适用边界清楚后才考虑 `established`；
- 至少跨两个项目出现，才考虑跨项目或全局能力；
- 高影响单次事件可以成为 `once` 候选，但不能描述为重复规律。

创建知识项：

```bash
codex-dream-knowledge \
  create \
  --title "复杂任务先读取项目规则" \
  --kind effective_practice \
  --scope cross_project \
  --summary "读取项目规则减少了可避免的返工。"
```

通过 JSON 文件追加生命周期事件：

```bash
codex-dream-knowledge \
  event KD-0001 \
  --type observation_added \
  --data-file observation.json
```

候选结构模板位于 `templates/candidate.json`，验证合同 schema 位于
`schemas/validation-contract.schema.json`。只有 `accepted` 候选才能记录采用，实际采用
后必须建立验证合同。

查看知识视图和所有活跃验证：

```bash
codex-dream-knowledge show KD-0001
codex-dream-knowledge active-validations
```

## 隐私模型

默认把所有 session 当作敏感数据。

永远只留在 `state/`：

- 真实 session UUID；
- rollout 和项目绝对路径；
- 原始消息与未脱敏摘录；
- 私有 capsule；
- `TASK-*` 与真实 session 的映射。

可以选择进入 Git 的内容：

- 使用 `TASK-*` 作为证据引用的脱敏知识；
- 不包含原始对话、绝对路径、UUID 和秘密的报告；
- schema、模板和用户自行确认的生命周期事实。

`privacy-audit` 是发布前检查器，不是自动脱敏器。发现问题时必须回到对应文件人工判断
和删除；不要为了通过检查而盲目忽略规则。

## 默认运行节奏

- session 静默 24 小时后可视为相对完整的审阅对象；
- 每周进行一次增量做梦；
- 观察证据至少保留 28 天；
- 每四周聚合一次低频但持续存在的模式；
- 第一次运行只建立基线，不宣称改善或恶化；
- 没有适用任务不等于验证失败，用户沉默也不等于正面反馈。

这些默认值都可以在 workspace 的 `dream.toml` 中修改。

## 项目结构

```text
codex_dream/                 Python 确定性内核
├── cli.py                   workspace、sync、pending、checkpoint、privacy
├── ledger.py                session 身份、任务树、增量游标与原子写入
├── review.py                私有任务树审阅卡
├── knowledge.py             稳定知识 ID 与独立生命周期
├── privacy.py               可分享输出的隐私检查
├── schema.py                workspace / knowledge schema 兼容性门
├── migrations/              相邻版本迁移注册表与迁移实现
├── database.py              V2 SQLite 私有运行状态、梦境与操作审计
├── console.py               本地 HTTP API、写入门和隐私收敛
├── console_static/          无外部依赖的 Console 页面
└── workspace.py             workspace 初始化、配置与 doctor
skills/codex-dream/          可选语义控制面 Skill
schemas/                     知识项、生命周期事件、候选和验证合同
templates/                   候选与报告模板
tests/                       只使用合成 rollout 的测试
```

本仓库自身永远不应包含任何用户已经做过的梦。它只保存引擎、协议、schema、模板和
合成测试。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/codex-dream
```

还应至少验证：

1. 在临时目录执行 `codex-dream init`；
2. 用合成 Codex home 执行 dry-run、sync、pending 和 append；
3. 确认未审阅内容不会被自动 checkpoint；
4. 确认 `privacy-audit` 会拦截 UUID、绝对路径和常见密钥格式；
5. 确认项目 Git 中不存在真实 `knowledge/items`、报告和 state。

## 当前边界

- 当前只解析 Codex 本机 rollout JSONL，不支持其他 Agent 产品；
- session 格式发生不兼容变化时需要更新适配器；
- 语义结论由 Codex 按 Skill 协议生成，CLI 不假装能用关键词替代判断；
- `privacy-audit` 只能发现一组高风险模式，不能证明不存在所有隐私信息；
- 自动定时运行、外部上传和自动采用候选均不属于默认能力。

## License

[MIT](LICENSE)
