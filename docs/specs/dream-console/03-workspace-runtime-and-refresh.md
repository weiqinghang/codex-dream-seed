# Workspace、运行时与刷新可靠性 Spec

状态：`active`
适用范围：Console 与 Agent 共用 Workspace 的运行可靠性

## 目标

保证 Console、CLI 和 Dream Skill 读取并写入同一个有效 Workspace；外部写回可以可靠反映到页面；服务和数据异常存在可理解的恢复路径。

## Workspace 单一事实源

- 解析顺序继续遵循：显式 `--workspace` → 环境配置 → 当前初始化 Workspace →机器默认指针 → fail closed。
- Console 页面展示安全短 fingerprint 和解析来源，不展示绝对路径。
- Console 接续前必须核对与 Agent 使用的是同一 fingerprint。
- 仅包含 `dream.toml`、但缺少必需结构或 schema 不兼容的目录不得被静默初始化为有效 Workspace。
- 正常流程不得使用 `--ledger`、knowledge `--root` 等参数形成平行事实源；保留时必须标记为 legacy/debug escape hatch 并加防误用检查。

## 一致性与并发

- SQLite 与 knowledge JSON 的关键跨文件写入必须有跨进程锁、可恢复事务或等价的一致性保护。
- 同一 action 的重复写入必须幂等或明确拒绝。
- 进程崩溃后能够识别未完成事务，不允许数据库显示完成而 knowledge 生命周期缺少对应结果。
- 锁超时、冲突和恢复结果必须可诊断，不能无限等待。
- 测试只使用合成 Workspace。

## 页面刷新

- 提供手动刷新按钮和“最后更新时间”。
- 浏览器重新获得焦点或恢复可见时安全刷新。
- 可选择低频轮询，但不得制造重复写入、闪烁或高资源占用。
- API 部分失败时保留成功加载的数据，并为失败区块提供重试。
- 区分“写操作失败”和“写入成功但刷新失败”。
- 页面显示加载中、已更新、数据可能陈旧和刷新失败状态。
- 外部 claim/complete/fail/retry 后，Banner、Board 和详情能够显示一致状态。

## Console 服务管理

提供与现有 CLI 风格一致的：

- `console start`
- `console status`
- `console stop`

或等价公开能力，并处理：重复启动、端口占用、陈旧 PID、服务异常退出和停止不存在的服务。默认监听本机回环地址。

## 报告与指标

- Dream 报告可在 Console 内安全只读打开。
- 服务端只能解析 Workspace 内已登记的报告，禁止任意路径读取和目录穿越。
- 有可靠 Token/耗时来源时显示数值与口径；没有时显示“未记录/不可用”。
- 缓存 Token、原始 Token 和计费成本不得混为同一指标。

## 验收

- Workspace 不匹配、schema 不兼容、并发写入和崩溃恢复均有测试。
- Agent 外部写回后页面可恢复地刷新，不要求用户强制整页重载。
- 服务管理命令在重复启动、端口冲突和陈旧 PID 下行为确定。
- 报告读取不能越过 Workspace 边界。
