# 纸面交易列表 v1.0 — 设计方案

> **版本**: v1.0
> **日期**: 2026-05-16
> **关联 PRD**: [paper-trade-list-v1.md](../prd/paper-trade-list-v1.md)
> **关联基线**: [paper-trade.md](paper-trade.md)（v1.0 引擎与数据模型）
> **预估**: ~14h（后端 6h + 迁移 2h + 前端 3h + 测试 3h），~1500 LOC

---

## § 1 · 既有现状（已确认）

- **per-ticker session 模型已存在** —— `paper_trade_sessions.ticker` + `user_id` 唯一索引（v1.20 起）；新写入走 [`session_store.find_session_by_ticker`](../../stock_trading_system/strategy/paper_trader/session_store.py#L721) → 同 (user, ticker) 复用同 session。
- **lazy 聚合已存在** —— [`list_ticker_sessions_summary`](../../stock_trading_system/strategy/paper_trader/session_store.py#L815) 默认 `group_by_ticker=True`，运行时把同 (user, ticker) 的 sibling sessions 合并成一张卡。**typo 形成的"不同" ticker 仍是不同 group**，所以本方案要解决的是入口验证 + 历史合并。
- **聚合 SQL 已收敛到 4 query** —— 不能再退回 N+1。
- **DTO 缺字段** —— 当前只返 `total_value / cum_pnl_pct / position_shares / counts / sparkline`，详细见 PRD §三。
- **DataRouter.get_price()** —— 已存在多源 fallback（Schwab / Qwen / YFinance / AKShare），含 5 分钟内存 `_price_quote` 缓存。本方案直接复用。
- **frontend 列表卡** —— [`PaperTradeListPage.tsx:137-211`](../../stock_trading_system/web/frontend/src/islands/paper-trade-list/PaperTradeListPage.tsx) 是唯一渲染点。

---

## § 2 · ticker 归一化与校验

### 2.1 新文件 `stock_trading_system/utils/ticker_validator.py`

```python
import re
from dataclasses import dataclass
from time import time
from threading import Lock

@dataclass(frozen=True)
class TickerValidation:
    canonical: str               # 归一化后字符串
    market: str                  # "us" | "cn" | "hk"
    has_quote: bool              # 是否拿到了报价（市场存在性证据）
    quote_price: float | None
    quote_date: str | None
    reason_if_invalid: str | None = None

class InvalidTickerError(ValueError):
    def __init__(self, raw: str, reason: str):
        self.raw = raw
        self.reason = reason
        super().__init__(f"invalid ticker {raw!r}: {reason}")

_US_RE = re.compile(r"^[A-Z]{1,5}$")
_CN_RE = re.compile(r"^(\d{6})(\.(SH|SZ))?$")
_HK_RE = re.compile(r"^\d{1,5}$")     # 港股可在后续支持时再启

# (canonical, market) → (timestamp, TickerValidation); 5 分钟 TTL
_CACHE: dict[tuple[str, str | None], tuple[float, TickerValidation]] = {}
_CACHE_TTL = 300.0
_LOCK = Lock()

def normalize_and_validate_ticker(
    raw: str, market_hint: str | None = None,
    *, allow_quote_failure: bool = False,
) -> TickerValidation:
    """归一化 + 形态校验 + 调一次报价证伪。

    - allow_quote_failure=True 时报价拿不到不抛错（只标 has_quote=False），
      用于 /api/paper/track 这种用户主动 typing 的写入路径需要在网络抖动时
      给用户兜底的场景。默认 False。
    """
    if raw is None or not isinstance(raw, str):
        raise InvalidTickerError(str(raw), "ticker is None or non-string")
    canonical = raw.strip().upper()
    if not canonical:
        raise InvalidTickerError(raw, "empty after trim")

    # 形态判定（推断 market）
    if _CN_RE.match(canonical):
        market = "cn"
        canonical = _CN_RE.match(canonical).group(1)  # 去掉 .SH/.SZ 后缀，统一为 6 位
    elif _US_RE.match(canonical):
        market = "us"
    elif market_hint == "hk" and _HK_RE.match(canonical):
        market = "hk"
    else:
        raise InvalidTickerError(raw, "形态校验失败：不像 US/CN 证券代码")

    key = (canonical, market)
    now = time()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            return cached[1]

    # 报价证伪（仅形态对的才打数据源）
    from stock_trading_system.data.data_router import DataRouter   # 懒加载防循环
    try:
        q = DataRouter().get_price(canonical)   # 假定返回 dict 或 None
    except Exception:
        q = None

    if q and q.get("price"):
        v = TickerValidation(
            canonical=canonical, market=market, has_quote=True,
            quote_price=float(q["price"]),
            quote_date=str(q.get("date") or ""),
        )
    elif allow_quote_failure:
        v = TickerValidation(
            canonical=canonical, market=market, has_quote=False,
            quote_price=None, quote_date=None,
            reason_if_invalid=None,
        )
    else:
        raise InvalidTickerError(
            raw, "市场未找到该代码（报价数据源 0 命中）",
        )

    with _LOCK:
        _CACHE[key] = (now, v)
    return v
```

### 2.2 入口接入点（4 处）

| 入口 | 文件:行 | 改动 |
|---|---|---|
| `POST /api/paper/track` | `web/app.py:3841` | 取 `ticker = request.json["ticker"]` 后**第一行**调 `normalize_and_validate_ticker(ticker)`；异常转 `jsonify({"error": "invalid_ticker", "reason": e.reason}), 400` |
| `process_analysis()` | `strategy/paper_trader/event_executor.py:27` | 同上；analysis 自动 track 时 typo 直接拒绝并写 worker log |
| `ensure_ticker_session()` | `strategy/paper_trader/ticker_session_manager.py:14` | 入参前置校验；非法直接抛 `InvalidTickerError`，上游捕获并 400 |
| `POST /api/paper/sessions` | `web/app.py:3757` | 同上 |

> 不动 `session_store.create_ticker_session` —— 它是底层 DAO，校验放在 service 层，DAO 不再次校验避免双重 round-trip。

---

## § 3 · 历史合并迁移 `scripts/migrate_paper_ticker_dedup.py`

### 3.1 流程

```text
1. SELECT user_id, ticker, COUNT(*) FROM paper_trade_sessions WHERE is_system=0 GROUP BY user_id, ticker;
2. 对每个 user_id，生成 ticker 列表，两两算 Levenshtein 距离 ≤ 1 的对。
3. 对每对 (a, b)：
   - 跑 normalize_and_validate_ticker(a) 和 (b)
   - 如果只有一个 has_quote=True，candidate map: {bad → good}
   - 如果两个都 valid（如 ABC vs ABCD 是两支真票），跳过
4. CLI 打印每对 + 用户输入 y/n/skip
5. --dry-run（默认）只打印；--apply 执行 merge
```

### 3.2 Merge 事务（一对内的 SQL，伪代码）

```python
def merge_into_canonical(db, user_id: int, from_ticker: str, into_ticker: str):
    """把 from_ticker 的所有 session + 子表行迁到 into_ticker 的 canonical session。"""
    with db.transaction():
        from_sessions = SELECT id FROM paper_trade_sessions
                         WHERE user_id=? AND ticker=? AND is_system=0
                         ORDER BY id ASC
        into_sessions = SELECT id FROM paper_trade_sessions
                         WHERE user_id=? AND ticker=? AND is_system=0
                         ORDER BY id ASC
        canonical_id  = into_sessions[0]    # 最早的 into 是真 canonical
        siblings      = into_sessions[1:] + from_sessions
        for sid in siblings:
            UPDATE paper_trade_plans            SET session_id=canonical WHERE session_id=sid
            UPDATE paper_trade_planned_orders   SET session_id=canonical WHERE session_id=sid
            UPDATE paper_trade_trades           SET session_id=canonical, ticker=into_ticker WHERE session_id=sid
            UPDATE paper_trade_strategy_events  SET session_id=canonical WHERE session_id=sid
            # daily_stats 唯一键 (session_id, date) —— 同日重复时保留 max(total_value) 那条
            MERGE paper_trade_daily_stats ON (session_id, date) RESOLVE MAX(total_value)
            INSERT INTO paper_trade_merge_audit (user_id, from_session_id, into_session_id,
                                                  from_ticker, into_ticker, reason, merged_at)
            DELETE FROM paper_trade_sessions WHERE id=sid
```

### 3.3 新表

```sql
CREATE TABLE IF NOT EXISTS paper_trade_merge_audit (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    merged_at        TEXT    NOT NULL,
    user_id          INTEGER,
    from_session_id  INTEGER NOT NULL,
    into_session_id  INTEGER NOT NULL,
    from_ticker      TEXT    NOT NULL,
    into_ticker      TEXT    NOT NULL,
    reason           TEXT             -- "edit_distance_1" / "manual_y" / "duplicate_canonical"
);
CREATE INDEX IF NOT EXISTS idx_pt_audit_user ON paper_trade_merge_audit(user_id, merged_at);
```

> 直接 INLINE 写在 `session_store.py` 的 schema 初始化路径里，与现有 `paper_trade_sessions` 表创建同事务，确保新部署自动建表。

---

## § 4 · DTO v2 — `/api/paper/tickers` 返回

### 4.1 新增 service 层 `paper_trade_list_view.py`

把 DTO 拼装从 `app.py` 路由抽出，单测可独立调：

```python
@dataclass
class TickerCardDTO:
    # identity
    id: int
    ticker: str
    session_ids: list[int]
    # status
    status_label: str          # "追踪中" / "等待触发" / "已结束" / "失败"
    signal_label: str | None   # "建议买入" / "建议卖出" / "观望"
    # money
    start_capital: float
    cash: float
    market_value: float
    total_value: float
    total_pnl: float
    total_pnl_pct: float
    realized_pnl: float
    unrealized_pnl: float
    # position
    open_position_shares: float
    avg_cost: float | None
    last_price: float | None
    last_price_date: str | None
    stale: bool
    # narrative
    latest_execution: LatestExecutionDTO | None
    next_pending_order: NextPendingOrderDTO | None
    # meta
    start_date: str
    last_eod: str | None
    analysis_count: int
    sparkline: list[float]
    dto_version: int = 2
```

### 4.2 status_label / signal_label 映射

| status (DB) | status_label | 触发条件 |
|---|---|---|
| `running` 且有 pending_orders | 等待触发 | DTO 拼装时检测 `pending_orders_count > 0` |
| `running` 且无 pending | 追踪中 | 默认 |
| `completed` | 已结束 | |
| `failed` | 失败 | |
| `cancelled` | 已取消 | |

| signal (latest event) | signal_label |
|---|---|
| BUY / OVERWEIGHT / bullish | 建议买入 |
| SELL / UNDERWEIGHT / bearish | 建议卖出 |
| HOLD / neutral / null | 观望 |

### 4.3 PnL fallback 顺序（实现）

```python
def compute_pnl(session_id, daily_stats_latest, open_trades, quote_fn):
    today_str = today_local_date_str()
    if daily_stats_latest and within_3_trading_days(daily_stats_latest.date, today_str):
        return PnL.from_daily(daily_stats_latest, stale=False)

    # fallback to mark-to-market
    if open_trades:
        ticker = open_trades[0].ticker
        q = quote_fn(ticker)  # 通过 DataRouter
        if q and q.price:
            mv = sum(t.shares * q.price for t in open_trades)
            cost = sum(t.shares * t.entry_price for t in open_trades)
            return PnL.from_mtm(cash, mv, cost, last_price=q.price,
                                 last_price_date=q.date, stale=False)
        # quote 也拿不到 → 用最后一次 daily_stats（如果有）
        if daily_stats_latest:
            return PnL.from_daily(daily_stats_latest, stale=True,
                                   last_price_date=daily_stats_latest.date)

    # 没 trade 也没 daily_stats → 全 null
    return PnL.empty()
```

### 4.4 latest_execution 拼装（优先级链）

```python
def derive_latest_execution(session_ids: list[int]) -> LatestExecutionDTO | None:
    # 1. triggered planned_order
    r = SELECT * FROM paper_trade_planned_orders
        WHERE session_id IN (?) AND status='triggered'
        ORDER BY triggered_date DESC, id DESC LIMIT 1
    if r:
        return LatestExecutionDTO(
            side="buy" if r.order_type.startswith("entry") else "sell",
            shares=r.shares,
            price=r.fill_price or r.trigger_price,
            date=r.triggered_date,
            source="triggered_order",
            description=_zh_order_description(r),  # 见 §4.6
        )
    # 2. paper_trade_trades
    r = SELECT * FROM paper_trade_trades
        WHERE session_id IN (?)
        ORDER BY COALESCE(exit_date, entry_date) DESC, id DESC LIMIT 1
    if r:
        return ...

    # 3. strategy_events
    r = SELECT * FROM paper_trade_strategy_events
        WHERE session_id IN (?) AND action IN ('open','add','reduce','close','reverse')
        ORDER BY event_date DESC, id DESC LIMIT 1
    if r:
        return ...

    return None
```

### 4.5 next_pending_order 拼装（优先级）

```python
ORDER_PRIORITY = {"exit_stop": 5, "exit_target": 4,
                  "entry_add": 3, "entry_initial": 2, "exit_trailing": 1}

def derive_next_pending(session_ids):
    rows = SELECT * FROM paper_trade_planned_orders
           WHERE session_id IN (?) AND status='pending'
    if not rows: return None
    pick = sorted(rows, key=lambda r: (-ORDER_PRIORITY.get(r.order_type, 0),
                                        r.created_at))[0]
    return NextPendingOrderDTO(
        action=_zh_action(pick.order_type),   # 建仓/加仓/止损/止盈
        trigger_text=_zh_trigger(pick.trigger_kind, pick.trigger_price, pick.trigger_zone),
        price_or_zone=_zh_zone(pick.trigger_price, pick.trigger_zone),
        description=_zh_pending_description(pick),
    )
```

### 4.6 中文文案模板

```python
_ZH_ORDER_TYPE = {
    "entry_initial": "首次建仓",
    "entry_add":     "加仓",
    "exit_stop":     "止损",
    "exit_target":   "止盈",
    "exit_trailing": "跟踪止盈",
}
_ZH_ACTION_FOR_PENDING = {
    "entry_initial": "建仓", "entry_add": "加仓",
    "exit_stop": "止损",     "exit_target": "止盈", "exit_trailing": "跟踪止盈",
}

def _zh_order_description(triggered_row) -> str:
    """例：'首次建仓 88.99 股 @ $412.30'"""
    kind = _ZH_ORDER_TYPE[triggered_row.order_type]
    return f"{kind} {triggered_row.shares} 股 @ ${triggered_row.fill_price:.2f}"

def _zh_trigger(kind, price, zone) -> str:
    """例：'跌破 $310' / '回踩 $370-$375' / '突破 $420'"""
    if kind == "stop_below":  return f"跌破 ${price:.2f}"
    if kind == "break_above": return f"突破 ${price:.2f}"
    if kind == "pullback_zone": return f"回踩 ${zone[0]:.2f}-${zone[1]:.2f}"
    return f"价位 ${price:.2f}"

def _zh_pending_description(pending_row) -> str:
    """例：'等待触发：跌破 $310 止损（首次设定 2026-05-12）'"""
    return (f"等待触发：{_zh_trigger(pending_row.trigger_kind, pending_row.trigger_price, pending_row.trigger_zone)}"
            f" {_ZH_ACTION_FOR_PENDING[pending_row.order_type]}"
            f"（首次设定 {pending_row.created_at[:10]}）")
```

---

## § 5 · 前端 `PaperTradeListPage.tsx` 重构

### 5.1 DTO 接口替换
```tsx
interface TickerCardDTO {
  id: number; ticker: string; session_ids: number[]
  status_label: string; signal_label: string | null
  start_capital: number; cash: number; market_value: number
  total_value: number; total_pnl: number; total_pnl_pct: number
  realized_pnl: number; unrealized_pnl: number
  open_position_shares: number; avg_cost: number | null
  last_price: number | null; last_price_date: string | null; stale: boolean
  latest_execution: { side: "buy" | "sell"; shares: number; price: number;
                      date: string; source: string; description: string } | null
  next_pending_order: { action: string; trigger_text: string;
                        price_or_zone: string; description: string } | null
  start_date: string; last_eod: string | null
  analysis_count: number; sparkline: number[]
  dto_version: 2
}
```

### 5.2 卡片结构（新）

```tsx
<Card>
  <CardContent className="pt-5 space-y-3">
    {/* 标题行：ticker · 中文状态 · 中文信号 */}
    <div className="flex items-center gap-2 min-w-0">
      <span className="font-mono font-semibold">{t.ticker}</span>
      <Badge variant={statusVariant(t.status_label)}>{t.status_label}</Badge>
      {t.signal_label && <Badge variant="outline">{t.signal_label}</Badge>}
    </div>

    {/* 资金行 */}
    <div className="space-y-0.5">
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-mono">${fmtMoney(t.total_value)}</span>
        <span className={pnlColor(t.total_pnl)}>
          {fmtSignedMoney(t.total_pnl)} ({fmtSignedPct(t.total_pnl_pct)})
        </span>
      </div>
      <div className="text-[11px] text-muted-foreground">
        起始本金 ${fmtMoney(t.start_capital)} · 现金 ${fmtMoney(t.cash)}
      </div>
    </div>

    {/* 持仓行 */}
    {t.open_position_shares > 0 ? (
      <div className="text-xs space-y-0.5">
        <div>持仓 {t.open_position_shares} 股 · 均价 ${t.avg_cost?.toFixed(2)}</div>
        <div className="text-muted-foreground">
          现价 {t.last_price != null ? `$${t.last_price.toFixed(2)}` : "—"}
          {t.stale && t.last_price_date && (
            <span className="ml-2 text-amber-500">⚠ {t.last_price_date} 行情</span>
          )}
          · 浮盈亏 <span className={pnlColor(t.unrealized_pnl)}>{fmtSignedMoney(t.unrealized_pnl)}</span>
        </div>
      </div>
    ) : (
      <div className="text-xs text-muted-foreground">暂无持仓</div>
    )}

    {/* 最近成交 */}
    {t.latest_execution ? (
      <div className="text-xs">
        <span className="text-muted-foreground">最近 </span>
        {t.latest_execution.date}
        <span className="ml-1">{t.latest_execution.description}</span>
      </div>
    ) : (
      <div className="text-xs text-muted-foreground">暂无成交</div>
    )}

    {/* 等待触发 */}
    {t.next_pending_order ? (
      <div className="text-xs text-amber-500/90">
        等待 · {t.next_pending_order.description}
      </div>
    ) : (
      <div className="text-xs text-muted-foreground">无待触发订单</div>
    )}

    {/* 元信息 */}
    <div className="text-[11px] text-muted-foreground pt-1 border-t border-border/40">
      历史分析 {t.analysis_count} 次 · 起始 {t.start_date}
      {t.last_eod && <span className="ml-1">· EOD {t.last_eod}</span>}
    </div>
  </CardContent>
</Card>
```

### 5.3 helpers
```ts
function statusVariant(label: string): "default" | "muted" | "destructive" {
  if (label === "追踪中" || label === "等待触发") return "default"
  if (label === "失败") return "destructive"
  return "muted"
}
function pnlColor(n: number): string {
  if (n > 0) return "text-[var(--color-accent-green)]"
  if (n < 0) return "text-[var(--color-accent-red)]"
  return "text-muted-foreground"
}
function fmtSignedMoney(n: number): string {
  const sign = n > 0 ? "+" : (n < 0 ? "-" : "")
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {maximumFractionDigits: 0})}`
}
function fmtSignedPct(n: number): string {
  const sign = n > 0 ? "+" : ""
  return `${sign}${(n * 100).toFixed(2)}%`
}
```

### 5.4 严禁出现的英文字面量（前端测试断言这些 0 出现）

`running`、`completed`、`failed`、`cancelled`、`Plan`、`Orders`、`Pos`、`ENTRY_INITIAL`、`entry_add`、`exit_stop`、`exit_target`、`exit_trailing`、`pending`、`triggered`、`shares` 单独出现。

例外（允许出现）：ticker 本身（GOOG / NVDA / SOXL 等大写）、`EOD` 缩写、`$` 货币符号。

---

## § 6 · 测试矩阵

### 后端
| 文件 | case |
|---|---|
| `tests/web/test_paper_ticker_validation.py` | (a) typo `ZZZZZ` → 400；(b) valid `GOOG` → 200；(c) CN `600519.SH` → 200 + canonical=`600519`；(d) 空 / null → 400 |
| `tests/web/test_paper_tickers_aggregate.py`（扩展） | (a) 同 (user, ticker) 多 session 合并成一张卡；(b) typo SXOL 在 dedup 后不再出现；(c) 不同 user 同 ticker 不合并 |
| `tests/web/test_paper_tickers_dto.py` | DTO 含全部 §4.1 字段；status_label 4 种映射；signal_label 3 种映射；stale=true 时 last_price_date 非空 |
| `tests/strategy/paper_trader/test_pnl_fallback.py` | (a) daily_stats 有 → from_daily；(b) daily_stats 缺失 + quote 有 → from_mtm stale=false；(c) 都没 → empty + null 字段 |
| `tests/strategy/paper_trader/test_latest_execution_source.py` | 4 case 对应 §4.4 优先级链 |
| `tests/scripts/test_migrate_paper_ticker_dedup.py` | --dry-run 不改 DB；--apply 后 audit 行齐全；merge 后 daily_stats 同 date 唯一 |

### 前端
| 文件 | case |
|---|---|
| `PaperTradeListPage.business-labels.test.tsx` | 用 mock DTO 渲染，断言所有 §5.4 字面量 `queryByText` 均为 null；status_label / signal_label 中文出现 |
| `PaperTradeListPage.empty-states.test.tsx` | open_position_shares=0 → "暂无持仓"；latest_execution=null → "暂无成交"；next_pending_order=null → "无待触发订单"；total_value=null → 不显示 $0 / 0.00% |

### 集成（Playwright，可选）
`paper-trade-list-business.spec.ts` —— 320 / 414 两宽度截图，断言不溢出。

---

## § 7 · 实施顺序（建议拆 4 个 Code instruction）

| # | 范围 | 预估 |
|---|---|---|
| **CI-1 后端 ticker 验证 + 4 入口接入** | `ticker_validator.py` 新建 + 4 入口加一行调用 + `test_paper_ticker_validation.py` | ~3h |
| **CI-2 DTO 扩展 + service 层 + 5 后端测试** | `paper_trade_list_view.py` 新建 + DTO + PnL fallback + 优先级链 + 5 测试文件 | ~5h |
| **CI-3 迁移脚本 + audit 表 + 干跑测试** | `scripts/migrate_paper_ticker_dedup.py` + schema 加表 + 1 测试 | ~3h |
| **CI-4 前端卡片重写 + 2 vitest** | `PaperTradeListPage.tsx` 重写 + 2 测试 | ~3h |

---

## § 8 · 严格不动

- `paper_trade_sessions / plans / planned_orders / trades / daily_stats / strategy_events` schema（除 audit 表新增）
- 详情页 `PaperTradePage.tsx`、`/api/paper/tickers/<ticker>`、`/api/paper/sessions/*`
- EOD job / event_executor 核心业务逻辑
- DataRouter 实现 / 行情源
- 任何后端测试已有 case（只扩展）

---

## § 9 · 风险与缓解（实施侧）

| 风险 | 缓解 |
|---|---|
| `DataRouter.get_price()` 在 hot path 调用引入延迟 | 5 分钟 LRU + `allow_quote_failure=True` 兜底；前端独立 spinner |
| Levenshtein 距离 1 误判（如 `SOXL` vs `SOXS` 都是真票） | 校验后只有一个 has_quote=True 才提示；y/n 人工确认 |
| `paper_trade_daily_stats` (session_id, date) 主键冲突在 merge 时 | `INSERT OR REPLACE` + 保留 `MAX(total_value)`（更激进口径） |
| 新 DTO 字段过多前端 payload 膨胀 | 总字段 ~22 个 × 平均 50 张卡 → ~1100 数字 + 字符串，<30KB，不优化 |
| dedup 后旧 session_id 在前端被外部链接引用（404） | audit 表保留映射；详情页 fallback：`/paper-trade/:ticker` 优先 ticker 路由而非 session_id |
