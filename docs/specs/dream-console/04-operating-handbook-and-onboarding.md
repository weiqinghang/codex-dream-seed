# Dream 操作手册与首次指引 Spec

状态：`active`
适用范围：Console、Dream Skill 与 README 的共同用户说明

## 目标

建立一份中文优先的 canonical Dream 操作手册，使 Console 和 Agent 对状态、动作、恢复方式与隐私边界保持同一解释，同时避免把整份说明塞进 `SKILL.md`。

## Canonical 工件

默认路径：

```text
docs/dream-operating-handbook.md
```

如果实现阶段发现已有更合适的 canonical 工件，可以复用，但必须保持单一事实源并说明迁移关系。

## 手册章节

1. Dream、Console、Codex Agent、Workspace 的分工。
2. 首页、梦境、推进看板、改进和知识库分别回答什么问题。
3. 待决策、试用落实、验证中、待收尾和完成的状态语义。
4. 暂缓、拒绝、试用、调整验证、重试和收尾动作的结果与可逆性。
5. Console→Codex handoff、唯一定位和新鲜度检查。
6. WIP、正向/负向证据、成功标准、进度和收尾条件。
7. failed handoff、页面陈旧、服务停止、API 失败和 Workspace 不一致的恢复方法。
8. UI 动作与 CLI/Agent 能力对照表。
9. 本地运行、隐私裁剪、人工决策门和禁止性声明。

## 三个阅读面

- Console：左侧导航底部、“仅在本机运行”附近提供长期可见的“使用指南”。
- Skill：只保留路由规则，按首次做梦、Console 接续、验证收尾和故障恢复读取对应章节。
- README：保留安装、架构和深度参考，只提供简短介绍与手册入口。

不得在三个阅读面分别维护状态定义。

## 首次指引

- 空 Workspace 首页显示三步卡片：开始做梦 → 查看和决定 → 回到 Codex 接续。
- 每个页面空状态提供具体 CTA，并解释为什么当前为空。
- 帮助入口随时可返回，不强制全屏 onboarding。
- 关键按钮附近提供简短、面向结果的说明；深度内容进入手册章节。

## 防漂移

- 为 canonical 手册章节、Console 使用的文案/结构和 Skill 引用建立 checksum、生成验证或契约测试。
- 新增或修改状态、动作、CLI 能力时，测试必须暴露未同步的手册/Skill/UI。
- 手册不得复制内部实现细节或真实私有数据。

## 验收

- 新用户仅通过 Console 帮助即可解释完整旅程和下一步。
- Agent 能按当前场景读取必要章节，不默认加载整份手册。
- README、Skill 和 Console 不存在冲突的状态与恢复说明。
- 文案与引用漂移会导致测试失败。
