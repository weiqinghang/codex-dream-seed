## Related requirement

Related to #

> 使用非关闭型 `Related to #N`。在默认分支验证、Writeback 和 `workflow::done` 前，不要使用 `Fixes` 或 `Closes`。

## Acceptance coverage

- [ ] 已把 Issue 中每个 Must Acceptance 映射到实现和证据

## Verification

- [ ] 已记录实际运行的测试、检查与人工验收结果
- [ ] 已运行 `git diff --check`
- [ ] 若影响 Dream 产品，已完成仓库规定的完整测试与 bundled Skill 校验

## Privacy / data boundary

- [ ] 只使用合成或已脱敏数据
- [ ] 不含真实 Session、梦境、知识、UUID、绝对用户路径、密钥或私有 Workspace 原文

## Compatibility / release impact

- [ ] 已说明 package、Schema、安装渠道、OS/Python 和稳定版本影响
- [ ] repo-ops-only 变更未修改 package version 或创建稳定 tag

## Writeback

- [ ] 合并后会在 Issue 使用 `requirements-writeback:v1` 结构化评论回写 PR、merge commit、Acceptance 证据、验证和残余风险
- [ ] 默认分支回读完成后，才会设置 `workflow::done` 并人工关闭 Issue
