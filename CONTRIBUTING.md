# Contributing to Codex Dream Seed

本仓库使用 GitHub Issue 管理需要跨任务追踪的产品需求、缺陷与 repo-operations 工作。
GitHub 是状态唯一事实源；不要在本地 Todo、聊天或 PR 描述中维护第二套需求状态。

## 提交需求或缺陷

1. 使用 GitHub 的 Product requirement 或 Bug report 表单。
2. 新卡默认按 `sizing::standard` 进入 Backlog；维护者在首次分诊时确认 Sizing、成熟度和
   workflow。
3. Ready 前补齐 Scope、Acceptance、Verification、Privacy、Compatibility；Standard 和
   Heavy 还必须有 Spec/Plan。
4. PR 只用 `Related to #N` 关联 Issue，不自动关闭。
5. 合并后把证据写回 Issue，默认分支读回通过后再标为 Done 并人工关闭。

完整的标签、状态机、NFR、审计与例外规则见
[Requirements governance](docs/project/requirements-governance.md)。

## 隐私边界

禁止向 Issue、PR、评论或仓库提交真实 Session、梦境、知识、UUID、绝对用户路径、原始
消息、密钥、cookies、tokens 或私有 Workspace 内容。复现与测试只使用合成数据；审计器的
命中是需要人工复核的高风险提示，不是自动脱敏结果。

## 开发与验证

产品实现仍遵循 [AGENTS.md](AGENTS.md) 的分支、安装、测试和发布契约。治理审计器属于
仓库运营工具，不是 `codex_dream` CLI、bundled Skill 或 wheel 的一部分：

```bash
python3 scripts/audit_requirements_governance.py --repo weiqinghang/codex-dream-seed
python3 -m unittest tests.console_runtime_tests -v
python3 -m unittest discover -s tests -p "test_*.py" -v
```
