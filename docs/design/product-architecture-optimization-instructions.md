# 产品与技术架构优化合并指令

| 项 | 值 |
|---|---|
| 文档用途 | 给实施会话/开发者的合并优化指令 |
| 日期 | 2026-04-25 |
| 范围 | 产品设计、技术架构、代码审查发现、多租户数据边界 |
| 原则 | 先安全与可用，再体验闭环，最后架构治理 |

## 0. 总定位

系统应定位为：

> 多用户共享的投资研究库，每个用户拥有自己的持仓、提醒、偏好和个人操作建议。

这不是传统 SaaS 的“所有数据完全隔离”，也不是单机个人工具。正确的数据模型是：

- **共享研究数据**：AI 分析、选股结果、回测结果、公开报告、Agent 评分、Prompt 版本。
- **私有用户数据**：用户账户、持仓、交易记录、组合快照、个人提醒、个人设置、个人 API key、基于自己持仓生成的操作建议。
- **审计与编排数据**：任务、任务事件、创建者、执行状态；结果是否共享按任务类型决定。

核心产品价值是：一个用户跑出的高成本研究结果可以被其他用户复用，但任何人的持仓和个人决策上下文不能泄露。

## 1. P0：安全与可用性底座

### 1.1 修正认证启动策略

当前未迁移或空 users 表时，系统会放开全部访问。必须改为：

- 未完成多租户初始化时，只允许 `/api/health`、登录/注册页、初始化/迁移入口访问。
- 禁止访问持仓、任务、设置、分析历史等业务 API。
- `/api/seed` 只允许测试环境或 admin 调用。
- 不公开返回真实邀请码；注册页最多显示“需要邀请码”，不列出可用 code。

### 1.2 明确数据分层

按以下分层修正 schema、repository 和 API 查询：

```text
private_user_data:
  users
  user_settings
  positions
  transactions
  daily_snapshots
  alerts
  alert_history
  user_analysis_advice
  user_bookmarks

shared_research_data:
  analysis_history
  screen_results
  screen_results_v2
  backtest_results
  report_results
  agent_scorecards
  prompt_versions

audit_orchestration_data:
  tasks
  task_events
```

实现要求：

- `positions` 不能再用 `ticker` 全局主键，改为 `(user_id, ticker)` 唯一。
- `transactions`、`daily_snapshots`、`alerts`、`alert_history` 必须按 `user_id` 过滤。
- `analysis_history`、`screen_results*`、`backtest_results` 默认共享，但保留 `created_by`、`provider`、`model`、`config_hash`、`created_at`。
- 所有写操作必须记录 `created_by` 或 `user_id`，用于审计和权限控制。

### 1.3 拆分共享分析与个人建议

AI 分析要拆成两层：

```text
shared_analysis_result:
  ticker
  date
  market_report
  fundamentals_report
  sentiment_report
  news_report
  investment_debate
  risk_assessment
  final_signal
  provider
  model
  config_hash
  created_by

private_user_advice:
  user_id
  analysis_id
  holdings_context_snapshot
  action
  confidence
  suggested_position_pct
  entry_price_low
  entry_price_high
  stop_loss
  take_profit
  reasoning
  risk_warning
```

不要再把基于个人持仓生成的 `advice` 直接混进共享 `analysis_history`。否则共享分析会泄露用户成本价、仓位和操作意图。

### 1.4 修任务系统权限与契约

任务系统必须保留 `created_by=g.user.id`，但任务结果可按类型共享：

- `analysis`、`screen_v2`、`screen_v3`、`backtest`、`report`：结果共享可读。
- `portfolio_batch`、`personal_advice`、`alerts`、持仓相关任务：仅本人可读。
- 普通用户只能取消、删除、重试自己创建的任务。
- admin 可看全部任务审计。

接口契约统一：

