# 测试用例变更记录

| 日期 | 文档 | 版本 | 用例数 | 变更内容 | 关联设计 |
|------|------|------|--------|---------|---------|
| 2026-04-14 | [v2.0-manual-test-cases.md](v2.0-manual-test-cases.md) | v1.0 | 151 | 初版测试用例：后端 API(42) + 前端页面(47) + 移动端(12) + WebSocket(8) + 状态(10) + 图表(8) + Toast(4) + 跨页面(4) + 异常(9) + 性能(7) | PRD v2.0 + 技术方案 v1.0 |
| 2026-04-15 | [architecture-upgrade.md](architecture-upgrade.md) | v1.0 | 204 | 架构升级测试用例：TaskManager(51) + LocalCache(18) + DataRouter(17) + Qwen 扩展(16) + TV Widget(16) + 回测(16) + 任务中心 UI(19) + WebSocket(6) + 性能(12) + 幂等(5) + 异常(10) + 回归(8) | 架构升级方案 |
| 2026-04-15 | [screener-v2.md](screener-v2.md) | v1.0 | 110 | 选股 V2 测试用例：单元测试(56) + 集成(18) + 前端(20) + 回归(8) + 性能(8) | 选股 V2 技术方案 |
| 2026-04-18 | [model-switch.md](model-switch.md) | v1.0 | 66 | 模型切换测试用例：单元(22: resolver 12 + client 4 + config 6) + 集成(11: analyzer 6 + screener 5) + API(10) + 前端(7) + 异常(8) + 回归(5) + 性能(3) | 模型切换技术方案 |
| 2026-04-18 | [mobile-optimization.md](mobile-optimization.md) | v1.0 | 82 | 移动端优化测试用例：通用组件单元(12) + 断点矩阵 11 页×3 断点(33) + 可达性(8) + 表格卡片降级(5) + 横滑(4) + 折叠行(5) + 性能 Lighthouse(4) + 桌面回归(6) + 真机(5) | 移动端优化技术方案 |
| 2026-04-19 | [multi-tenant.md](multi-tenant.md) | v1.0 | 130 | 多租户测试用例：auth 单元(14) + 邀请码(8) + repository(10) + 迁移脚本(9) + 权限隔离(18) + 共享可见性(6) + 任务中心(7) + model-switch 用户级(6) + auth API(14) + admin API(6) + 前端 E2E(10) + 安全(10) + 回归(5) + 性能(4) + 真机(3) | 多租户技术方案 |
| 2026-04-19 | [screener-v3.md](screener-v3.md) | v1.0 | 145 | 选股 V3 测试用例：Pydantic 单元(8) + 14 大师(52) + Pipeline(9) + 并发重试(7) + 缓存(6) + 成本预估(6) + 流式 WS(5) + 圆桌辩论(8) + API(10) + 前端(12) + 经典兼容(5) + 跨模块集成(8) + 性能(5) + 回归(4) | 选股 V3 技术方案 |
| 2026-04-19 | [paper-trade.md](paper-trade.md) | v1.0 | 89 | 纸面交易测试用例（首版，补齐历史缺口）：基线 v1.0-v1.2(38) + v1.3 F1 dedup(10) + F2 AI 决策 surface(6) + F3 executive_summary(9) + F4 图表(7) + F5 tab 合并(8) + 集成(6) + 性能回归(5) | 纸面交易 v1.0-v1.3 |
| 2026-04-20 | [unified-progress.md](unified-progress.md) | v1.0 | 101 | 统一进度系统测试用例：emit_event 单元(8) + task_events 表(5) + ProgressStream 组件(12) + per-user room(7) + 断线续传(8) + 11 task 发射(12) + 5 页面集成(10) + 3 布局视觉(9) + 5 态动画(6) + 移动端(6) + 异常(8) + 性能(5) + 回归(5) | 统一进度系统技术方案 |
| 2026-04-21 | [ui-react-island.md](ui-react-island.md) | v1.0 | 108 | UI React Island 测试用例：构建管道 Vite+Flask(10) + lib api/socket/auth(12) + shadcn 组件(14) + Screener V3 island(12) + Tasks(10) + Paper-trade(8) + Dashboard(7) + 跨岛集成(6) + 视觉一致性(8) + 非迁移页回归(7) + 性能(5) + 安全 CSRF(5) + 真机部署(4) | UI React Island 技术方案 |
| 2026-04-21 | [ui-react-island.md](ui-react-island.md) | v2.0 | 74 | 剩余 11 页测试用例：共享组件 AppShell/DataTable/Form/EChartsPanel(12) + Portfolio/History/Alerts/Reports(20) + Backtest/Paper list/Analysis(18) + Settings(7) + Auth Login/Register/Reset(9) + Phase 18 废弃旧代码(5) + v2.0 性能(3) | UI React Island v2.0 技术方案 |
| 2026-04-24 | [ui-migration-validation.md](ui-migration-validation.md) | v1.0 | 164 | 架构级迁移完整验证测试用例：L0 冒烟 5 + L1 基础 E2E 33 + L2 功能回归矩阵 74 + L3 跨模块集成脚本 20 + L4 数据完整性（row count/抽样/invariant/FK）14 + L5 对抗性（越权 8 + CSRF 3 + session 4 + 并发 3）18 | 迁移验证技术方案 |
| 2026-04-25 | [ui-react-island-regression.md](ui-react-island-regression.md) | v1.0 | 90 | 迁移回归修复测试用例：P0 CRITICAL 9 + P1 HIGH 26 + P2 MEDIUM/LOW 24 + 共享组件（Stat/ChartPanel/form-row-mobile）8 + Playwright E2E 12 + 视觉回归 11；P0 闸门强约束 + 老 Jinja baseline 截图归档 | 迁移回归修复技术方案 |
| 2026-04-25 | [ui-react-island-regression.md](ui-react-island-regression.md) | v1.1 | 94 | 补充：P0 新增 paper-trade 列表页 1 条（TC-RG-P0-3b 默认 session 突出卡 + 工具栏 + 卡 grid）+ 菜单重组 3 条（TC-RG-P0-10~12 桌面 Sidebar 6 组 / active 高亮 / Mobile Tabbar 5+更多） | 迁移回归修复 v1.1 |
| 2026-04-25 | [ui-react-island-regression.md](ui-react-island-regression.md) | v1.2 | 97 | 补充：P0 新增 Tasks 5 项（TC-RG-P0-13~17 分页/类型 chip/scope tab/9 类 task→落地页跳转/详情操作齐全）；P1 Tasks 用例由 3 → 1（升级合并） | 迁移回归修复 v1.2 |
| 2026-04-25 | [ui-react-island-regression.md](ui-react-island-regression.md) | v1.3 | 102 | 补充实测 P0 5 项：TC-RG-P0-18 Tasks 空白 bug / P0-19 Paper-trade ticker 详情空白 bug / P0-20 Settings 缺 Gemini+Qwen API key 字段 / P0-21~22 LLMSwitcher 4 状态完整 | 迁移回归修复 v1.3 |
| 2026-05-03 | [analysis-progress-truth-source.md](../design/analysis-progress-truth-source.md) | v1.0 | 4 | AI 分析进度真源测试（test_progress_truth_source.py）：envelope shape / task_progress payload contract / 5→85 linear mapping / structural stage id 4 case 锁 TaskManager._emit 广播统一 envelope + analyzer step_done 桥接 progress_cb 契约 | 统一 AI 分析进度真相源 v1.0 |
| 2026-05-03 | [analysis-rendering.md](../design/analysis-rendering.md) | v1.4.1 | 6 | AI 分析详情布局/8 tab/K 线/Quick-info 顺序测试（AnalysisDetailView.order.test.tsx，vitest）：3 个 anchor (analysis-tabs / kline-section / quickinfo-row) querySelectorAll length===1 唯一性 + 严格 tabs→kline→quickinfo 顺序 + legacy Stats 3 卡缺席 + completed 任务隐藏 PipelineDAG。锁 v1.8 v1.8.1 反复出现的旧布局残留 + 5min 时间启发式问题 | 详情页板块顺序 v1.8 + v1.8.1 |
| 2026-05-03 | [task-failure-visibility.md](../design/task-failure-visibility.md) | v1.0 | 22 | 任务失败原因可见化测试（test_task_detail_failure.py 4 case + test_workers_qwen_errors.py 18 case）：owner 见 trace / 非 owner 共享类只见 message / admin 见 trace / 缺 trace 兜底 + Qwen/DashScope/Gemini 缺 key/401/403/404/timeout/429 全套包装 + traceback __cause__ 链保留 | 任务失败原因可见化 v1.0 |
| 2026-05-03 | [llm-fallback.md](../design/llm-fallback.md) | v1.0 | 21 | LLM 跨 provider 自动 fallback 测试（test_rate_limit_classification.py 10 + test_resilient_chat.py 6 + test_screener_integration.py 5）：限流 type/字符串识别（429 / quota / RESOURCE_EXHAUSTED / too many requests）+ 拒识非限流（auth/timeout/validation/500） + 缺 key 降级 + disabled 降级 + 限流自动切 + structured_output passthrough + counter telemetry | LLM 跨 provider fallback v1.0 |
| 2026-05-03 | [screener-v3.md](../design/screener-v3.md) | v1.4 | 47 | V3 选股 v1.4 8 处契约缺口测试（test_v14_contracts.py 12 + test_screen_v3_trigger.py 14 + test_screen_v3_run_metadata.py 8 + test_pipeline_progress_events.py 6 + test_guru_signal_uniqueness.py 13 - 6 既有重叠）：classic mode 真路径 / cancel 部分结果 / trigger 14 大师 + candidate_n + mode 校验 / cache hit 真计数 / roundtable status 区分 / unit start/done/failed/cached 4 态 / data bundle 增 news+price_history+sector / consensus 算法重写 / guru reasoning 框架区分 | Screener V3 v1.4 |
| 2026-05-03 | [screener-history.md](../design/screener-history.md) | v1.1 | 6 | V3 选股 stage 进度事件测试（test_pipeline_progress_events.py）：pipeline 至少发 screen_v3_stage_start{stage=parse} + _done{stage=guru} + aggregate_done；agent_rt 模式发 roundtable_start | screener-history v1.1 |
| 2026-05-03 | [paper-trade.md](../design/paper-trade.md) | v1.4 | 17 | Paper trade advice/private advice/track/save_plan 测试（test_paper_track.py 6 + test_signal_loader.py 5 + test_backfill_user_advice.py 3 + test_fresh_db_save_plan.py 3）：advice 用户隔离 / 跨用户不泄露 / 401 未登录 / 立即成交 / fresh DB 自初始化 v1.3 列 / signal_loader 双键名归一 / backfill 历史 advice 入 user_analysis_advice | 纸面交易 v1.3 / v1.4 |
| 2026-05-03 | [unified-progress.md](../design/unified-progress.md) | v1.1 | 11 | 分析记录 inbox 实时进度回放测试（test_history_inbox.py）：optimistic insert 字段契约 / submit→inbox 端到端 blocking worker stub / running row 立即出现 / progress_pct 增长 / 完成替换为 completed | 统一进度系统 v1.1 |
| 2026-05-03 | [reports-backtest-contract.md](../design/reports-backtest-contract.md) | v1.0 | 7 | 报告中心与策略回测 contract 测试（test_backtest_contract.py）：strategies endpoint 返 canonical id / entries 同时含 name + label / report task private / report submit type 字段 / task result endpoint backtest shape unpack / not-success 404 | 报告 + 回测契约 |
| 2026-05-03 | [ui-react-island.md](../design/ui-react-island.md) | v3.0 | 13 | Vite base + static cache + modulepreload + frontend perf 测试（test_vite_asset_base.py 8 + test_static_cache_headers.py 2 + test_vite_modulepreload.py 3）：vite base=/static/dist/ + manifest.json no-store + assets immutable 1y + react-vendor chunk 独立 ≥50kB / card chunk ≤250kB / socket+ChartPanel 仅在 dynamicImports 不在 imports | UI React Island v3.0 perf |
| 2026-05-03 | [analysis-rendering.md](../design/analysis-rendering.md) | v1.2 + v1.3 | 32 | AI 分析结构化卡片 ErrorBoundary + 防御 normalize + lazy-bundle 循环修复 vitest（AnalysisCards.test.tsx 8 + OverviewCard.executive.test.tsx 4）+ pytest（test_analysis_sndk_smoke.py 9 + test_analysis_rendering_normalize.py 11）：8 tab 形态合规 / 数组 / 混合 string/null/object/array / 真实 render() 不出 fallback 文案 / executive summary 位置 + whitespace 兜底 | 分析结构化渲染 v1.2 + v1.3 |
| 2026-05-03 | [conftest.py](../../tests/conftest.py) | iso-fix | — | 测试基础设施修复：app_client fixture 增加 settings._config / event_emitter._seq_cache 重置 + web.app 模块的 get_config/load_config/save_config 已绑定引用刷新（修 monkeypatch.setattr lambda 跨测试泄露到 web.app's import 的 binding 缓存导致后续 web 测试见不到 users 表） | 测试隔离 |

