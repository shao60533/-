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
