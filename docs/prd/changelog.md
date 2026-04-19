# PRD 变更记录

| 日期 | 版本 | 变更内容 | 关联文件 | 关联 Commit |
|------|------|---------|---------|-------------|
| 2026-04-12 | v2.0 | 初版 PRD，定义 9 大页面功能、P0/P1/P2 需求矩阵、后端 API 规格、成功指标 | [v2.0-stock-trading-system.md](v2.0-stock-trading-system.md) | — |
| 2026-04-18 | v1.0 | 全局模型切换（Qwen ↔ Gemini）：推理层一键切换 + Nav 下拉 UI + env 锁定态 + 目标 key 校验 | [model-switch.md](model-switch.md) | — |
| 2026-04-19 | v1.0 | 多租户：邀请码注册 + 邮箱密码登录 + 私有（持仓/预警/纸面）vs 共享（分析/选股/回测）数据分区 + admin 首启自动迁移 + 用户级 model-switch + 任务中心我的/全部双 tab | [multi-tenant.md](multi-tenant.md) | — |

## 待跟进
- P2 需求（R-2.1 ~ R-2.8）尚未排期
- Q3（AkShare 海外可达性）已验证：海外节点常失败，系统已自动降级
- Q4（analysis_history schema 完整性）已在架构升级中解决
