# Codex Dream Seed

Codex Dream Seed 是一套本地优先、跨项目、增量运行的 Codex 协作复盘框架。

它读取本机可访问的 Codex session，寻找三类值得长期积累的知识：

1. 已被证据证明有效、值得保留的实践；
2. 多次出现、可能抽象成 Skill、脚本、模板、检查器或规则的重复工作；
3. 当时已有信息下本可以更直接完成的绕路。

它不是一个“自动纠错机器人”。第一阶段只生成带证据的候选，不会自行修改你的
项目、`AGENTS.md`、Skills 或自动化。候选的接受、拒绝、采用和最终验证始终需要
可追溯的人工决定。

> 当前版本为 `0.1.0`，适合本地试用和框架共建。默认只支持 Codex 本机 rollout
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

## 安装项目内核

克隆后建议使用虚拟环境或 `pipx`。开发模式示例：

```bash
git clone https://github.com/weiqinghang/codex-dream-seed.git
cd codex-dream-seed
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

安装后会提供三个命令：

```text
codex-dream             workspace、session ledger、增量游标和隐私检查
codex-dream-review      生成私有任务树审阅卡
codex-dream-knowledge   管理知识、候选、采用和验证生命周期
```

## 安装可选 Skill

将项目中的 `skills/codex-dream` 安装到你的 Codex Skills 目录。最直接的本地方式是：

```bash
cp -R skills/codex-dream ~/.codex/skills/codex-dream
```

Skill 只包含语义工作流和参考协议，不保存任何用户数据。安装后可以对 Codex 说：

```text
使用 $codex-dream 开始做梦。先只读预览最近 30 天，再等我确认是否初始化。
```

也可以不安装 Skill，直接按本 README 的命令使用 CLI；但完整的语义审阅仍需要 Agent
遵循 `skills/codex-dream/references/` 中的协议。

## 创建个人 Workspace

选择一个不会与本项目源码混在一起的目录：

```bash
codex-dream init ~/codex-dream-workspace
```

生成结构：

```text
~/codex-dream-workspace/
├── dream.toml                范围、节奏和 Codex 数据位置
├── .gitignore                强制忽略私有 state
├── state/                    私有：UUID、路径、原文摘录、capsule、游标
├── knowledge/
│   ├── index.json            稳定 ID 分配与索引
│   └── items/                脱敏知识及完整生命周期
└── reports/
    ├── weekly/               周期聚合报告
    └── reviews/              必要的专项审阅
```

先检查环境：

```bash
codex-dream --workspace ~/codex-dream-workspace doctor
```

如果你的 Codex 数据不在默认位置，编辑 `dream.toml`：

```toml
[source]
codex_home = "~/.codex"
```

## 第一次做梦：必须先预览

第一次初始化分两步。先运行只读预览：

```bash
codex-dream \
  --workspace ~/codex-dream-workspace \
  --since-days 30 \
  sync --dry-run
```

该命令只输出 session、sub-agent、任务树和待审数量，不创建 ledger，也不打印 session
原文。确认数量和路径范围合理后，再建立 30 天基线：

```bash
codex-dream \
  --workspace ~/codex-dream-workspace \
  --since-days 30 \
  sync
```

然后只深度审阅最近 7 天；其余基线按周回填，避免一次把全部历史塞进上下文：

```bash
codex-dream \
  --workspace ~/codex-dream-workspace \
  --since-days 7 \
  pending

codex-dream-review \
  --workspace ~/codex-dream-workspace
```

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
codex-dream \
  --workspace ~/codex-dream-workspace \
  privacy-audit
```

只有报告或知识项已经持久化且隐私检查通过，才能为实际审阅过的 rollout 推进游标：

```bash
codex-dream \
  --workspace ~/codex-dream-workspace \
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
```

- 首次出现的行为只是 `observed`；
- 至少两个独立案例后才考虑 `emerging`；
- 通常至少三个案例且适用边界清楚后才考虑 `established`；
- 至少跨两个项目出现，才考虑跨项目或全局能力；
- 高影响单次事件可以成为 `once` 候选，但不能描述为重复规律。

创建知识项：

```bash
codex-dream-knowledge \
  --workspace ~/codex-dream-workspace \
  create \
  --title "复杂任务先读取项目规则" \
  --kind effective_practice \
  --scope cross_project \
  --summary "读取项目规则减少了可避免的返工。"
```

通过 JSON 文件追加生命周期事件：

```bash
codex-dream-knowledge \
  --workspace ~/codex-dream-workspace \
  event KD-0001 \
  --type observation_added \
  --data-file observation.json
```

候选结构模板位于 `templates/candidate.json`，验证合同 schema 位于
`schemas/validation-contract.schema.json`。只有 `accepted` 候选才能记录采用，实际采用
后必须建立验证合同。

查看知识视图和所有活跃验证：

```bash
codex-dream-knowledge --workspace ~/codex-dream-workspace show KD-0001
codex-dream-knowledge --workspace ~/codex-dream-workspace active-validations
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
└── workspace.py             workspace 初始化、配置与 doctor
skills/codex-dream/          可选语义控制面 Skill
schemas/                     候选和验证合同
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
