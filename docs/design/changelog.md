# 设计方案变更记录

| 日期 | 文档 | 版本 | 变更内容 | 关联 Commit |
|------|------|------|---------|-------------|
| 2026-04-21 | [ui-react-island.md](ui-react-island.md) | v1.0 | UI React Island 迁移方案：新建 `web/frontend/`（Vite 8 + React 19 + TS + Tailwind v4）+ `vite_helpers.py` 读 manifest + `layout.html` 共享 Jinja 壳 + 4 个 island entry（screener-v3 / tasks / paper-trade / dashboard）+ 共享 `lib/api.ts`（CSRF/fetch）+ `lib/socket.ts`（SocketIO + catch-up）+ `components/ui/` 14 个 shadcn 风格组件 + `components/shared/ProgressStream` 复用 unified-progress envelope + manualChunks（react-vendor/radix/ui 三共享 chunk）+ Railway Nixpacks 加 nodejs-18 + 7 简单页保留 Jinja + 7 Phase 实施计划（~28h）| — |
| 2026-04-21 | [ui-react-island.md](ui-react-island.md) | v2.0 | 完整迁移：新增剩余 11 页页面规格（Portfolio / History / Alerts / Reports / Backtest / Paper list / Analysis 列表+详情 / Settings / Login / Register / Reset）+ 新增共享组件（`<AppShell>`、`<DataTable>`（@tanstack/react-table）、`<Form>`（react-hook-form+zod）、`<EChartsPanel>`、`<AuthCard>`、`<SettingsTabs>`、`<FilterBar>`）+ Phase 8-19 共 ~47h 实施计划 + Phase 18 废弃旧 index.html / app.js / Bootstrap（减 5000+ LOC）+ v2.0 新依赖清单（@tanstack/react-table / react-hook-form / zod / echarts / react-markdown）| — |
| 2026-04-20 | [unified-progress.md](unified-progress.md) | v1.0 | 统一实时进度系统（后端 + 前端）：新建 `task_events` 表 + `emit_event()` 统一入口替代散落的 `socketio.emit` + Per-user SocketIO room 隔离 + `GET /api/tasks/events?since=<seq>` 断线续传 + `GET /api/tasks/running` reconnect 同步 + 前端 `ProgressStream` 组件（3 布局 compact/detail/inline-badge × 5 态 connecting/streaming/stalled/disconnected/done）+ 5 页面统一挂载（任务中心/分析/screener-v3/batch/backtest）+ 断线 banner UX + 全局连接指示灯 + 7 天 events 保留 + 11 种 task 事件标准 envelope | — |
| 2026-04-19 | [paper-trade.md](paper-trade.md) | v1.3 | UX / 数据 surface 5 处修正：F1 Plan 内容指纹 dedup（fingerprint + reconfirmed_count + analysis_ids）+ F2 底部 "AI 最终决策" 改渲染 analysis_history.trade_decision 全文 + F3 新增 analysis_history.executive_summary 列并用 `with_structured_output(ExecutiveSummary)` 抽取（禁写字面量 "regex 解析"）+ F4 日度图表 ECharts 双 grid + drawdown markArea + visualMap + F5 "时间轴 / 策略历史" 合并为 "执行记录" 单 tab 内嵌双视图切换（按 Plan / 按 Event） | — |
| 2026-04-19 | [screener-v3.md](screener-v3.md) | v1.0 | 智能选股 V3：新建 `stock_trading_system/screener/v3/` + 14 大师 agent（12 位 virattt clean-room 重写 + Marks/Dalio 自建）+ 并发 Semaphore(10) + `(ticker,guru,date)` 缓存 + 成本预估动态校准 + Round-table 辩论（Top 5）+ 流式 WebSocket + 预选配置面板 + 经典阈值模式兼容保留（v2 gurus 不动）+ `BaseGuru` 接口保留 aggregator/regime 零改动 | `042a98d` (P0), `8c3ceea` (P1), `40bbad4` (P2+3), `5e0ca93` (P4), `141f8fa` (P5), `cca0ed1` (P6) |
| 2026-04-19 | [screener-v3.md](screener-v3.md) | v1.1 | 复用审计修订（依据 [engineering-principles.md](../engineering-principles.md)）：§4.1 改用 LangChain `ChatOpenAI.with_structured_output(GuruSignal)` 替代自写 JSON 解析；§4.3 改用 `tenacity` 替代自写重试循环；§4.9 复用 TradingAgents `bull_researcher` / `bear_researcher` / `conservative_debator` / `reflection` 作辩论图基底；新增 §12 复用清单；自写 LOC ~31% 下降 | — |
| 2026-04-19 | [engineering-principles.md](../engineering-principles.md) | v1.0 | 新建跨文档原则：复用优先（L0 项目内 → L1 依赖库 → L2 vendor → L3 clean-room → L4 自写）+ 应用规则 + 4 份近期设计审计矩阵 + 对 screener-v3 产生 3 处 P0 修订 | — |
| 2026-04-19 | [multi-tenant.md](multi-tenant.md) | v1.0 | 多租户：新建 `stock_trading_system/auth/` 模块（password/session/invite/repository/decorators/bootstrap）+ 3 张新表（users/invite_codes/user_settings）+ `analysis_bookmarks` 共享收藏 + 6 类私有表 + paper 子表 user_id FK 迁移 + Flask session 认证 + admin 首启自动迁移脚本 `migrations/to_multi_tenant.py` + model-switch router 签名加 user_id + 前端 login/register 两页 | `af6965c` (P0), `01354f3` (P1), `1ac99a5` (P2), `f69b526` (P3), `e1db42b` (P4), `5d32293` (P5) |
| 2026-04-19 | [mobile-optimization.md](mobile-optimization.md) | v1.0 | 移动端统一优化（11 页 × 3 断点）：设计 tokens（断点/字号 clamp/触摸 44px）+ 7 个通用组件（form-row-mobile / num-responsive / table-to-cards / tabs-scrollable / collapse-row / btn-group-wrap / chip-row）+ 11 页逐项清单。含 screener v1.2 移动端专项 | `e198acd` (P0), `1bfd290` (P1), `2380d09` (P2) |
| 2026-04-18 | [model-switch.md](model-switch.md) | v1.0 | 全局模型切换：新建 `stock_trading_system/llm/` 模块（router + client + constants），analyzer graph 按 provider 缓存，screener V2 call site 改用 LLMTextClient 抽象，Nav 下拉 + `/api/settings/llm-provider` GET/POST | `f682855` (P1), `dffbab4` (P2), `a549b90` (P3), `e21f6ac` (P4) |
| 2026-04-18 | [self-iterating-agents.md](self-iterating-agents.md) | v3.0 | 自我迭代能力模块（包裹 TradingAgents）：最大化复用版。Agent Scorer(唯一核心新模块) + Darwinian 权重(采用 atlas-elenchus 常量) + Meta Agent(采用 atlas MUTATOR_SYSTEM_PROMPT) + A/B 验证复用 paper trade sessions。仅 2 张新表 | `e083788` |
| 2026-04-18 | [batch-analyze-holdings.md](batch-analyze-holdings.md) | v1.0 | 一键持仓分析方案：batch_analysis worker + 逐只推送 + 跳过近期 + 进度面板 | — |
| 2026-04-12 | [ui-ux-redesign.md](ui-ux-redesign.md) | v1.0 | 初版 UI/UX 重设计方案：9 页面线框图、移动端适配、组件规范（8 大类） | — |
| 2026-04-12 | [technical-design.md](technical-design.md) | v1.0 | 初版技术方案：前端改造 + 后端 API 补全 + 回测引擎 + PRD 追踪矩阵 | — |
| 2026-04-15 | [architecture-upgrade.md](architecture-upgrade.md) | v1.0 | 架构升级方案：Qwen 主导数据层 + TradingView 图表 + 异步任务系统 | — |
| 2026-04-15 | [architecture-upgrade.md](architecture-upgrade.md) | v1.1 | 补充：三层数据策略、TaskManager 设计、缓存策略、配置扩展 | — |
| 2026-04-15 | [screener-v2.md](screener-v2.md) | v1.0 | 智能选股 V2：8 Agent 并行打分 + 8 Guru 哲学 + Regime 自适应权重 | — |
| 2026-04-16 | [screener-v2.md](screener-v2.md) | v1.1 | 修订：NL 驱动优先，strategy chip 退化为辅助提示 | — |
| 2026-04-16 | [paper-trade.md](paper-trade.md) | v1.0 | 纸面交易方案：AI 信号回放 + 前向追踪 + 权益曲线 | — |
| 2026-04-16 | [paper-trade.md](paper-trade.md) | v1.1 | 修订：独立菜单 + 可选留痕 + 个股绑定 analysis_tracked 表 | — |
| 2026-04-16 | [paper-trade.md](paper-trade.md) | v1.2 | 修订：全量自动追踪（所有非 ERROR 分析自动进入默认 session） | — |
| 2026-04-15 | — | — | Phase A-E 架构升级实施完成（commit `034efe0`） | `034efe0` |

## 决策摘要

| 决策 | 选择 | 原因 |
|------|------|------|
| K 线图方案 | TradingView Widget（展示）+ ECharts（净值/回测） | TV 零数据成本，专业体验 |
| 回测数据源 | yfinance + LocalCache，不走 Qwen | 精度 + 可复现性 |
| 异步任务 | ThreadPoolExecutor + SQLite，非 Celery | 单人项目，零运维 |
| 数据主源 | Qwen（语义/判断/单点查询），Local（精确结构化） | LLM 做语义，专业 API 做数据 |
| 选股 V2 NL 优先 | 自然语言输入为主，strategy 为辅 | 用户反馈 |
| 纸面交易追踪 | 全量自动，非 opt-in | 100% 覆盖率，AI 效果可量化 |
