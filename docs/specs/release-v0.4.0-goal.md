# Goal

## Objective

将 0.4.0 开发线完整发布为普通 Codex 用户可安装、可升级、可恢复的稳定版本；所有代码和
写回文件先完成，再合入 `develop`、推进 `product` 并创建同 commit 的 annotated `v0.4.0`。

## Source Of Truth

- 仓库 `AGENTS.md` 的 release、installation 与 bootstrap contract。
- `docs/specs/dream-console/01-05` 和 `docs/verification/dream-console-browser-journey.md`。
- `README.md`、`CHANGELOG.md`、`docs/design/*`、包元数据、CI 和 GitHub 实时分支/PR/tag。

## Scope

- 同步版本、稳定状态、安装渠道、支持矩阵、迁移、Console 能力与限制的所有文档和元数据。
- 验证合成环境中的全新安装、Skill、首次 30 天预览、V1→V2 升级、Console 服务和构建产物。
- 在 exact release head 通过本地检查及 macOS/Linux/Windows × Python 3.9–3.13 CI。

## Operating Rules

- 保护主 worktree 的用户修改；只在当前功能 worktree 完成发布准备。
- 不读取、迁移或提交真实 Session、原始消息、UUID 或私有 Workspace。
- 不以旧 head 的 CI 代替最终 release head；不先 tag 再补 README/CHANGELOG/设计文档。
- 常规失败自主诊断、修复、重跑，不静默缩减范围。

## Exit Conditions

代码和全部写回一致；普通用户新装与升级旅程通过；PR 合入 `develop`；最终远端矩阵成功；
`product`、`v0.4.0^{}` 与发布 commit 完全一致，且最终报告列明证据和真实限制。