## 用例总数汇总

| 文档 | 用例数 |
|------|--------|
| V2.0 手动测试用例 | 151 |
| 架构升级测试用例 | 204 |
| 选股 V2 测试用例 | 110 |
| 模型切换测试用例 | 66 |
| 移动端优化测试用例 | 82 |
| 多租户测试用例 | 130 |
| 选股 V3 测试用例（v1.0 + v1.4 47 + history v1.1 6） | 198 |
| 纸面交易测试用例（v1.0 + v1.4 17） | 106 |
| 统一进度系统测试用例（v1.0 + v1.1 11） | 112 |
| UI React Island 测试用例（v1.0 + v2.0 + v3.0 perf 13）| 195 |
| 迁移验证测试用例 | 164 |
| 迁移回归修复测试用例（v1.0 ~ v1.3）| 102 |
| AI 分析进度真源测试用例 | 4 |
| AI 分析详情布局/顺序测试用例 | 6 |
| 任务失败原因可见化测试用例 | 22 |
| LLM 跨 provider fallback 测试用例 | 21 |
| 报告 + 回测契约测试用例 | 7 |
| AI 分析结构化卡片 v1.2/v1.3 测试用例 | 32 |
| **总计** | **1712** |

## 覆盖状态（2026-05-03 更新）

