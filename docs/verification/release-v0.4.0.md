# v0.4.0 稳定发布验收记录

验证日期：2026-07-23（Asia/Shanghai）  
事实源：临时目录中的全合成 Codex Home、V1/V2 Workspace 与空白首次安装；未读取、
迁移或提交真实 Session、原始消息或个人 Workspace 状态。

## 发布结论

`v0.4.0` 的发布候选已通过本机功能、构建、全新安装和相邻版本升级验收。只有包含本记录
的最终提交在 GitHub Actions 完成 macOS、Linux、Windows × Python 3.9–3.13 的 15 项
矩阵后，才允许合入 `develop`、推进 `product` 并创建 annotated `v0.4.0` tag。

## 验收对照

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| Python 本机回归 | 通过 | Python 3.11、3.12、3.13 各运行 101 项测试，全部通过。 |
| 声明支持矩阵 | 发布门禁 | GitHub Actions 对三个系统和 Python 3.9–3.13 执行测试、bootstrap dry-run 与 apply。 |
| 包构建 | 通过 | 离线构建 `0.4.0` sdist 与 `py3-none-any` wheel；wheel 包含 Console 静态资源和 V0→V1、V1→V2 迁移。 |
| 全新安装 | 通过 | 从最终 wheel 安装到空虚拟环境；bootstrap plan 不写入，apply 后 doctor/verify 均为 `ok`。 |
| 配置解析 | 通过 | 自定义 `CODEX_DREAM_HOME` 下 bootstrap 与运行时共享同一默认指针，无平行事实源。 |
| Console 服务 | 通过 | 安装产物在回环地址启动、status、HTTP 200、stop 全部成功；空 Workspace 指纹保持一致。 |
| v0.3.0 → v0.4.0 | 通过 | 从稳定 tag 初始化 V1；新 bootstrap fail-closed 提示迁移；dry-run、apply、verify、set-default、doctor 依次成功。 |
| 数据保全 | 通过 | V1→V2 合成记录测试保留 ledger、review card、task ref、run 计数；来源 Workspace 不原地修改。 |
| Skill 与静态检查 | 通过 | bundled Skill validator、Python compile、Console JavaScript syntax 与 `git diff --check` 通过。 |
| 隐私 | 通过 | 临时 V2 Workspace privacy audit 为 `clean`；仓库发布差异不含真实 Session、UUID、私有 Workspace 或本机绝对路径。 |

## 构建指纹

- wheel SHA-256：`56cead08df684dfd2ffeb98e9216498fe304783479b1259e31c0c99e1d483333`
- sdist SHA-256：`ee06191bb8124ef04115e2d61280b68d61134c900a14fa113d91bd704b1b427d`

这些指纹用于本次候选的本地可重复性检查，不代替最终 Git tag 和 GitHub Actions 结果。

## 普通用户边界

- 稳定安装源是默认分支 `product` 或 immutable `v0.4.0`，不是 `develop`。
- 首次 bootstrap 只展示 30 天 inventory，不建立 ledger；需要用户确认后才处理 Session。
- V1 升级必须迁移到新目标并验证后切换默认指针，旧 Workspace 保留为回退来源。
- Console 只监听本机回环地址，不做模型语义判断，也不自动接受、拒绝、采用或验证候选。
- 支持的是本机 Codex rollout JSONL；浏览器验收使用合成 Workspace，不代表任何个人数据质量。
