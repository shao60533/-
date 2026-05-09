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
| 2026-05-10 | v1.3 — 实装 | 按 v1.3 PRD/Design/TestCase 完成移动端 IA/UI 落地：MobileTabbar 收敛为「首页/分析/发现/纸面/更多」5 tab + More 重整；DashboardPage 合并持仓（默认 5/全部 N + 看分析/卖出/修正成本/移除 + 批量分析持仓产品缺口标注）；AnalysisDetail 严格 8 结构化 tabs（删 Quick Info / 顶部重复结论 / 结构化原文，新增记录与操作 + 原始报告 fallback）；ScreenerV3 删表单取消 + 结果页透明度审计块，14 大师评分 details 默认收起含共识摘要；PaperTradeDetail 删策略/日度内层 tabs + 日度按钮去重 + AI 决策结构化卡替代英文原文。Playwright 12 页面 × 4 视口（375/390/430/768）= 48 case 全过、0 横向溢出；npm run build 3.81s 通过。新增 `components/shared/HoldingDialogs.tsx` + `islands/dashboard/HoldingsSection.tsx` 两个共享组件，PortfolioPage 同步切到共享 dialog；不新增后端端点 / migration / task type。 | [mobile-ui-v1.3.md](mobile-ui-v1.3.md) | — |
| 2026-05-09 | v1.0 | 第三方快捷登录（Google + GitHub）：Authlib + OAuth 2.0/OIDC + PKCE + 邀请码门保留（多租户红线）；同邮箱已验证 provider（Google）首次登录自动合并到现有账户、未验证（GitHub primary verified=false）走二次确认；新增 `oauth_accounts` 表（不动 users schema，OAuth 用户用占位 password_hash）；6 新路由 `/auth/oauth/<p>/start`/`/callback`/`/api/auth/oauth/register`/`/linked`/`/<p>/unlink`/`/api/auth/providers`；access/refresh_token fernet 加密存（`OAUTH_ENCRYPT_KEY` env 启动时 fail-fast）；前端 login/register 加 OAuth 按钮 + Settings "登录方式" section（绑定/解绑，解绑前置检查至少保留一种登录方式）；Apple/微信 v1.1/v1.2 排期，邮箱密码登录路径永久保留作 fallback；~5h 实装 ~1240 LOC | [oauth-quick-signin.md](oauth-quick-signin.md) | — |

## 待跟进
- P2 需求（R-2.1 ~ R-2.8）尚未排期
- Q3（AkShare 海外可达性）已验证：海外节点常失败，系统已自动降级
- Q4（analysis_history schema 完整性）已在架构升级中解决
