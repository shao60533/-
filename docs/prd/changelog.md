# PRD 变更记录

| 日期 | 版本 | 变更内容 | 关联文件 | 关联 Commit |
|------|------|---------|---------|-------------|
| 2026-04-12 | v2.0 | 初版 PRD，定义 9 大页面功能、P0/P1/P2 需求矩阵、后端 API 规格、成功指标 | [v2.0-stock-trading-system.md](v2.0-stock-trading-system.md) | — |
| 2026-04-18 | v1.0 | 全局模型切换（Qwen ↔ Gemini）：推理层一键切换 + Nav 下拉 UI + env 锁定态 + 目标 key 校验 | [model-switch.md](model-switch.md) | — |
| 2026-04-19 | v1.0 | 多租户：邀请码注册 + 邮箱密码登录 + 私有（持仓/预警/纸面）vs 共享（分析/选股/回测）数据分区 + admin 首启自动迁移 + 用户级 model-switch + 任务中心我的/全部双 tab | [multi-tenant.md](multi-tenant.md) | — |
| 2026-04-19 | v1.0 | 智能选股 V3：14 大师 agent 深度评估（6-10 子分析/位 + LLM 结构化推理）替换 v2 硬阈值 + 用户预选配置面板（大师/深度模式/候选数）+ 成本预估 + Round-table 辩论 + 流式回显 + 可中断恢复 + 缓存 + 经典模式兼容保留 | [screener-v3.md](screener-v3.md) | — |
| 2026-04-21 | v1.0 | UI React Island：Flask 外壳不动 + 4 高价值页（screener-v3 / tasks / paper-trade detail / dashboard）迁 React + Vite + Tailwind v4 + shadcn 风格组件，7 简单页保留 Jinja；POC 已验证（/tmp/stock-ui-demo/） | [ui-react-island.md](ui-react-island.md) | — |
| 2026-04-21 | v2.0 | UI React Island 完整迁移：剩余 11 页全部迁 React（Portfolio / History / Alerts / Reports / Backtest / Paper list / Analysis 列表+详情 / Settings / Login / Register / Reset）+ Phase 18 废弃旧 index.html / app.js / Bootstrap，总工期 ~75h | [ui-react-island.md](ui-react-island.md) | — |
| 2026-05-09 | v1.3 | 移动端信息架构与 UI 实装：严格按高保真 demo，不改产品功能/后端/架构；首页+持仓合并、纸面交易升一级、Analysis 8 结构化 tabs、Screener 大师评分默认折叠、Paper detail 去冗余、More 减噪 + 分阶段任务拆解 | [mobile-ui-v1.3.md](mobile-ui-v1.3.md) | — |

## 待跟进
- P2 需求（R-2.1 ~ R-2.8）尚未排期
- Q3（AkShare 海外可达性）已验证：海外节点常失败，系统已自动降级
- Q4（analysis_history schema 完整性）已在架构升级中解决