- 自动化测试（Python pytest）：~700 已实现
  - tests/llm: 45（rate limit + resilient chat + screener integration + router + client）
  - tests/tasks: ~120（task_manager + workers + event_emitter + progress_truth_source + workers_qwen_errors + cleanup + task_store + task_api）
  - tests/web: ~280（analysis_detail/sndk/rendering/normalize + history_inbox/dto_isolation/redirect/compare_timeline/dashboard/alerts + paper_track + backtest_contract + vite_asset_base + static_cache_headers + vite_modulepreload + screen_v3_trigger/results/run_metadata/history + task_detail_failure + signal_consistency + analysis_actions/depth/quick_info/delete_permission/paper_ticker_detail_privacy + …）
  - tests/screener/v3: ~178（v14 contracts + pipeline_progress_events + guru_signal_uniqueness + theme_aware_prompts + pipeline_storage_fallback + concurrency + …）
  - tests/strategy/paper_trader: ~60（signal_loader + backfill_user_advice + fresh_db_save_plan + plan_dedup + executive_summary 等）
  - tests/auth + tests/portfolio + tests/data 等：~80
- 自动化测试（Node vitest）：21 已实现（AnalysisCards 8 + OverviewCard.executive 4 + AnalysisDetailView.order 6 + depth-label 3）
- 手动测试用例：~1700 已定义（设计文档 changelog 链路）
- 测试基础设施：app_client fixture 现在会重置 settings._config 和 web.app 模块的 get_config 已绑定引用，防 monkeypatch lambda 跨测试泄露
