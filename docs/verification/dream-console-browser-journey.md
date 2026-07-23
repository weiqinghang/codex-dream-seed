# Dream Console 真实浏览器验收记录

验证时间：2026-07-23 01:52–02:11（Asia/Shanghai）
浏览器：Playwright Chromium，桌面视口与 390×844 窄屏
事实源：全合成 Workspace；未读取真实 Session、原始消息或个人 Workspace 状态。

## P0 对照

| P0 | 结果 | 浏览器与运行证据 |
| --- | --- | --- |
| 1. 首次启动与用户旅程 | 通过 | 空 Workspace 展示“开始做梦 → 查看和决定 → 回到 Codex 接续”三步卡片；主要 CTA 在桌面和窄屏可见。 |
| 2. 稳定 handoff 与恢复 | 通过 | UI 生成唯一 `ACT-000003`、fingerprint、attempt 指令；独立 CLI Context 后完成 claim → fail → UI retry → attempt 2 → claim → complete。 |
| 3. Workspace、刷新与服务 | 通过 | 指纹与解析来源可见；手动、focus/visibility 刷新成立；服务停止保留旧数据并提示陈旧，重启后恢复；单区块异常保留成功 API 数据。 |
| 4. 指南、验证与收尾 | 通过 | 使用指南可随时访问；正向/负向/未定证据分色；成功、失败、证据不足继续观察、调整合同均实际提交并回写正确泳道。 |
| 5. 验证与退出 | 通过 | 真实浏览器、自动化、Skill、JS、privacy、schema/CLI/API/锁/服务/报告合同均执行；最终服务保持运行。 |

## 旅程明细

1. 空 Workspace：首页仅显示首次指引，复制“开始做梦” CTA 可用。
2. 梦境：`DREAM-0003 → 0002 → 0001` 降序；左侧序号为真实 Dream ordinal；无数据时显示“未记录”；可靠 Token 显示输入、缓存、输出口径。
3. 安全报告：仅登记的 `DREAM-0002` 报告可在 Console 对话框中打开。
4. 看板：仅五列；价值、提出时间、Dream 提及排序存在；验证列可按进度或反馈数排序；WIP 与 Advisor 可见。
5. 决策：分别提交暂缓、拒绝和试用计划。真实浏览器发现并修复隐藏 required 控件阻断非试用提交的问题。
6. 接续：新上下文不依赖聊天历史，通过 fingerprint、`ACT-*` 与 attempt fail closed 地定位事项。
7. 恢复：failed handoff 在 UI 保存 retry reason/source/request ID；原错误、claim、attempt 和 retry 历史保留。
8. 验证：详情同时显示成功标准、失败信号、正向、负向、未定证据、验收阻碍和下一步。
9. 收尾：确认固化进入完成；结束为失败进入完成；证据不足继续观察返回验证中；调整合同保留旧版本并等待新证据。
10. 异常：服务停止显示“刷新失败 · 数据可能陈旧”；服务恢复后刷新成功；破坏一个合成 knowledge 区块时，页面提示失败区块并保留 runs/handoffs 等成功数据。

## 截图

- `output/playwright/01-empty-first-run.png`
- `output/playwright/02-runs-safe-report.png`
- `output/playwright/03-board-five-states.png`
- `output/playwright/04-decision-handoff-act.png`
- `output/playwright/05-failed-retry-attempt-2.png`
- `output/playwright/06-narrow-home.png`
- `output/playwright/07-help-narrow.png`
- `output/playwright/08-service-stopped-stale-data.png`
- `output/playwright/09-partial-api-failure.png`

## 浏览器发现并修复

- 隐藏的试用载体 `required` 会阻断暂缓/拒绝：移除浏览器级隐藏约束，保留 JS 与服务端校验。
- 人工 `failed` / `inconclusive` 仍停在待收尾：改为进入可追溯完成终态。
- 选择“继续观察”后立即再次 closeout：在新证据到来前尊重最近一次 continue/adjust，之后重新评估。
- 空页面首次请求 favicon 产生噪音：本地服务返回 204。

## 真实限制

- 浏览器旅程使用合成 Workspace，不证明任何个人 Workspace 数据质量。
- Console 仍不执行语义工作；handoff complete 只表示 Codex 已处理交接，落实和验证记录仍需继续写回。
- 页面使用 Markdown 纯文本方式展示已登记报告，不执行报告中的 HTML 或脚本。
