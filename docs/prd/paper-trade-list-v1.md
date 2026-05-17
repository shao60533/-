# 纸面交易列表 v1.0 — 卡片业务化与 ticker 校验

> **版本**: v1.0
> **日期**: 2026-05-16
> **触发**: 用户 2026-05-16 反馈
> **关联设计**: [paper-trade-list-v1.md](../design/paper-trade-list-v1.md)
> **关联既有**: [paper-trade.md](../design/paper-trade.md)（v1.0 基线方案）

---

## 一、问题

`/paper-trade` 列表页今天对用户不友好：

1. **重复 / 拼写错误 ticker 共存**：同一用户同时出现 `SOXL` 与 `SXOL` 两张卡，等价于"数据污染"。
   - 根因：`/api/paper/track` 与 `process_analysis` 入口只做了 `ticker.upper()`，没有任何"这是不是真证券代码"的校验；任何字符串都能落库并新建会话。
   - 现状缓解：[`session_store.list_ticker_sessions_summary`](../../stock_trading_system/strategy/paper_trader/session_store.py#L815) 已有按 `(user_id, ticker)` 的运行时聚合（v1.21 起），但聚合的前提是 ticker 完全相同——typo 形成的不同 ticker 仍是两个 group，仍是两张卡。

2. **卡片字段是内部行话，不是用户能直接做决策的信息**。当前 [`PaperTradeListPage.tsx:181-205`](../../stock_trading_system/web/frontend/src/islands/paper-trade-list/PaperTradeListPage.tsx) 显示：
   - `Plan: 1 active`
   - `Orders: 2 pending · 1 triggered`
   - `Pos: 88.99 shares`
   - `status` 直接显示原始英文 `running` / `completed`
   - 没有总资金、没有总盈亏、没有持仓成本、没有现价、没有浮动盈亏、没有最近成交、没有"下一步等待什么"

3. **盈亏依赖 `cum_pnl_pct`，只来自最近一条 `paper_trade_daily_stats`**。daily_stats 由 EOD job 写入；EOD job 没跑 / 跑失败 / 当天没收盘，列表卡显示的 PnL 就是滞后或缺失的，且没有"数据陈旧"提示。

4. **`ENTRY_INITIAL / entry_add / exit_stop / exit_target / exit_trailing` 这些 order_type 英文常量**在详情页转中文了（[`PaperTradePage.tsx:56-59`](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx)），但列表卡完全没有"最近一次成交是什么 / 下一步等什么触发"这类用户可读说明。

---

## 二、目标（用户语言）

打开 `/paper-trade`，每张卡 8 秒内能回答：

- 这是哪支票？现在追踪中还是已结束？
- 我投了多少？现在值多少？赚还是亏，赚/亏百分之几？
- 我持有多少股？平均成本？现价？这部分浮盈亏多少？
- 最近一次买卖是什么时候、什么价？
- 下一步等什么触发？（哪个价格止损、回踩哪个价位加仓等）

且：
- 同一用户 × 同一 canonical ticker，永远只看到一张卡。
- 任何无效 ticker（拼写错误、非证券代码）都不能创建会话。
- 历史已存在的重复 / typo 会话经过人工确认后被合并，列表展示干净。

---

## 三、需求矩阵（P0 全部必做）

### P0-1 后端 ticker 归一化 + 校验
- 新增 `normalize_and_validate_ticker(raw: str, market_hint: str | None = None) -> str`。
- 三步：`trim → upper → 形态校验 + 市场校验`。
- 形态校验：US 1-5 大写字母；CN 6 位数字 + 可选 `.SH/.SZ`；HK 1-5 位数字。
- 市场校验：调 `DataRouter.get_price(ticker)` 拿一次报价，拿不到价则拒绝（即"市场不存在此代码"）。校验结果短期缓存（5 分钟），避免每次 track 都打数据源。
- 强制入口：`/api/paper/track`、`process_analysis`、`ensure_ticker_session`、`POST /api/paper/sessions`。
- 无效 → HTTP 400 `{"error": "invalid_ticker", "ticker": "...", "reason": "..."}`，不落库。

### P0-2 历史数据合并迁移
- 新建一次性脚本 `scripts/migrate_paper_ticker_dedup.py`：
  - 列出每个 user 下"形态相近"的 ticker 对（编辑距离 ≤ 1 且校验后只有一个有效）。
  - 人工确认 mapping（CLI 提示 y/n）后才执行。
  - 合并 `paper_trade_sessions`（保留最早 id 为 canonical，end_date 取最晚活跃日）、`paper_trade_plans`、`paper_trade_planned_orders`、`paper_trade_trades`、`paper_trade_daily_stats`、`paper_trade_strategy_events`——所有外键 `session_id` 改指 canonical，daily_stats 按 (session_id, date) 唯一去重。
  - 写 audit 行到新表 `paper_trade_merge_audit(merged_at, user_id, from_session_id, into_session_id, from_ticker, into_ticker, reason)`。
  - 干跑模式 `--dry-run` 默认开启，加 `--apply` 才真改。

### P0-3 `/api/paper/tickers` DTO 扩展
新增/确认以下字段（所有金额单位均为 USD float、所有日期 ISO date string）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `start_capital` | number | 会话起始本金 |
| `total_value` | number | 当前净值（cash + 持仓市值） |
| `total_pnl` | number | `total_value - start_capital` |
| `total_pnl_pct` | number | `total_pnl / start_capital` |
| `realized_pnl` | number | 已平仓 trades pnl 之和 |
| `unrealized_pnl` | number | 当前未平仓持仓的 mark-to-market |
| `cash` | number | 当前现金余额 |
| `market_value` | number | 当前持仓市值 |
| `open_position_shares` | number | 当前未平仓股数 |
| `avg_cost` | number \| null | 未平仓持仓的加权平均成本 |
| `last_price` | number \| null | 最近一次能拿到的报价 |
| `last_price_date` | string \| null | 该报价的日期 |
| `stale` | boolean | 当 `last_price_date` 不是今天交易日时 `true`，前端要显眼提示 |
| `latest_execution` | object \| null | 见下 |
| `next_pending_order` | object \| null | 见下 |
| `status_label` | string | 中文状态（"追踪中" / "等待触发" / "已结束" / "失败"） |
| `signal_label` | string \| null | 中文最新信号（"建议买入" / "建议卖出" / "观望"） |

`latest_execution`：
```jsonc
{ "side": "buy" | "sell",
  "shares": 88.99,
  "price": 412.30,
  "date": "2026-05-14",
  "source": "triggered_order" | "trade" | "strategy_event",
  "description": "首次建仓 88.99 股 @ $412.30" }
```

`next_pending_order`：
```jsonc
{ "action": "止损" | "止盈" | "加仓" | "建仓",
  "trigger_text": "跌破 $310 止损",
  "price_or_zone": "310.00" | "370-375",
  "description": "等待触发：跌破 $310 止损（首次设定 2026-05-12）" }
```

### P0-4 PnL fallback 链
1. 有当天 / 昨天的 `daily_stats` → 直接用 `daily_stats.total_value` / `cum_pnl`。
2. `daily_stats` 滞后（最近日期 ≥ 3 个交易日前）或没有 → 用开放 trades + `DataRouter.get_price()` 做 mark-to-market，`stale=false`。
3. 报价也拿不到 → 用最后一次能拿到的报价（可能是几天前），`stale=true` + `last_price_date` 标注真实日期。
4. 三种情况都失败（没 daily_stats、没 trades、没 quote）→ 字段全部 null，前端显示"暂无成交"而非 $0 / 0.00%。

### P0-5 `latest_execution` 来源优先级
1. `paper_trade_planned_orders` `status='triggered'` 最近一条（按 `triggered_date DESC, id DESC`）。
2. fallback 到 `paper_trade_trades` 最近一条（entry 或 exit）。
3. fallback 到 `paper_trade_strategy_events` `action ∈ {open, add, reduce, close, reverse}` 最近一条。
4. 三者都没有 → `null` → 前端显示"暂无成交"。

### P0-6 `next_pending_order` 生成
- 从 `paper_trade_planned_orders` `status='pending'` 取按"优先级"排前一条：
  - 优先级：`exit_stop > exit_target > entry_add > entry_initial > exit_trailing`（用户最关心"会不会被止损"）。
- 把 `order_type` + `trigger_kind` + 价位拼成中文 `description`，规则见设计文档。

### P0-7 前端卡片重构
- 内部英文常量全部移除，改为按 DTO 中已经汉化好的字段渲染（前端 0 转换）。
- 字段缺失全部用业务文案占位（"暂无成交" / "暂无持仓" / "等待下一次 EOD 更新"），**不显示 0 / 0.00% 误导**。
- 320px 不溢出；金额、百分比、最近成交、等待触发 4 块信息均允许换行。
- 详情页本次不动（已 OK），只动列表卡 + 顶部 toolbar。

### P0-8 测试覆盖
- 后端：`tests/web/test_paper_ticker_validation.py`（typo 被拒）、`tests/web/test_paper_tickers_aggregate.py`（扩展 duplicate merge case）、`tests/web/test_paper_tickers_dto.py`（DTO 新字段断言）、`tests/strategy/paper_trader/test_pnl_fallback.py`（daily_stats 缺失 → quote fallback）、`tests/strategy/paper_trader/test_latest_execution_source.py`（来源优先级 4 case）。
- 前端：`PaperTradeListPage.business-labels.test.tsx`（断言 "Plan" / "Orders" / "Pos" / "running" / "ENTRY_INITIAL" 等英文常量在渲染输出中均不出现）。
- 已有的迁移脚本：`tests/scripts/test_migrate_paper_ticker_dedup.py`（干跑模式不会改库；apply 模式合并后 audit 行齐备）。

---

## 四、不做（明确划线）

- **不**动详情页 `/paper-trade/:ticker`（labels 已对、布局已 OK）。
- **不**改 EOD job / 订单引擎 / 计划解析（只读那些表，不动业务逻辑）。
- **不**做新增数据源（quote 一律走现有 `DataRouter`）。
- **不**做 ticker 联想 / autocomplete UI（404 即拒，用户自己重输）。
- **不**做实时推送（卡片仍按 30 秒手动 / 路由切换刷新）。
- **不**改 `paper_trade_sessions` schema（除了为 dedup 加 audit 表）。

---

## 五、验收清单（人工 + 自动）

1. SOXL/SXOL 不再同卡共存：手动制造 typo session + 跑 migrate apply 后，列表只剩一张 SOXL 卡。
2. 提交 `/api/paper/track` ticker=`ZZZZZZ`（虚构）→ 400，DB 无新行。
3. GOOG 持仓中：列表卡显示持仓股数 / 成本 / 现价 / 浮动盈亏 4 项齐全。
4. 有 triggered planned_order 时，"最近"行显示该订单的中文描述。
5. 有 pending planned_order 时，"等待"行显示中文触发条件。
6. 移动端 320 / 375 / 414 三个宽度卡片不溢出，所有字段换行后仍可读。
7. 关掉 EOD job 一周，列表卡仍显示 `stale=true` 提示 + 最后一次 quote 日期，PnL 来自 mark-to-market 而非 0。
8. 全部新增测试 PASS；现有 paper trade 测试 0 回归。

---

## 六、风险

| 风险 | 影响 | 处置 |
|---|---|---|
| `DataRouter.get_price()` 在 track 时增加一次同步调用 | track 端响应延迟 +200-800ms | 5 分钟 LRU 缓存 + 失败时降级为"形态校验通过"（不阻塞），但显示 stale 警示 |
| ticker dedup migration 误合并真实不同票 | 数据丢失 | 强制 `--dry-run` 默认 + 人工逐对 y/n + audit 表可逆查询 |
| 新 DTO 字段被旧 API 缓存吞掉 | 前端拿不到新字段 | 端点路径不变；通过版本字段 `dto_version: 2` 让前端能识别 |
| EOD 缺失时 mark-to-market 与 daily_stats 落库后口径不一致 | 用户看到的数会跳 | 文档明示 "stale" 含义；数值差异 < 1% 时不刷红 |