```json
{
  "tasks": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

前端可兼容旧字段 `items`，但后端以后统一返回 `tasks`。

`TaskManager._emit()` 必须使用当前 manager 注入的 `socketio` 发事件，并将事件持久化到 `task_events`。任务事件只推送到创建者房间；共享结果完成后可通过结果页被其他用户读取。

### 1.5 修 Settings 与模型切换

Settings 前后端必须使用同一 schema：

- 后端可写字段仍使用 dotted path，例如 `gemini.api_key`、`qwen.api_key`、`alerts.email.enabled`。
- 前端不要提交 `provider/model/api_keys/alerts` 这种旧聚合对象。
- Provider 选择只展示当前后端支持的 `qwen` 和 `gemini`。
- 增加 `GEMINI_API_KEY`、`DASHSCOPE_API_KEY`、`QWEN_API_KEY` 的清晰标签。
- 环境变量锁定时 UI 禁用切换，并说明优先级：env > user_settings > yaml > legacy auto-detect。

实现 `LLMSwitcher`：

- 挂到桌面 Sidebar/Topbar 和移动菜单。
- 支持 active、missing key、env locked、loading 四种状态。
- 切换成功后清空 `_analyzer`，并让 Analyzer graph cache key 包含 provider、model、key/config version、user。

### 1.6 修已确认运行时 bug

- `/api/portfolio/<ticker>` 调用了不存在的 `PortfolioManager.remove_position`，实现该方法或改为调用 `PortfolioDatabase.delete_position`。
- `/paper-trade/<ticker>/` 尾斜杠会导致 ticker 解析为空，改用 `pathname.split("/").filter(Boolean).pop()` 或正则。
- 任务中心后端返回 `items`、前端读 `tasks` 的 schema mismatch 必须修。

## 2. P1：产品体验闭环

### 2.1 重组信息架构

导航按 6 组组织：

```text
概览:
  仪表盘

分析:
  AI 分析
  分析记录
  报告中心

选股:
  智能选股 V3
  策略回测

持仓:
  持仓管理
  预警中心

纸面交易:
  全部会话

系统:
  任务中心
  设置
```

移动端底部保留 5 个主入口：仪表盘、分析、选股、持仓、更多。

### 2.2 固化三条核心工作流

盘前研究：

```text
Dashboard -> Screener -> Analysis -> Watchlist/Report
```

盘中管理：

```text
Alerts -> Portfolio -> Quote/Analysis -> Personal Advice
```

盘后复盘：

```text
Paper Trade -> Backtest -> History Compare -> Report
```

每条路径控制在 2-3 次点击内。任务完成后不要停在任务详情页，要跳到业务结果页。

### 2.3 任务结果落地页映射

实现 `getTaskResultUrl(task)`：

| task.type | success 落地页 |
|---|---|
| analysis | `/analysis/<analysis_id>` |
| screen / screen_v2 / screen_v3 | `/screener-v3?result=<result_id>` |
| backtest | `/backtest/<result_id>` |
| report | `/reports?id=<result_id>` |
| paper_trade | `/paper-trade/<ticker>` |
| paper_backfill | `/paper-trade` |
| qwen_fundamentals / qwen_news | `/analysis?ticker=<ticker>` |
| agent_score_update / meta_evolution / echo | `/tasks/<task_id>` |

运行中点击任务进入 `/tasks/<id>` 看进度；完成后点击进入结果页。

### 2.4 补关键页面能力

- Dashboard：净值曲线、仓位分布饼图、最近任务、快捷入口。
- Analysis：K 线、7 Tab 报告、Pipeline DAG、共享分析与个人建议分区展示。
- Portfolio：卖出表单、修正成本、交易记录 tab、持仓表市场/市值列。
- Paper Trade：`/paper-trade` 列表页、ticker 详情尾斜杠修复、权益曲线。
- Tasks：分页/加载更多、类型过滤、我的/共享/全部 scope、结果跳转。
- Settings：模型/API Key、数据源、通知、调度器、安全分区。

### 2.5 移动端与图表规范

- 新建或统一使用 `ChartPanel` 封装 ECharts 初始化、ResizeObserver、dispose。
- 所有金额/统计值使用响应式字号、`font-mono`、`tabular-nums`、`truncate`。
- 所有多列表单在 575.98px 以下单列。
- 复杂 Tabs 支持横向滚动。
- 关键触控目标不小于 44px。

## 3. P2：技术架构治理

### 3.1 统一数据源策略

数据源职责：

```text
Schwab:
  美股实时价格、批量 quotes、账户只读、订单只读、可选历史 K 线兜底

