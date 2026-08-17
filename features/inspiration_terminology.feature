# language: zh-CN
功能: 将 CAN 生命周期实体称为灵感
  Dream 应该用贴近复盘语境的名称向用户展示 CAN 实体，
  同时保持已发布的数据接口兼容。

  场景: Console 将待决定的 CAN 实体展示为灵感
    假如存在一个等待人工决定的 CAN 实体
    当用户查看 Console 和改进追踪页面
    那么用户可见的生命周期名称应为灵感
    而且页面不应继续把这个生命周期称为候选

  场景: Dream 指南统一解释灵感及其兼容边界
    当维护者阅读 Dream 的 Skill README 和报告模板
    那么这些指南应把 CAN 实体称为灵感
    而且 Skill 应说明 candidate 字段仍是兼容接口

  场景: 既有 candidate 数据接口保持兼容
    假如调用方仍使用 candidate_proposed 和 candidate_id
    当知识生命周期记录并渲染这个实体
    那么生成的稳定标识仍应使用 CAN 前缀
    而且内部 candidate 字段和值应保持可读