yfinance / AkShare:
  历史 OHLCV、回测真值、fallback

Qwen:
  新闻、基本面摘要、语义判断、AI 分析、选股解释

TradingView Widget:
  前端 K 线展示，不作为后端回测数据源
```

LLM 不参与回测 OHLCV 真值来源。

### 3.2 建立 Provider 能力矩阵

每个 provider 标注能力：

```text
realtime_price
batch_quotes
historical_bars
fundamentals
news
account_positions
orders
```

DataRouter 按能力路由，不再靠散落的 if/else 链条。

### 3.3 加强共享结果缓存与复用

共享研究任务需要按参数去重：

```text
analysis_cache_key:
  ticker + date + provider + model + prompt_version/config_hash

screen_cache_key:
  market + nl_query + gurus + provider + model + config_hash

backtest_cache_key:
  ticker + strategy + params + period + data_source_version
```

命中已有共享结果时直接返回 result，不重复跑 LLM。

### 3.4 清理全局单例

当前 `web/app.py` 中 `_analyzer`、`_data_manager`、`_router`、`_task_manager` 等全局单例会让配置切换和用户级设置失效。短期要求：

- 单例按 config version/user/provider 失效。
- Settings、LLM Switch、API key 更新后重置相关依赖。

长期建议：

- 拆 Flask 蓝图。
- 引入轻量 dependency container。
- 把 app.py 从“所有路由大文件”拆成 auth、portfolio、research、tasks、settings、diagnostics。

### 3.5 自迭代 Agent 权重持久化

`AgentScorer` 当前权重只存在内存里，新建 scorer 会回到 1.0。必须新增 `agent_weights` 表：

```text
agent_id
weight
updated_at
updated_by_task_id
```

`get_weight`、`save_weight`、`get_all_weights` 改为读写 DB。否则 Darwinian 调权不会跨任务生效。

### 3.6 统一异步原则

所有超过 2 秒的操作走 TaskManager：

- AI 分析
- 选股
- 回测
- 报告
- 批量持仓分析
- Agent 评分更新
- Meta evolution

同步 API 仅保留：

- health
- quote/price 单点
- 轻量列表查询
- 设置读取

逐步废弃旧 `/api/analyze`、`/api/screen` 的后台线程直发 WebSocket 模式，统一改为任务提交。

## 4. 文档与测试治理

### 4.1 更新文档真源

保留一个新的“当前架构总览”作为真源，内容必须包含：

- 当前产品定位
- 共享研究库 + 私有持仓的数据边界
- React/Vite 前端基线
- TaskManager 异步任务基线
- Schwab/Qwen/yfinance/AkShare 数据职责
- LLM provider 优先级

旧文档如果与当前基线冲突，标记为 archived 或在顶部加“历史方案，仅供参考”。

### 4.2 测试修复顺序

当前测试基线曾出现 `518 passed, 39 failed`。先按以下顺序修：

1. 测试环境依赖：确保 `requirements.txt` 完整安装，包括 langchain 相关包。
2. 鉴权测试夹具：需要业务 API 的测试必须登录或构造初始化后的用户。
3. 任务事件测试：TaskManager 注入 socketio 后应能捕获事件。
4. Settings/LLM provider API 测试：使用临时 `STOCK_CONFIG_DIR`，不能写真实 `~/.stock_trading`。
5. 前端 build：`npm run build`。
6. 关键 E2E：登录、持仓 CRUD、任务提交、LLM 切换、分析复用、任务结果跳转。

## 5. 推荐实施顺序

按阶段拆 PR 或 commit：

1. **P0-A 数据边界与认证**：启动鉴权、私有持仓隔离、共享研究表边界。
2. **P0-B 任务与事件**：created_by、tasks schema、socket event、权限控制。
3. **P0-C Settings 与 LLM Switch**：dotted path schema、LLMSwitcher、Analyzer cache 失效。
4. **P0-D 明确 bug 修复**：remove_position、paper-trade 尾斜杠、任务空白。
5. **P1-A 产品导航与任务落地页**：Sidebar 分组、移动更多菜单、getTaskResultUrl。
6. **P1-B 页面能力补齐**：Dashboard、Analysis、Portfolio、Paper Trade、Tasks、Settings。
7. **P2-A DataRouter 与 Schwab**：Provider 能力矩阵、Schwab 批量 quotes、数据源职责。
8. **P2-B 架构拆分**：Flask 蓝图、dependency container、全局单例治理。
9. **P2-C 自迭代持久化**：agent_weights 表、权重上下文跨任务生效。
10. **P2-D 文档与 CI**：当前架构总览、旧文档归档、完整测试 gate。

## 6. 验收标准

- 未登录用户无法访问任何私有数据。
- Alice 和 Bob 的持仓、交易、提醒、个人建议互不可见。
- Alice 生成的 AI 分析、选股、回测结果可被 Bob 读取和复用。
- 共享分析中不包含任何用户持仓上下文。
- 任务列表能区分“我的任务 / 共享研究任务 / 全部任务”。
- 普通用户不能取消、删除、重试别人创建的任务。
- LLM 切换后下一次分析实际使用新 provider/model。
- Settings 能成功保存 Gemini/Qwen key 和通知设置。
- 任务中心不空白，完成任务能跳转到业务结果页。
- 前端 build 通过，关键 E2E 通过。
- `pytest` 基线恢复稳定，不再因为鉴权、依赖、真实 home 目录写入而失败。

## 7. 2026-04-26 验收回归补充指令

### 7.1 当前验收结论

本轮代码已覆盖部分原始 review finding，但仍未达到可签收状态。需要继续按 P0 修复并补测试。

已基本通过：

- 未迁移或空 `users` 表时，不再开放全部业务访问；未初始化 API 应返回 `503 not_initialized`，页面跳登录。
- 通用 `/api/tasks/submit` 已传入 `created_by=g.user.id`，`TaskManager.submit()` 也能从 request context 兜底推断用户。
- `/api/tasks` 响应已包含 `tasks/items/total/limit/offset`，任务中心列表 schema mismatch 本体已修。

未通过：

- `POST /api/settings/llm-provider` 调用了不存在的 `_invalidate_singletons()`，登录后切换模型会 500。
- Settings 页面仍提交旧 schema `{provider, model, api_keys, alerts}`，后端仍只接受 dotted path，保存会返回 `400 No writable fields provided`。
- Tasks 前端发送 `scope=my`，后端只识别 `mine/shared_research/all`；这会绕过过滤，普通用户可能在列表里看到其他用户任务，包括私有任务。
- `GET /api/tasks/<task_id>` 没有权限校验，普通用户可读取其他用户私有任务详情；`/result` 有校验但 detail 已泄漏元数据。
- 当前测试夹具未适配鉴权，大量 API 测试只拿到 401，无法作为回归保护。
- 前端 `npm run build` 当前失败，存在 TypeScript 与路径解析错误。

### 7.2 P0 修复指令

#### P0-1 修复 LLM 切换运行时错误

目标文件：

- `stock_trading_system/web/app.py`

要求：

- 将 `set_llm_provider()` 中不存在的 `_invalidate_singletons(["llm_provider"])` 改为现有的 `_reset_config_dependent_singletons(["llm_provider"])`。
- 切换成功后必须清空 `_analyzer`，下一次分析必须重新创建 `StockAnalyzer`。
- `get_active_provider()` 如果支持 `user_id`，`GET/POST /api/settings/llm-provider` 应保持同一优先级：`env > user_settings > yaml > legacy auto-detect`。
- 为 `POST /api/settings/llm-provider` 增加登录后的 API 测试：成功切换、缺 key、env locked、非法 provider、连续切换。

验收：

```text
登录后 POST /api/settings/llm-provider {"provider":"gemini"} 返回 200
不再出现 NameError: _invalidate_singletons is not defined
切换后 _analyzer is None，下一次分析使用新 provider
```

#### P0-2 统一 Settings 前后端 schema

目标文件：

- `stock_trading_system/web/frontend/src/islands/settings/SettingsPage.tsx`
- `stock_trading_system/web/app.py`
- `stock_trading_system/config/settings.py`

要求：

- 前端加载 `/api/settings` 时读取后端现有结构：`gemini`、`qwen`、`telegram`、`email`、`ib`、`polygon`。
- 前端保存时只提交 dotted path：

```json
{
  "gemini.api_key": "...",
  "gemini.model": "...",
  "qwen.enabled": true,
  "qwen.api_key": "...",
  "qwen.model": "...",
  "qwen.base_url": "...",
  "alerts.email.enabled": true,
  "alerts.email.to_address": "...",
  "alerts.telegram.enabled": false
}
```

- 不再提交 `provider`、`model`、`api_keys`、`alerts` 旧聚合对象。
- Settings 页面只展示后端支持的 LLM provider：`qwen`、`gemini`。
- OpenAI、Anthropic、DeepSeek 字段先移除，除非后端真的支持。
- 空字符串允许提交，用于清空错误 key。

验收：

```text
Settings 保存 Gemini/Qwen API key 返回 200
后端返回 applied 包含对应 dotted path
旧 schema 不再由前端发出
```

#### P0-3 修复任务 scope 契约与私有任务泄漏

目标文件：

- `stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx`
- `stock_trading_system/web/app.py`
- `stock_trading_system/tasks/task_store.py`

要求：

- 前端 scope 枚举改为后端契约：`mine | shared_research | all`。
- UI 文案建议：
  - `mine`：我的任务
  - `shared_research`：共享研究
  - `all`：全部（仅 admin 可见或可用）
- 后端对未知 `scope` 必须拒绝或降级到 `mine`，不能因为未知值变成无过滤。
- 普通用户请求 `scope=all` 时，可降级为 `shared_research`，但不能返回私有任务。
- `TaskStore.PRIVATE_TYPES` 必须覆盖所有持仓、提醒、纸面交易、个人建议类任务。
- `TaskStore.SHARED_TYPES` 仅覆盖分析、选股、回测、公开报告类任务。

验收：

```text
Alice GET /api/tasks?scope=mine 只返回 Alice 创建的任务
Alice GET /api/tasks?scope=shared_research 可看到 Bob 的 analysis/screen/backtest/report
Alice GET /api/tasks?scope=shared_research 看不到 Bob 的 paper_trade/personal_advice/alerts
Alice GET /api/tasks?scope=my 不得绕过过滤；返回 400 或按 mine 处理
```

#### P0-4 给任务详情加权限校验

目标文件：

- `stock_trading_system/web/app.py`

要求：

- `GET /api/tasks/<task_id>` 必须调用 `_check_task_ownership(task)`。
- 对共享任务类型，其他用户可读详情，但不可取消、删除、重试。
- 对私有任务类型，非 owner 且非 admin 返回 403。
- `cancel/delete/retry` 继续要求 owner 或 admin。
- 如果任务详情中包含敏感 params，需要对共享任务详情做 params 白名单或脱敏，避免把用户私有上下文混入共享任务。

验收：

```text
Alice GET Bob 的 paper_trade task detail 返回 403
Alice GET Bob 的 analysis task detail 返回 200
Alice POST Bob 的 analysis cancel/delete/retry 返回 403
Admin 可读全部任务详情
```

#### P0-5 修复 Screen V2/V3 任务创建用户归属

目标文件：

- `stock_trading_system/web/app.py`

要求：

- `/api/screen/v2/submit` 和 `/api/screen/v3/trigger` 调用 `tm.submit()` 时显式传 `created_by=g.user.id`。
- `screen_v3` params 中可以保留 `user_id` 用于估算或审计，但任务 owner 必须来自 `created_by`。
- 所有绕过 `/api/tasks/submit` 的任务提交路径都要做同样审查：report、backtest、paper trade、batch analysis、agent evolution。

验收：

```text
任何 Web 路由创建的 task.created_by 都是当前登录用户 id
不再出现新任务 created_by='user'
```

#### P0-6 修复 TaskManager 事件测试与实际推送路径

目标文件：

- `stock_trading_system/tasks/task_manager.py`
- `stock_trading_system/tasks/event_emitter.py`
- `tests/tasks/test_task_manager.py`

要求：

- `TaskManager._emit()` 需要同时满足：
  - 持久化事件到 `task_events`。
  - 使用当前 TaskManager 注入的 `socketio` 发事件，而不是测试时绕到全局 `web.app.socketio`。
  - 推送到 `user:{created_by}` room。
- 测试中注入的 `RecordingSocketIO` 应能捕获 `task_created/task_started/task_progress/task_completed/task_failed`。
- 如果无法解析 `created_by`，可以退化为 direct emit，但不能让测试事件完全消失。

验收：

```text
pytest -q tests/tasks/test_task_manager.py 通过
task_events 表能查询到任务生命周期事件
SocketIO room 推送仍按用户隔离
```

#### P0-7 修复测试夹具鉴权

目标文件：

- `tests/web/test_llm_provider_api.py`
- `tests/tasks/test_task_api.py`
- 相关 validation tests

要求：

- 需要访问业务 API 的测试必须创建已迁移用户表并登录。
- 测试配置必须使用临时 `STOCK_CONFIG_DIR` 和临时 `portfolio.db`，不能写真实 `~/.stock_trading`。
- 区分两类测试：
  - anonymous security tests：期望 401/302/503。
  - authenticated business tests：先登录，再验证业务响应。
- 补跨用户任务权限测试：Alice/Bob/Admin 三类 client。

验收：

```text
pytest -q tests/web/test_llm_provider_api.py tests/tasks/test_task_api.py tests/tasks/test_task_manager.py tests/auth/test_auth_module.py 通过
```

#### P0-8 修复前端 build

目标文件：

- `stock_trading_system/web/frontend/src/**`
- `stock_trading_system/web/frontend/tsconfig.json`
- `stock_trading_system/web/frontend/vite.config.ts`

要求：

- 修复 `@/styles/index.css` 解析失败。
- 修复 `lightweight-charts` v5 API 不匹配：`addCandlestickSeries`、`addHistogramSeries` 需要按当前版本 API 调整，或替换为已封装的 ChartPanel/ECharts。
- 清理 `noUnusedLocals` 下所有未使用变量。
- 修复 `Badge` variant 类型，不能传未定义的 `secondary`。
- 修复 `AnalysisDetail.task_id` 类型缺失。
- 修复 `ScreenerV3Page` 的 `Guru` 类型字段缺失。

验收：

```text
cd stock_trading_system/web/frontend
npm run build
```

必须通过。

### 7.3 P1 产品与架构优化建议

#### P1-1 明确任务中心三视图

任务中心不应只有“我的/全部”。按产品定位，应有：

```text
我的任务:
  当前用户创建的所有任务，包括私有任务与共享研究任务。

共享研究:
  所有人创建的 analysis/screen/screen_v2/screen_v3/backtest/report。

全部任务:
  仅 admin，可看所有任务审计。
```

这样既符合“用户只管理持仓，选股和 AI 分析共享”，也不会泄漏个人持仓相关任务。

#### P1-2 拆分共享分析与个人建议

继续推进 §1.3：

- `analysis_history` 只存共享研究结论。
- 基于用户持仓、成本、仓位生成的操作建议进入 `user_analysis_advice`。
- Analysis 页面展示时分两区：
  - 共享研究结果
  - 我的持仓建议

#### P1-3 统一配置版本与 Analyzer cache key

建议新增 `config_version` 或 `llm_config_hash`：

```text
provider + model + api_key_hash + prompt_version + config_version
```

Analyzer、Screener、LLM client cache 都按这个 key 失效。不要只靠全局 `_analyzer = None` 长期维持正确性。

#### P1-4 收敛 Settings 信息架构

Settings 分区建议：

```text
AI 模型:
  当前 provider、Gemini、Qwen、模型、base_url

数据源:
  Schwab、Polygon、IB、Qwen data source

通知:
  Email、Telegram、Webhook

系统:
  DB path 只读、任务清理、诊断

安全:
  Session、密码、邀请码
```

可写字段继续由 `WRITABLE_SETTING_PATHS` 控制，UI 不展示不可写字段。

#### P1-5 建立验收脚本

建议新增一个轻量 gate：

```bash
pytest -q tests/auth/test_auth_module.py \
  tests/web/test_llm_provider_api.py \
  tests/tasks/test_task_api.py \
  tests/tasks/test_task_manager.py

cd stock_trading_system/web/frontend && npm run build
```

后续每次改 auth/tasks/settings/frontend 都必须跑这组。

### 7.4 可直接复制给实现会话的指令

```text
你是实现工程师。请只修改代码和测试，不改产品目标。当前产品定位是“共享研究库 + 私有持仓”：用户只管理自己的持仓、交易、提醒、个人设置和个人建议；AI 分析、选股、回测、公开报告等研究结果默认共享，但必须记录 created_by 用于审计。

请按 docs/design/product-architecture-optimization-instructions.md 的 §7 执行 P0 修复，优先顺序如下：
1. 修复 /api/settings/llm-provider 调用不存在的 _invalidate_singletons，切换后正确重置 Analyzer。
2. 修复 SettingsPage 前端 schema，只提交后端支持的 dotted path，移除旧 provider/model/api_keys/alerts 聚合提交。
3. 修复任务 scope：前后端统一 mine/shared_research/all，未知 scope 不得绕过过滤；普通用户不能看到其他人的私有任务。
4. 给 GET /api/tasks/<task_id> 加权限校验：共享任务可读，私有任务仅 owner/admin 可读；cancel/delete/retry 仅 owner/admin。
5. 所有直接 tm.submit 的 Web 路由都显式传 created_by=g.user.id，尤其 screen_v2 和 screen_v3。
6. 修复 TaskManager 事件推送，使注入 socketio 的测试 recorder 能收到生命周期事件，同时保留 task_events 持久化和 user room 隔离。
7. 修复测试夹具鉴权：业务 API 测试必须创建用户并登录，测试配置使用临时 STOCK_CONFIG_DIR 和临时 DB。
8. 修复前端 npm run build 的 TypeScript 错误。

验收命令：
pytest -q tests/auth/test_auth_module.py tests/web/test_llm_provider_api.py tests/tasks/test_task_api.py tests/tasks/test_task_manager.py
cd stock_trading_system/web/frontend && npm run build

完成后输出：每个 P0 项的文件变更、测试结果、仍未解决的问题。不要引入 OpenAI/Anthropic/DeepSeek provider，除非后端同时完整支持。
```
