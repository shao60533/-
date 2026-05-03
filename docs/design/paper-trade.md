# 纸面交易（Paper Trade）— AI 效果追踪方案

> **版本**: 1.0
> **日期**: 2026-04-16
> **目标**: 把历史 AI 分析的策略建议当作交易信号流，用真实历史价格回放，观测 AI 的实际效果

---

## 一、核心思路

### 1.1 问题

现在系统里有几十条 AI 分析记录（`analysis_history` 表），每条含：
- `signal`: BUY / SELL / HOLD / OVERWEIGHT / UNDERWEIGHT / ERROR
- `advice_json`: 含 `action` / `entry_price_low` / `entry_price_high` / `stop_loss` / `take_profit` / `suggested_position_pct` / `confidence` / `reasoning`
- `trade_decision`: 完整 Executive Summary（Markdown）

**痛点**：用户看不到"AI 当时说 BUY 的那些票，现在涨了还是跌了"。
**诉求**：自动把信号拼成交易，跑一遍 P&L，跟 SPY 基线比。

### 1.2 方案概览

```
┌────────────────────────────────────────────────────────────────┐
│  Paper Trade Engine (新模块)                                    │
│                                                                 │
│  Input:  analysis_history → advice_json 信号流                  │
│  Sim:    按 advice 的 entry/stop/target + position_pct 模拟下单  │
│  Prices: yfinance 历史日线 (已缓存 LocalCache)                   │
│  Output: 权益曲线 + 交易日志 + 指标 + vs SPY 基线                 │
└────────────────────────────────────────────────────────────────┘
```

**两种模式**：

| 模式 | 描述 | 用途 |
|------|------|------|
| **Replay（回放）** | 取过去 N 天的所有 AI 信号按时间顺序执行 | 看"过去 3 个月 AI 建议如果真做了，赚亏多少" |
| **Live（前向追踪）** | 从今天开始，新 AI 分析自动下单，持续跟踪 | 看"从此刻起跟随 AI 能否跑赢市场" |

---

## 二、交易规则设计

### 2.1 开仓逻辑（Entry）

**触发**：AI 分析记录的 `signal` ∈ {BUY, OVERWEIGHT} 或 `advice.action` == "buy"

**价格**：
- 优先使用 `advice.entry_price_low` / `entry_price_high`
- **回放模式**：若当日收盘价落在入场区间 → 以当日收盘价买入
- **回放模式**：若未落在区间 → 等待区间满足或 N 天超时后放弃（可配置）
- **Live 模式**：次日开盘价直接买入（简化，避免 intraday 复杂性）

**仓位大小**：
- 优先 `advice.suggested_position_pct`（% of 总资产）
- 上限单票仓位（默认 20%），可配置
- 取 `min(suggested_pct, max_single_position_pct, 可用现金/现价)`
- 自动按整股数取整（A 股最小 100 股）

**重复开仓**：同 ticker 未平仓时，忽略新 BUY 信号（避免加仓造成回测失真）

### 2.2 平仓逻辑（Exit）— 四个退出条件，先到先生效

| 优先级 | 条件 | 行为 |
|-------|------|------|
| 1 | **止损**：收盘价 ≤ `advice.stop_loss` | 以止损价或次日开盘价平仓 |
| 2 | **止盈**：收盘价 ≥ `advice.take_profit` | 以止盈价或次日开盘价平仓 |
| 3 | **AI 反转信号**：同 ticker 出现新 SELL/UNDERWEIGHT 分析 | 次日收盘价平仓 |
| 4 | **时间止损**：持有天数 ≥ 配置值（默认 90 天） | 次日收盘价平仓 |

**强制平仓**：Session 结束时（`end_date` 或手动停止），所有持仓按最后一根可用 bar 的收盘价平仓。

### 2.3 账户规则

- **初始资金**：默认 $100,000，可配置
- **手续费**：可选（默认 0，但支持配置 bps）
- **滑点**：可选（默认 0.05%）
- **T+1/T+0**：美股 T+0，A 股 T+1（当日买入不可当日卖出）
- **不允许做空**：只支持多头

### 2.4 配置项（Session Config）

```json
{
    "name": "AI 信号复盘 2026 Q1",
    "mode": "replay",                 // replay | live
    "start_capital": 100000,
    "start_date": "2026-01-01",
    "end_date": "2026-04-15",         // replay 必填，live 为 null
    "filters": {
        "tickers": null,              // null = 全部，或 ["AAPL","NVDA"]
        "signals": ["BUY", "OVERWEIGHT"],
        "min_confidence": null,       // "medium"+
        "markets": ["us"]             // us | cn
    },
    "sizing": {
        "mode": "advice",             // advice | fixed_pct | kelly
        "max_single_pct": 20,
        "fixed_pct": 10               // 仅 sizing.mode=fixed_pct 时用
    },
    "exit_rules": {
        "use_advice_stop": true,
        "use_advice_target": true,
        "time_stop_days": 90,
        "follow_reverse_signal": true
    },
    "cost": {
        "commission_bps": 0,
        "slippage_bps": 5
    },
    "benchmark": "SPY"                // 对标
}
```

---

## 三、数据模型

### 3.1 新增表

```sql
-- 模拟交易 session（一次完整的回放/前向追踪）
CREATE TABLE paper_trade_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,                   -- replay | live
    status TEXT NOT NULL,                 -- pending | running | completed | failed | cancelled
    task_id TEXT,                          -- 关联 tasks 表
    start_capital REAL NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,                         -- replay 必填
    config_json TEXT NOT NULL,             -- 完整 config
    metrics_json TEXT,                     -- 完成后填：{total_return, win_rate, max_dd, sharpe, num_trades, ...}
    benchmark_metrics_json TEXT,           -- SPY 同期对标
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX idx_paper_sessions_created ON paper_trade_sessions(created_at DESC);

-- 每个 session 内的交易记录（每条 = 一次完整的 buy → sell）
CREATE TABLE paper_trade_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    entry_analysis_id INTEGER,             -- 触发开仓的 analysis_history.id
    exit_analysis_id INTEGER,              -- 若因反转信号平仓
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    exit_date TEXT,                         -- 持仓中为 null
    exit_price REAL,
    exit_reason TEXT,                       -- stop | target | reverse_signal | time_stop | session_end
    pnl REAL,
    pnl_pct REAL,
    hold_days INTEGER,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_paper_trades_session ON paper_trade_trades(session_id);

-- 每日权益快照（画净值曲线用）
CREATE TABLE paper_trade_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    total_value REAL NOT NULL,              -- cash + Σ(positions * close)
    cash REAL NOT NULL,
    positions_value REAL NOT NULL,
    benchmark_value REAL,                   -- SPY 等量持仓同期价值
    open_positions INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_paper_equity_session_date ON paper_trade_equity(session_id, date);
```

### 3.2 为什么不复用 `backtest_results` 表

- 回测是**策略级**的（SMA 交叉等无参数算法），只需 equity_curve + metrics
- 纸面交易是**信号级**的，每笔交易来源于某条 AI 分析，需要**可追溯**到原始 analysis_id
- 回放/Live 模式切换需要 status 字段管理生命周期
- Session 需要支持**部分结果**（running 状态下前端可边跑边看）

---

## 四、执行引擎

### 4.1 模块组织

```
strategy/
├── backtest_engine.py         ← 已有
├── paper_trader/              ← 新增
│   ├── __init__.py
│   ├── simulator.py           ← 核心模拟器
│   ├── session_store.py       ← 3 张表的读写
│   ├── metrics.py             ← 指标计算（收益率、胜率、夏普、MDD）
│   └── signal_loader.py       ← 从 analysis_history 取信号流
```

### 4.2 Simulator 流程

```python
class PaperTradeSimulator:
    def run(self, session_id, progress_cb):
        cfg = load_config(session_id)
        signals = SignalLoader.load(cfg.filters, cfg.start_date, cfg.end_date)
        # signals 按 date 升序，含 {analysis_id, ticker, date, signal, advice}

        # 构造逐日日期序列
        dates = business_days(cfg.start_date, cfg.end_date or today())

        portfolio = Portfolio(cash=cfg.start_capital)
        price_cache = PriceCache(cfg.all_tickers)  # 预取所有 ticker 的日线

        for i, d in enumerate(dates):
            # 1. 处理当日信号（可能多条）
            for sig in signals.on_date(d):
                self._handle_signal(portfolio, sig, d, price_cache, cfg)

            # 2. 检查所有持仓的退出条件
            for pos in portfolio.open_positions():
                self._check_exits(pos, d, price_cache, cfg)

            # 3. 写入当日权益快照
            equity = portfolio.total_value(d, price_cache)
            self._save_equity(session_id, d, equity, portfolio)

            # 4. 进度
            progress_cb(int(i / len(dates) * 100), f"模拟 {d}")

        # 5. Session 结束：强制平仓剩余持仓
        self._force_close_all(portfolio, dates[-1], price_cache)

        # 6. 计算最终指标
        metrics = MetricsCalculator.compute(session_id)
        save_metrics(session_id, metrics)
```

### 4.3 预取价格缓存

**关键优化**：一次性拉取所有相关 ticker 的历史 bars（走 LocalCache），避免每天 N 次查询。

```python
class PriceCache:
    def __init__(self, tickers):
        self._bars = {}  # ticker -> pd.DataFrame (date-indexed)
        for t in tickers:
            self._bars[t] = data_helper.get_bars(t, period="2y", interval="1d")

    def close(self, ticker, date):
        df = self._bars.get(ticker)
        if df is None: return None
        # 找最接近的 bar
        return df.asof(date)["Close"]
```

---

## 五、API 设计

### 5.1 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/paper/sessions` | 创建 session（不立即执行） |
| POST | `/api/paper/sessions/:id/run` | 异步提交执行任务，返回 task_id |
| GET | `/api/paper/sessions` | 列表（轻量） |
| GET | `/api/paper/sessions/:id` | 详情（含 metrics + 最后 N 条交易） |
| GET | `/api/paper/sessions/:id/equity` | 权益曲线数据 |
| GET | `/api/paper/sessions/:id/trades` | 交易列表（可分页） |
| POST | `/api/paper/sessions/:id/cancel` | 取消运行中 session |
| DELETE | `/api/paper/sessions/:id` | 删除 session（级联） |

### 5.2 异步任务

注册 `paper_trade` worker 到 TaskManager：

```python
# tasks/workers.py
def make_paper_trade_worker():
    def worker(params, progress_cb):
        from stock_trading_system.strategy.paper_trader import PaperTradeSimulator
        sim = PaperTradeSimulator(get_config())
        result = sim.run(params["session_id"], progress_cb)
        return {
            "result_ref": f"paper_trade_sessions:{params['session_id']}",
            "total_return": result["metrics"]["total_return"],
            "trades": result["metrics"]["num_trades"],
        }
    return worker
```

---

## 六、前端 UI

### 6.1 新增页面：纸面交易

**侧边栏新 Tab**：`<i class="fas fa-vial"></i> 纸面交易` （放在"策略回测"下方）

### 6.2 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  纸面交易 · AI 信号复盘与跟踪                                │
│                                                               │
│  [+ 创建新 Session]        [运行中: 2]  [已完成: 15]          │
├─────────────────────────────────────────────────────────────┤
│  Session 列表 (卡片)                                          │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ AI 信号复盘 2026 Q1        [Replay]  [completed]     │  │
│  │ 2026-01-01 ~ 2026-04-15    38 trades  耗时 12s      │  │
│  │ 收益 +14.3% (vs SPY +9.1%)  胜率 58%  MDD -8.2%     │  │
│  │ ════════════════════════════════  净值曲线缩略图       │  │
│  │                                     [查看详情] [重跑]  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 跟随 AI 前向实盘         [Live]      [running]        │  │
│  │ 2026-04-16 ~ 至今         5 trades    5 open          │  │
│  │ 收益 +2.1% (vs SPY +0.8%)  胜率 --                    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 6.3 创建 Session 表单

```
┌──────────────────────────────────────────┐
│  新建模拟交易                              │
│                                            │
│  名称:    [____________________]           │
│  模式:    ◉ 回放   ○ 前向跟踪              │
│  期间:    [2026-01-01] - [2026-04-15]      │
│  本金:    $ [100,000]                       │
│                                            │
│  信号过滤:                                  │
│  ☑ BUY  ☑ OVERWEIGHT  ☐ HOLD  ☐ SELL      │
│  股票:   ◉ 全部  ○ 指定 [_______]          │
│                                            │
│  仓位策略:                                  │
│  ◉ 按 AI 建议仓位    ○ 固定比例            │
│  单票上限: [20]%                            │
│                                            │
│  退出规则:                                  │
│  ☑ 使用 AI 止损      ☑ 使用 AI 止盈        │
│  ☑ 反转信号退出                             │
│  时间止损: [90] 天                          │
│                                            │
│  成本:                                      │
│  手续费: [0] bps    滑点: [5] bps          │
│                                            │
│             [取消]       [创建并运行]        │
└──────────────────────────────────────────┘
```

### 6.4 Session 详情页

三栏布局：

**左侧**：关键指标
- 总收益率 + 年化（对比 SPY）
- 胜率（X/N）
- 平均持仓天数
- 最大回撤
- 夏普比率
- Trade 总数

**中间**：大图 - ECharts 净值曲线
- 策略曲线（蓝）
- SPY 基准（灰虚线）
- 持仓数副图（堆叠柱）
- 鼠标悬停显示当日详情

**右侧**：交易日志表
- 时间 / Ticker / 方向 / 入场 / 出场 / 盈亏 / 持有天数 / 退出原因
- 每行可点击 → 弹出当时 AI 分析详情（复用 history detail modal）
- 按 Ticker / 退出原因 / 盈亏正负 筛选

**底部**：Per-Ticker 排行榜（哪些股票 AI 选得准）
- Top 5 盈利 / Top 5 亏损
- 命中率 per 信号类型

---

## 七、实施阶段

### Phase 1 — 最小可用（MVP）3 天
1. 数据表建立（3 张）
2. `paper_trader/simulator.py` 核心回放引擎（只支持 replay 模式）
3. `paper_trader/signal_loader.py` 取 analysis_history 信号流
4. `paper_trader/metrics.py` 指标计算
5. API：create / run / list / detail / equity / trades
6. TaskManager 注册 `paper_trade` worker
7. 前端页面骨架（列表 + 详情）

### Phase 2 — 指标增强 2 天
1. SPY 基准对比曲线
2. Per-Ticker 排行
3. 按信号类型命中率
4. 交易详情 → 原 AI 分析跳转
5. 取消 / 重跑功能

### Phase 3 — Live 模式 2 天
1. Live session 随新分析自动开仓（复用现有 analysis_result 事件）
2. Daily cron：每日收盘后检查所有 Live session 的退出条件
3. 实时权益更新推送（WebSocket）

### Phase 4 — 可选增强
- **参数扫描**：同一份信号流跑多组不同 exit_rules → 找最优退出策略
- **Walk-forward 验证**：取 2025 前 6 个月训练参数，后 6 个月验证
- **A/B 对比**：同一时段两个 session 配置并排比较

---

## 八、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 信号粒度 | `advice_json` 而不是 `trade_decision` Markdown | 已结构化，无需 LLM 二次解析 |
| 执行价 | 收盘价（回放）/ 次日开盘价（live） | 避免 intraday 数据复杂性 |
| T+1 | 区分 us / cn 市场 | 符合真实市场约束 |
| 仓位 | 支持 advice / fixed / kelly 三种 | advice 跟 AI 意图，fixed 做对照 |
| 反转平仓 | 可配置，默认开启 | 反映 AI 最新观点 |
| 基准 | SPY（美股）/ 沪深 300（A 股） | 行业标准 |
| 数据源 | LocalCache 已缓存 bars | 速度快，零新依赖 |
| 任务系统 | 复用 TaskManager | 已有进度推送 / 留痕 / 重试 |

---

## 九、非目标（明确不做）

- ❌ 做空 / 保证金 / 期权
- ❌ 实盘下单对接券商 API
- ❌ Intraday / 分钟级模拟
- ❌ 多货币 / 汇率换算
- ❌ 动态再平衡策略（如每月按目标配置调仓）
- ❌ 复杂订单类型（限价/跟踪止损/条件单）

---

## 十、预期产出

### 用户价值
1. **验证 AI 价值**：用户能数字化看"跟随 AI 到底赚不赚钱"
2. **参数调优**：试不同 exit_rules / sizing 找出最优跟随方式
3. **策略信心**：Live 模式持续跑，累积真实效果
4. **反思素材**：哪些信号 AI 准、哪些股 AI 失误 → 反向优化分析

### 技术指标
- **性能**：10 ticker × 90 天回放 < 10 秒（LocalCache 命中情况下）
- **资源**：单 session 数据占用 < 1MB
- **正确性**：同一配置多次运行结果一致（确定性）

---

## 十一、核心文件清单

| 文件 | 新增/修改 | 行数估计 |
|------|-----------|----------|
| `strategy/paper_trader/simulator.py` | 新增 | ~250 |
| `strategy/paper_trader/signal_loader.py` | 新增 | ~80 |
| `strategy/paper_trader/session_store.py` | 新增 | ~150 |
| `strategy/paper_trader/metrics.py` | 新增 | ~120 |
| `tasks/workers.py` | 修改 | +40 |
| `web/app.py` | 修改 | +120 (8 个端点) |
| `web/templates/index.html` | 修改 | +200 (新页面) |
| `web/static/js/app.js` | 修改 | +350 (页面逻辑) |
| `web/static/css/style.css` | 修改 | +150 |

**总估算**：后端约 680 行 + 前端约 700 行 = **~1400 行**

---

*方案 v1.0 结束，以下为 v1.1 补充*

---

# 方案修订 v1.1 — 独立菜单 + 可选留痕 + 个股绑定

> **修订日期**: 2026-04-16
> **动因**: 用户反馈两点
> 1. 菜单上新增独立入口（不合并到"策略回测"）
> 2. AI 分析生成的策略要"留痕"，可选跟踪，且绑定到具体个股

---

## 十二、调整点速览

| # | 原方案 | 修订后 |
|---|--------|--------|
| 1 | 侧边栏"策略回测"下方加 tab | **独立一级菜单**：`<i class="fas fa-vial"></i> 纸面交易` |
| 2 | Session 手动创建，从 history 批量取信号 | **AI 分析页新增"跟踪此策略"按钮**，可选把当前分析加入追踪 |
| 3 | 无追踪记录表 | **新增 `analysis_tracked` 留痕表**，绑定 analysis_id + ticker + session_id |

---

## 十三、个股绑定的留痕机制

### 13.1 数据模型新增

```sql
-- AI 分析策略的追踪记录（留痕）
-- 每一条 = 用户"选择"把某条 AI 分析的策略加入某个 session 跟踪
CREATE TABLE analysis_tracked (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,         -- → analysis_history.id
    ticker TEXT NOT NULL,                 -- 绑定到个股（冗余便于查询）
    session_id INTEGER NOT NULL,          -- → paper_trade_sessions.id
    tracked_at TEXT NOT NULL,             -- 何时加入追踪
    tracked_by TEXT DEFAULT 'user',       -- user | auto（auto-live 模式自动加）
    status TEXT DEFAULT 'pending',        -- pending | executed | skipped | failed
    executed_trade_id INTEGER,            -- 执行后填 paper_trade_trades.id
    skip_reason TEXT,                     -- 为何没执行（资金不足 / ticker 已持仓 / 超出规则等）
    notes TEXT,                            -- 用户备注（可选）
    FOREIGN KEY (analysis_id) REFERENCES analysis_history(id),
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_tracked_analysis ON analysis_tracked(analysis_id);
CREATE INDEX idx_tracked_ticker ON analysis_tracked(ticker, tracked_at DESC);
CREATE INDEX idx_tracked_session ON analysis_tracked(session_id, status);
```

**核心字段说明**：
- **analysis_id**：严格外键到具体分析记录，确保溯源
- **ticker**：冗余存一份便于"该股票被跟踪了多少次"这类查询
- **status**：pending（已登记待执行）/ executed（已开仓）/ skipped（被退出规则挡住）/ failed（数据异常）
- **executed_trade_id**：成功执行后回填，可双向跳转到交易详情

### 13.2 交互流程（UX）

#### 场景 A：AI 分析完成后可选跟踪

```
AI 分析完成（AAPL，信号 BUY，advice.entry=$260-262）
                   ↓
┌─────────────────────────────────────────────────────┐
│  [信号卡]   BUY   置信度 78%                          │
│  [策略建议] entry $260-262 · stop $245 · target $280 │
│                                                       │
│  ┌─────────────────────────────────────────────┐    │
│  │  💡 跟踪此策略                                │    │
│  │  把这条建议加入纸面交易，观察实际效果         │    │
│  │                                              │    │
│  │  跟踪到 Session:                             │    │
│  │  [AI 前向追踪 · Live ▾]                      │    │
│  │  ( + 新建 session )                          │    │
│  │                                              │    │
│  │  备注（可选）:                                │    │
│  │  [__________________________]                │    │
│  │                                              │    │
│  │        [取消]       [确认跟踪]               │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

#### 场景 B：分析历史页可回溯跟踪

在 "分析记录" 页的每条记录右上角加 **🔖 追踪徽章**：
- 未追踪：灰色"跟踪此策略"按钮
- 已追踪：绿色徽章 "已加入 Session #3" → 点击跳转 session

#### 场景 C：自动追踪（Live Session 的"跟随模式"）

Live session 创建时可选 `auto_track=true`：
- 每当 `analysis_result` WebSocket 事件触发（且信号匹配 filter）
- 自动 INSERT 一条 `analysis_tracked` 记录
- 用户在 session 详情页能看到"自动追踪"的 tag

### 13.3 执行管道（tracked → trade）

```
analysis_tracked (status=pending)
    ↓ (session.run() 或实时调度)
PaperTradeSimulator 读取该 session 的所有 pending tracked 记录
    ↓ (按 tracked_at 排序)
对每条评估:
  ├─ 资金足够？开仓规则允许？（checks）
  │   ├─ 是 → 执行 buy → 更新 status=executed + executed_trade_id
  │   └─ 否 → 更新 status=skipped + skip_reason
  └─ 继续下一条
```

### 13.4 留痕视图（Audit Trail）

新建 `/api/paper/audit/ticker/:ticker` 端点，返回某只股票的所有追踪历史：

```json
[
    {
        "tracked_at": "2026-04-16 14:32",
        "analysis_id": 42,
        "analysis_date": "2026-04-16",
        "signal": "BUY",
        "advice": {...},
        "session_id": 3,
        "session_name": "AI 前向追踪",
        "status": "executed",
        "executed_trade_id": 15,
        "trade_result": {
            "entry_price": 261.5,
            "exit_price": 279.2,
            "pnl_pct": 6.77,
            "hold_days": 18
        }
    },
    {
        "tracked_at": "2026-03-12 10:15",
        "analysis_id": 31,
        "signal": "BUY",
        "status": "executed",
        "trade_result": { "pnl_pct": -2.3, "hold_days": 90 }
    }
]
```

**UI 呈现**：个股分析详情页新增 "此股追踪历史" 时间线：
```
AAPL 追踪时间线
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 2026-04-16 BUY → Session #3 → +6.77% (18天)
🔴 2026-03-12 BUY → Session #1 → -2.30% (90天 time-stop)
🟡 2026-02-28 HOLD → 未跟踪
━━━━━━━━━━━━━━━━━━━━━━━━━━━
命中率: 1/2 = 50%  · 累积: +4.47%
```

---

## 十四、API 新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/paper/track` | 创建追踪记录 body `{analysis_id, session_id, notes?}` |
| DELETE | `/api/paper/track/:id` | 取消追踪（仅 status=pending 可取消） |
| GET | `/api/paper/track/by_analysis/:analysis_id` | 查询某条分析的所有追踪 |
| GET | `/api/paper/track/by_ticker/:ticker` | 查询某只股票的完整追踪时间线 |
| GET | `/api/paper/track/by_session/:session_id` | 查询某 session 的所有追踪记录（含 status） |

---

## 十五、菜单新增

`web/templates/index.html`：

**桌面侧边栏**（System 分组上方，Portfolio 分组内）：
```html
<li class="nav-item">
    <a class="nav-link" href="#" data-page="paper">
        <i class="fas fa-vial"></i> 纸面交易
    </a>
</li>
```

**移动 More Sheet**：
```html
<a href="#" class="more-sheet-item" data-page="paper" onclick="closeMoreSheet()">
    <i class="fas fa-vial"></i><span>纸面交易</span>
</a>
```

**AI 分析页内**：信号卡下方按需展示"跟踪此策略"按钮（只在 `signal ∈ {BUY,OVERWEIGHT,SELL,UNDERWEIGHT}` 时出现）

**分析历史页**：每条记录行末尾加追踪状态徽章

---

## 十六、实施顺序（调整）

### Phase 1 — MVP 独立模块（3 天）
1. ✅ 3 张核心表 + 新增 `analysis_tracked` 表（共 4 张）
2. ✅ `strategy/paper_trader/` 核心引擎（replay 模式）
3. ✅ 后端 API：sessions + tracking 共 11 个端点
4. ✅ TaskManager 注册 `paper_trade` worker
5. ✅ 前端独立页面 `page-paper`（菜单新增）
6. ✅ AI 分析结果页"跟踪此策略"按钮

### Phase 2 — 留痕增强（2 天）
1. ✅ 分析历史页追踪徽章
2. ✅ 个股追踪时间线（`/api/paper/track/by_ticker/:ticker`）
3. ✅ Session 详情页展示 tracked 记录状态

### Phase 3 — Live 模式（2 天）
1. ✅ Live session + auto_track 自动追踪
2. ✅ 每日收盘 cron 检查退出条件
3. ✅ 实时权益 WS 推送

### Phase 4 — 可选增强
- 参数扫描、Walk-forward、A/B 对比（不变）

---

## 十七、最终 Table 清单

| 表名 | 用途 |
|------|------|
| `paper_trade_sessions` | Session 配置 + 最终 metrics |
| `paper_trade_trades` | 每笔完整 buy→sell 交易 |
| `paper_trade_equity` | 每日权益快照 |
| **`analysis_tracked`** | **AI 分析的追踪留痕（新增）** |

---

## 十八、核心文件清单（更新）

| 文件 | 新增/修改 | 行数估计 |
|------|-----------|----------|
| `strategy/paper_trader/simulator.py` | 新增 | ~280 |
| `strategy/paper_trader/signal_loader.py` | 新增 | ~100 |
| `strategy/paper_trader/session_store.py` | 新增 | ~180 |
| `strategy/paper_trader/metrics.py` | 新增 | ~120 |
| `strategy/paper_trader/tracking.py` | **新增** | **~120** |
| `tasks/workers.py` | 修改 | +40 |
| `web/app.py` | 修改 | +180 (11 端点) |
| `web/templates/index.html` | 修改 | +260 |
| `web/static/js/app.js` | 修改 | +450 |
| `web/static/css/style.css` | 修改 | +180 |

**总估算**：后端约 840 行 + 前端约 890 行 = **~1730 行**

---

*v1.1 修订结束，以下为 v1.2 补充*

---

# 方案修订 v1.2 — 全量自动追踪

> **修订日期**: 2026-04-16
> **动因**: 用户反馈"只要有过 AI 分析且有结果的都要追踪"

---

## 十九、核心变化：从 opt-in 变 auto-all

### 原 v1.1 逻辑
- 用户**主动**点击"跟踪此策略"才写入 `analysis_tracked`
- 会遗漏很多分析，追踪覆盖率不完整

### 新 v1.2 逻辑
- **所有** `signal != ERROR` 的分析完成时，**自动**写入默认追踪 session
- UI 的"跟踪此策略"按钮保留，但作用变成：**加入额外 session**（如用户想同一分析跑多个策略对比）
- 前端始终展示"已自动追踪"状态

---

## 二十、默认追踪 Session

### 20.1 设计

系统初始化时创建一个**内置 session**（不可删除）：

```json
{
    "id": 1,
    "name": "AI 分析自动追踪（默认）",
    "mode": "live",
    "auto_track": true,
    "is_system": true,              // 系统 session 标记，前端不允许删除
    "start_capital": 100000,
    "start_date": "<首次启动日期>",
    "end_date": null,               // live 永不结束
    "filters": {
        "signals": ["BUY", "OVERWEIGHT", "SELL", "UNDERWEIGHT", "HOLD"],
        "tickers": null,            // 所有 ticker
        "markets": ["us", "cn"]
    },
    "sizing": { "mode": "advice", "max_single_pct": 20 },
    "exit_rules": { "use_advice_stop": true, "use_advice_target": true, "time_stop_days": 90, "follow_reverse_signal": true },
    "cost": { "commission_bps": 0, "slippage_bps": 5 }
}
```

### 20.2 自动追踪钩子

在 `web/app.py` 的分析完成路径（`run_analysis` 线程的 try 末端，紧接 `save_analysis` 之后）插入：

```python
# 分析成功入库后自动追踪
if result and result.signal != "ERROR":
    try:
        tracking.auto_track(
            analysis_id=new_analysis_id,
            ticker=ticker,
            signal=result.signal,
            advice=advice,  # strategy advice dict
        )
    except Exception as e:
        logger.warning("Auto-track failed (non-fatal): %s", e)
```

`tracking.auto_track(...)` 的职责：
1. 找到所有 `auto_track=true` 的 active session（至少默认 session）
2. 对每个 session 写入一条 `analysis_tracked` 记录
3. 根据 signal 类型决定后续执行路径：
   - `BUY`/`OVERWEIGHT` → 下个交易日执行开仓（status 暂为 pending）
   - `SELL`/`UNDERWEIGHT` → 若持有则平仓，否则 status=skipped（reason=no_position_to_sell/no_short）
   - `HOLD` → status=no_action（仅留痕，不执行）
   - `ERROR` → 不进入（前置过滤）

### 20.3 失败分析不追踪

前端"分析记录"页现已支持 ERROR 标签的记录（之前 Bug 修复时加的）。这类记录：
- `signal == "ERROR"`
- 不产生 advice_json
- **直接跳过追踪**（不写 `analysis_tracked`）
- UI 上显示"❌ 失败，不参与追踪"

---

## 二十一、UI 调整

### 21.1 AI 分析结果页

**原设计**：醒目的"跟踪此策略"按钮
**新设计**：

```
┌─────────────────────────────────────────────────────┐
│  [信号卡]   BUY   置信度 78%                          │
│  [策略建议] entry $260-262 · stop $245 · target $280 │
│                                                       │
│  🔖 已自动加入「AI 分析自动追踪（默认）」            │
│  （status: pending → 下一交易日开仓）                 │
│                                                       │
│  [+ 同时加入其他 session]   [查看追踪详情]           │
└─────────────────────────────────────────────────────┘
```

**说明徽章**位于信号卡下方，明确告知用户已自动追踪。两个次要按钮：
- 加入其他 session（打开 session 选择 modal）
- 查看追踪详情（跳转到 session 详情页，定位到该 tracked 记录）

### 21.2 分析记录页

每行记录末尾显示**追踪微型状态**：

| signal | 追踪状态显示 |
|--------|-------------|
| BUY (已执行) | 🟢 +6.77% (18天) |
| BUY (持仓中) | 🔵 持仓 3天 (当前 +1.2%) |
| SELL (执行) | 🔴 -2.30% |
| HOLD | ⚪️ 仅记录 |
| ERROR | ❌ 未追踪 |

点击跳转到 session 详情。

### 21.3 分析详情弹窗

在弹窗底部加 **"追踪详情"** 折叠区：
- 已加入的 session 列表（默认 session + 用户手动添加的）
- 每个 session 的当前 status + 交易结果（若已执行）

---

## 二十二、个股追踪时间线（强化）

由于现在**每条非 ERROR 分析都有追踪记录**，`/api/paper/track/by_ticker/:ticker` 数据会很完整。

新增 UI：在 AI 分析页输入 ticker 后，除了加载 K 线/基本面/新闻外，**自动加载该股的追踪时间线**：

```
AAPL 历史分析追踪（最近 10 条）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 2026-04-16 BUY  → +6.77% (18天)  default session
🔴 2026-03-12 BUY  → -2.30% (90天 time-stop)
⚪️ 2026-03-05 HOLD → 仅记录
🟢 2026-02-28 BUY  → +12.4% (25天)
🔴 2026-02-01 BUY  → -5.1% (反转信号)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUY 命中率: 2/4 = 50%   累积 +11.77%
HOLD 占比: 1/5 = 20%
```

这直接反馈 **AI 对这只股票的历史"说中率"**，帮用户建立对 AI 判断的信任。

---

## 二十三、回放模式的调整

**回放模式行为不变**：用户手动创建一个新 session，从 `analysis_history` 选时间段和过滤条件，一次性跑。

**关键理解**：默认追踪 session 是 live 模式；用户回放是**另创 session**，不影响默认 session 的持续追踪。

---

## 二十四、实施顺序微调

### Phase 1 — MVP（3 天，无变化）
+ 新增：系统默认 session 初始化（首次启动或 migration 时创建）
+ 新增：`tracking.auto_track()` 钩子在分析入库后调用

### Phase 2 — 留痕增强（2 天）
+ 新增：分析页追踪徽章实时显示
+ 新增：ticker 历史追踪时间线自动加载

### Phase 3 — Live 模式（2 天，核心流程不变）
+ 调整：所有 live session 都走自动追踪路径，不只是用户勾选的

### Phase 4 — 可选增强（不变）

---

## 二十五、v1.2 数据量评估

- 系统假设每日产生 ~5-10 条 AI 分析
- 每条分析生成 1 条 `analysis_tracked` 记录（默认 session）
- 一年 ≈ 2000-3600 条记录 → < 1MB 存储
- `paper_trade_trades` 仅有 signal ∈ {BUY, SELL} 的子集会产生真实 trade 记录

**结论**：全量自动追踪对存储/性能无压力。

---

## 二十六、最终汇总

| 改动层级 | 内容 |
|----------|------|
| **菜单** | 独立一级 "纸面交易" |
| **追踪粒度** | 所有非 ERROR 分析自动进入默认 session（+ 用户可选加入额外 session） |
| **留痕内容** | analysis_id / ticker / session_id / status / trade 结果 / 时间 |
| **UI 反馈** | 分析页徽章 / 历史页状态 / 个股时间线 / session 详情 |
| **核心价值** | **100% 覆盖率** — 没有"漏追踪"的分析，AI 效果可量化评估 |

---

## 二十七、v1.3 修订（2026-04-19）—— UX / 数据 surface 5 处修正

上线后实战反馈发现 5 处影响用户校验 AI 决策的问题。本章节是对既有功能的 **UX + 数据 surface 修订**，不引入新功能，不改流水线主体。

### 27.1 问题诊断

| # | 症状 | 根因位置 | 类别 |
|---|---|---|---|
| F1 | 同一只股票反复出现内容完全相同的 Plan 卡（#69 当前 / #49 已失效 内容字段一致） | [session_store.py:896-903](../../stock_trading_system/strategy/paper_trader/session_store.py) `save_plan` 无 dedup | 数据污染 |
| F2 | 底部 "AI 原文" 永远是固定文案（BUY→"AI 信号看多，建议建仓"）| [strategy_engine.py:100-122](../../stock_trading_system/strategy/strategy_engine.py) 按 signal 值返回硬编码句子 | 数据错位 |
| F3 | "核心论点" 永远显示 "regex 解析" 字样 | [plan_parser.py:253](../../stock_trading_system/strategy/paper_trader/plan_parser.py) 将 fallback label 写为内容 | 数据错位 |
| F4 | 日度数据图表视觉粗糙 | [app.js:4518-4549](../../stock_trading_system/web/static/js/app.js) 基础 ECharts line+bar 配置 | UX 视觉 |
| F5 | "时间轴" 与 "策略历史" 两 tab 空态下内容重合，用户误判为重复功能 | tab 分工未在 UI 呈现 | UX 结构 |

### 27.2 修法

#### F1 · Plan 内容指纹 dedup

**改**：[session_store.py](../../stock_trading_system/strategy/paper_trader/session_store.py) `save_plan()`

```python
def _plan_fingerprint(plan: Plan) -> str:
    # 稳定排序 + hashlib.sha1（stdlib，不装新库）
    payload = json.dumps({
        "entry_low": plan.entry_low, "entry_high": plan.entry_high,
        "stop_loss": plan.stop_loss, "take_profit": plan.take_profit,
        "tiers": sorted([(o.sequence, o.trigger, o.target_pct) for o in plan.orders]),
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()

def save_plan(self, session_id, plan, analysis_id):
    fp = _plan_fingerprint(plan)
    current = self._get_active_plan(session_id, plan.ticker)
    if current and current.fingerprint == fp:
        # 指纹一致 → 仅累加重复确认
        self._db.execute("""
            UPDATE paper_trade_plans
            SET reconfirmed_count = reconfirmed_count + 1,
                reconfirmed_at    = CURRENT_TIMESTAMP,
                analysis_ids      = json_insert(COALESCE(analysis_ids,'[]'), '$[#]', ?)
            WHERE id = ?
        """, (analysis_id, current.id))
        return current.id
    # 指纹不同 → 老路径（supersede + insert）
    ...
```

**Schema 迁移**（幂等，带 `--dry-run` 和自动备份）：

```sql
ALTER TABLE paper_trade_plans ADD COLUMN fingerprint TEXT;
ALTER TABLE paper_trade_plans ADD COLUMN reconfirmed_count INTEGER DEFAULT 1;
ALTER TABLE paper_trade_plans ADD COLUMN reconfirmed_at TEXT;
ALTER TABLE paper_trade_plans ADD COLUMN analysis_ids TEXT;  -- JSON array
CREATE INDEX ix_plans_session_ticker_fp ON paper_trade_plans(session_id, ticker, fingerprint);
UPDATE paper_trade_plans SET analysis_ids = json_array(analysis_id)
 WHERE analysis_ids IS NULL;
```

**UI**：Plan 卡右上角 `重复确认 × 3 · 最新 2026-04-19` 小字（仅当 reconfirmed_count > 1 时显示）。

#### F2 · "AI 最终决策" 真·原文

**改**：[web/app.py:1377-1382](../../stock_trading_system/web/app.py) `/api/paper/tickers/<ticker>` 返回的 `latest_trade_decision` 已存在但前端未用；改前端。

- 板块名：`AI 原文` → **`AI 最终决策`**
- 头部：`关联分析 #<id> · <created_at>`，点击跳 `/page-analysis?id=<id>`
- 内容：`analysis_history.trade_decision` **全文 Markdown 渲染**
- [strategy_engine.py:100-122](../../stock_trading_system/strategy/strategy_engine.py) 的 signal→文案映射**保留**，仅用于任务中心通知/徽章场景

#### F3 · 显式抽取 `executive_summary`

**复用原则 L1**：用 `ChatOpenAI.with_structured_output(ExecutiveSummary)` 抽出，**禁止**自写 JSON 解析或正则（见 [engineering-principles §4 反模式](../engineering-principles.md#4-反模式)）。

1. [agents/analyzer.py](../../stock_trading_system/agents/analyzer.py) 生成分析最后追加一步：

```python
class ExecutiveSummary(BaseModel):
    thesis: str = Field(description="2-3 句执行总结，明确 signal + 关键触发条件 + 风险点")

summary_chat = chat_model.with_structured_output(ExecutiveSummary)
exec_sum = summary_chat.invoke([
    SystemMessage(content="你是投资决策总结者，根据下面完整分析提炼 2-3 句执行总结"),
    HumanMessage(content=trade_decision_full_text),
])
result.executive_summary = exec_sum.thesis
```

2. [database.py](../../stock_trading_system/portfolio/database.py) `analysis_history`：

```sql
ALTER TABLE analysis_history ADD COLUMN executive_summary TEXT;
```

3. [plan_parser.py:253](../../stock_trading_system/strategy/paper_trader/plan_parser.py)：
- `thesis` 改为直接读 `analysis_history.executive_summary`
- 空值时 `thesis = None`（不再写字面量 `"regex 解析"`）
- **彻底删除** `"regex 解析"` 字符串

4. UI 空值时显示占位 `（执行总结生成失败，查看完整分析 ›）` + 链接

#### F4 · 日度数据图表重配

**复用**：继续用 ECharts（L0，已装），仅改配置。

```js
// app.js 重写 _renderPtvDailyChart
option = {
  grid: [
    { top: '8%',  height: '60%', left: '8%', right: '4%' },   // 净值区
    { top: '74%', height: '18%', left: '8%', right: '4%' },   // 迷你 pnl
  ],
  xAxis: [
    { type: 'category', gridIndex: 0, boundaryGap: false, axisLabel: { show: false } },
    { type: 'category', gridIndex: 1, boundaryGap: true },
  ],
  yAxis: [
    { type: 'value', gridIndex: 0, scale: true, splitLine: { lineStyle: { opacity: 0.08 } } },
    { type: 'value', gridIndex: 1, splitLine: { show: false } },
  ],
  visualMap: [{
    type: 'piecewise', seriesIndex: 1, show: false,
    pieces: [{ gt: 0, color: 'var(--accent-green)' }, { lte: 0, color: 'var(--accent-red)' }],
  }],
  series: [
    {
      name: '净值', type: 'line', smooth: true, showSymbol: false,
      gridIndex: 0, xAxisIndex: 0, yAxisIndex: 0,
      areaStyle: { opacity: 0.15 },
      markPoint: { data: [{ type: 'max' }, { type: 'min' }] },
      markArea: { /* drawdown_pct < 0 的区段半透明红色阴影 */ },
      data: totalValues,
    },
    {
      name: '当日盈亏', type: 'bar',
      gridIndex: 1, xAxisIndex: 1, yAxisIndex: 1,
      data: dailyPnls,
    },
  ],
  tooltip: {
    trigger: 'axis', axisPointer: { type: 'cross' },
    formatter: (p) => `${p[0].axisValue} · ${fmt(p[0].value)} · ${fmt(cumPct)}% · DD ${fmt(dd)}%`,
  },
};

// 移动端（≤575.98px）隐藏 grid[1]，净值全高
if (matchMedia('(max-width: 575.98px)').matches) {
  option.grid = [{ top: '8%', height: '84%', left: '10%', right: '4%' }];
  option.series = option.series.slice(0, 1);
}
```

参考：ECharts 官方 `stock-dashboard` example、TradingView / Robinhood 视觉风格。

#### F5 · 合并"时间轴 + 策略历史"为单 tab「执行记录」

**根因**：两 tab 分别绑 event-level（`paper_trade_strategy_events`）和 plan-level（`paper_trade_plans + planned_orders`）两张表，空态下内容错觉重合。

**改**：
- `#ptv-tabs` 4 tab → 3 tab：`当前策略 / 执行记录 / 日度数据`
- 新 tab `#ptv-tab-records` 内部两视图，用 [mobile-optimization](./mobile-optimization.md) `.chip-row` 切换：
  - **按 Plan**（默认）：复用现有 `_renderPtvHistory()`（[app.js:4433](../../stock_trading_system/web/static/js/app.js)），每个 plan 卡片底部加可展开区嵌入该 plan 相关的 events（按 `events.analysis_id ∈ plan.analysis_ids` 过滤）
  - **按 Event**：复用现有 `_renderPtvTimeline()`（[app.js:4477](../../stock_trading_system/web/static/js/app.js)）原样
- 后端 API 零改动（`/api/paper/tickers/<ticker>` 已同时返回 `events` 和 `plan_history`）
- 旧 DOM id `ptv-tab-timeline` / `ptv-tab-history` 移除

**复用收益**：两个 render 函数 0 修改，只加一个 ~30 LOC 的 view-switcher + 一个 plan→events 过滤辅助函数。

### 27.3 § 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md) L0→L4 阶梯：

**L0 项目内复用**：
- [session_store.py](../../stock_trading_system/strategy/paper_trader/session_store.py) `save_plan` 现有事务/supersede 逻辑（F1 仅加前置 dedup 检查）
- [web/app.py `/api/paper/tickers/<ticker>`](../../stock_trading_system/web/app.py) 已返回 `trade_decision` 和 `events` + `plan_history`（F2/F5 无后端改动）
- [app.js `_renderPtvHistory` / `_renderPtvTimeline`](../../stock_trading_system/web/static/js/app.js) 保留不动（F5 仅包一层 view switcher）
- [mobile-optimization](./mobile-optimization.md) `.chip-row` / `form-row-mobile`（F5 视图切换 + F4 移动端适配）

**L1 依赖库**：
- `hashlib.sha1`（stdlib）—— F1 指纹
- `ChatOpenAI.with_structured_output()` —— F3 抽取，已在 [screener-v3 v1.1](./screener-v3.md) 引入
- ECharts（已装）+ `visualMap.piecewise` + `markArea` —— F4 图表
- 现有 Markdown 渲染器（若项目未装则加 `markdown-it`）

**L2/L3**：
- ECharts `stock-dashboard` 官方示例（F4 布局灵感，不 copy 代码）
- TradingView 双栅格风格（F4 视觉参考）

**L4 必须自写**：
- F1 dedup 前置检查（~20 LOC）
- F5 view switcher + plan→events 过滤（~40 LOC）
- F4 ECharts 配置对齐项目 CSS tokens（~80 LOC 纯配置）
- 总计 ~140 LOC 胶水，0 业务逻辑新增

### 27.4 迁移 & 回滚

**迁移脚本** `migrations/paper_trade_v1_3.py`（幂等、`--dry-run`、自动备份）：
1. 备份 `portfolio.db → portfolio.db.pre-v1_3.bak`
2. 按 F1 / F3 Schema 变更执行 ALTER
3. 为现存 `paper_trade_plans` 行计算 fingerprint 并回填
4. 汇总输出迁移了 N 行、计算了 M 个指纹

**回滚**：`mv portfolio.db.pre-v1_3.bak portfolio.db`；代码 `git revert`。

### 27.5 实施顺序

F1 → F3（F3 需先跑一次全库回填 executive_summary，成本 ~¥5）→ F2 → F5 → F4。每项独立 commit，独立回滚单位。

---

*v1.2 修订结束 — 全量自动追踪。等待确认后开始 Phase 1 实施*


---

## 二十八、v1.4 修订（2026-05-04）—— 个股详情页结构化决策同步

> **背景**：用户截图 `/paper-trade/MSFT`（v1.18 R-fix-12 路由后）暴露三处与 [analysis-rendering v1.0+](./analysis-rendering.md) 结构化卡片体系脱节的旧渲染：
> 1. **「当前策略」卡** 仍展示 `plan.thesis`（来自 [plan_parser.py](../../stock_trading_system/strategy/paper_trader/plan_parser.py) regex 正则解析） + `Plan #x · 分析 #N · YYYY-MM-DD HH:MM · regex · 3-6个月` 元信息底栏 + 7 档评级 Badge。表面看起来"有结构"，实际是 v1.3 F3 引入 `with_structured_output` 抽取列**之前**的 fallback 路径，与新 OverviewCard / Decision banner / Executive Summary 视觉**完全不一致**。
> 2. **「AI 最终决策」卡** 是大段 raw markdown（`whitespace-pre-wrap` 渲染 `latest_trade_decision`），与 [/analysis/&lt;id&gt;](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 详情页 8 tab 结构化卡片（OverviewCard / DecisionCard 等）形成**双套**视觉语言。
> 3. **「执行记录」按 Plan tab** 每行都是 `Plan #id` + thesis + `<details>` 折叠 markdown，定位为「策略历史」；但用户心智里这是 **「该股票的 AI 分析历史」**——希望每行能直接跳转到对应 `/analysis/<id>` 看完整 8 tab。

### 28.1 § 现状诊断

#### 28.1.1 三处旧渲染源头追踪

| 位置 | 当前实现 | 行号 | 数据源 | 问题 |
|------|----------|------|--------|------|
| 当前策略卡 | `<Badge>{plan.rating}</Badge>` + `{plan.thesis}` + 元信息底栏 | [PaperTradePage.tsx:155-180](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) | `data.active_plan`（store.get_active_plan，**不带 rendering_json**） | regex 解析的 thesis 颗粒度粗，与 OverviewCard 8 tab 体系脱节，元信息暴露 `parse_method=regex` 实现细节 |
| AI 最终决策卡 | `<div whitespace-pre-wrap>{data.latest_trade_decision}</div>` | [PaperTradePage.tsx:240-256](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) | `data.latest_trade_decision`（`analysis_history.trade_decision` 原文 markdown） | raw markdown 与新 8 tab 卡视觉双轨；用户已习惯结构化展示 |
| 执行记录·按 Plan | `<PlanHistory plans={data.plan_history}>` 每行 Plan #id + thesis + `<details>` markdown | [PaperTradePage.tsx:432-466](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) | `data.plan_history[]`（每条带 `trade_decision` raw markdown） | 用户心智 = 该股 AI 分析历史；缺跳详情页入口 |

#### 28.1.2 后端数据 surface 状态

- [`api_paper_ticker_detail`](../../stock_trading_system/web/app.py#L2933) 当前返回字段中：
  - `active_plan` ← `store.get_active_plan(s_id)` —— 仅 `paper_trade_plans` 行字段（id / signal / rating / thesis / parse_method / holding_months / raw_summary / created_at / analysis_id），**无 rendering_json**
  - `latest_trade_decision` ← `_db.get_analysis_by_id(latest_event.analysis_id).trade_decision` —— raw markdown 字符串
  - `plan_history[].trade_decision` ← 同上，逐条贴 raw markdown
  - `latest_advice` ← `_db.get_user_advice(uid, analysis_id)` —— **per-user 私有，正确**，不动
- `analysis_history` 表已在 [analysis-rendering v1.0](./analysis-rendering.md#1-数据层) / [paper-trade v1.3 F3](#273-§-复用--reuse) 引入两列：
  - `rendering_json` —— 8 tab 结构化 JSON（含 `summary: OverviewCard`，字段：rating / action_direction / confidence / key_metrics / debate_synthesis / decision_drivers / one_line_takeaway）
  - `executive_summary` —— [`with_structured_output(ExecutiveSummary)`](#272-修法) 抽取的 1-2 句执行总结（[paper-trade v1.3 F3](#273-§-复用--reuse) 落地）
- 因此前端要做的不是新建数据通道，而是**把已有 surface 在 ticker 详情页上接通**。

### 28.2 § 方案

#### 28.2.1 后端：新增 `analysis_summary` rendering 包并随 plan 下发

**新增内部 helper**（[`web/app.py`](../../stock_trading_system/web/app.py)，置于 `api_paper_ticker_detail` 上方）：

```python
def _signal_to_tri_state(raw: str | None) -> str:
    """Mirror frontend signalLabel(): 7 档评级 → Buy/Sell/Hold。

    See analysis-inbox.md v1.3 for the canonical rule. Sell first
    so 'underweight' doesn't get caught by 'buy' substring later.
    """
    if not raw or not str(raw).strip():
        return "Hold"
    s = str(raw).strip().lower()
    if any(tok in s for tok in ("sell", "underweight", "reduce", "减仓", "bearish")):
        return "Sell"
    if any(tok in s for tok in ("buy", "overweight", "add", "加仓", "bullish")):
        return "Buy"
    if any(tok in s for tok in ("hold", "neutral", "wait", "中性")):
        return "Hold"
    return "Hold"


def _rendering_summary_for_analysis(analysis_id: int | None, db) -> dict | None:
    """Return a small struct used by paper-trade ticker detail page to
    render the same OverviewCard-style banner that /analysis/<id> uses.

    Shape (all fields optional, JSON-serializable):
      {
        "analysis_id": int,
        "ticker": str | None,
        "date": str | None,         # analysis_history.date
        "created_at": str | None,
        "signal_raw": str | None,   # 7-档原文（用于 Badge 颜色）
        "signal_tri": "Buy"|"Sell"|"Hold",   # 用于 Badge 文本
        "rating": str | None,       # OverviewCard.rating
        "action_direction": str | None,
        "executive_summary": str | None,
        "one_line_takeaway": str | None,
        "confidence_pct": int | None,         # 0..100
      }

    Missing rendering_json → still returns a row with signal_tri / executive_summary
    populated when available. Never returns analysis full body or
    legacy advice_json (privacy boundary, v1.18 R-fix-12).
    """
    if not analysis_id:
        return None
    try:
        ana = db.get_analysis_by_id(int(analysis_id))
    except Exception:
        return None
    if not ana:
        return None

    rendering = _parse_rendering(ana.get("rendering_json"))  # already defined above
    summary = (rendering or {}).get("summary") or {}

    confidence_pct = None
    if isinstance(summary.get("confidence"), (int, float)):
        c = float(summary["confidence"])
        confidence_pct = int(round(c * 100)) if 0 <= c <= 1 else int(round(c))

    return {
        "analysis_id": int(analysis_id),
        "ticker": ana.get("ticker"),
        "date": ana.get("date"),
        "created_at": ana.get("created_at"),
        "signal_raw": ana.get("signal"),
        "signal_tri": _signal_to_tri_state(ana.get("signal")),
        "rating": summary.get("rating"),
        "action_direction": summary.get("action_direction"),
        "executive_summary": ana.get("executive_summary"),
        "one_line_takeaway": summary.get("one_line_takeaway"),
        "confidence_pct": confidence_pct,
    }
```

**改造 `api_paper_ticker_detail`**：
- `active_plan` 在 return 之前附加 `analysis_summary = _rendering_summary_for_analysis(active_plan.analysis_id, _db)`
- `plan_history` 循环里把 `entry["trade_decision"] = …` 行**整段删除**，改为 `entry["analysis_summary"] = _rendering_summary_for_analysis(p.get("analysis_id"), _db)`
- `latest_trade_decision` 字段**保留**（向后兼容；前端不再渲染但旧 client 不报错），值改为 `None`（原 raw markdown 不再下发，节省 payload）
- 新增 `latest_analysis_summary = _rendering_summary_for_analysis(latest_event.analysis_id, _db)` 顶层字段（前端"当前策略"卡用 `active_plan.analysis_summary or latest_analysis_summary` 二选一）

#### 28.2.2 前端 A：当前策略卡重写

[`PaperTradePage.tsx:155-180`](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) 当前策略卡片整段替换为新 `<ActiveStrategyCard plan={data.active_plan} fallback={data.latest_analysis_summary}>` 组件：

```tsx
function ActiveStrategyCard({ plan, fallback }: {
  plan: ActivePlan | null;
  fallback: AnalysisSummary | null;  // 当无 active_plan 时仍展示最新分析
}) {
  const summary = plan?.analysis_summary ?? fallback;
  if (!plan && !summary) return null;  // 完全无数据 → 不渲染卡

  return (
    <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
      <div className="p-5">
        {/* Decision banner: Rating Badge + ConfidenceMeter + action_direction */}
        <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
          <div className="flex items-center gap-2">
            {summary?.signal_raw && (
              <Badge variant={signalVariant(summary.signal_raw)}>
                {signalLabel(summary.signal_raw)}
              </Badge>
            )}
            {summary?.rating && (
              <Badge variant="outline" className="font-semibold">
                {summary.rating}
              </Badge>
            )}
            {typeof summary?.confidence_pct === "number" && (
              <ConfidenceMeter pct={summary.confidence_pct} />
            )}
          </div>
          {summary?.analysis_id && (
            <a href={`/analysis/${summary.analysis_id}`}
               className="text-xs text-muted-foreground hover:text-foreground hover:underline">
              查看完整分析 →
            </a>
          )}
        </div>

        {/* action_direction —— 一句话执行方向 */}
        {summary?.action_direction && (
          <div className="text-base font-medium mb-3">
            📍 {summary.action_direction}
          </div>
        )}

        {/* Executive summary —— v1.6 OverviewCard 操作建议样式 */}
        {summary?.executive_summary && (
          <div className="border-l-4 border-primary/60 bg-primary/5 pl-3 py-2 mb-3">
            <div className="flex items-center gap-2 text-sm font-semibold mb-1">
              <ScrollText className="h-4 w-4" />
              执行总结
            </div>
            <p className="text-sm leading-relaxed line-clamp-4">
              {summary.executive_summary}
            </p>
          </div>
        )}

        {/* one_line_takeaway 兜底（无 executive_summary 时填补） */}
        {!summary?.executive_summary && summary?.one_line_takeaway && (
          <p className="text-sm text-muted-foreground mb-3">
            {summary.one_line_takeaway}
          </p>
        )}

        {/* Plan 元信息 —— 简化版，去掉 parse_method/regex 暴露细节 */}
        {plan && (
          <div className="text-xs text-muted-foreground border-t pt-3 mt-3 flex items-center gap-2 flex-wrap">
            <span>策略 #{plan.id}</span>
            <span>·</span>
            <span>{formatDateTime(plan.created_at)}</span>
            {plan.holding_months && (<><span>·</span><span>持有 {plan.holding_months} 个月</span></>)}
          </div>
        )}
      </div>
    </div>
  );
}
```

**关键设计点**：
- Rating Badge 用 [analysis-inbox v1.3 `signalLabel`](./analysis-inbox.md#v13) 三态归一（Buy/Sell/Hold）
- Executive Summary 视觉与 [analysis-rendering v1.6 OverviewCard](./analysis-rendering.md#v16) 一致（`border-l-4 border-primary/60 bg-primary/5` + `<ScrollText>` icon）
- "查看完整分析"超链接是补偿：本卡是浓缩版，需要给用户跳到完整 8 tab 的明确入口
- `parse_method=regex` 等实现细节**不再暴露**

#### 28.2.3 前端 B：删除「AI 最终决策」卡

[`PaperTradePage.tsx:240-256`](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) 整段删除：

```tsx
{/* DELETE THIS BLOCK */}
{data.latest_trade_decision && (
  <Card>
    <CardHeader><CardTitle>AI 最终决策</CardTitle></CardHeader>
    <CardContent>
      <div className="whitespace-pre-wrap text-sm">{data.latest_trade_decision}</div>
    </CardContent>
  </Card>
)}
```

理由：信息已被 28.2.2 当前策略卡 + 28.2.4 历史列表完整覆盖；保留只会形成"banner+raw markdown 双轨"。

#### 28.2.4 前端 C：执行记录·按 Plan → AI 分析历史列表

[`PaperTradePage.tsx:432-466`](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) `<PlanHistory>` 组件重构。**保留**外层 chip-row 切换（按 Plan / 按 Event），**重写**「按 Plan」视图为 AnalysisHistoryList（每个 plan 对应一次 AI 分析）：

```tsx
function AnalysisHistoryList({ plans }: { plans: PlanWithSummary[] }) {
  if (plans.length === 0) {
    return <p className="text-sm text-muted-foreground">尚无分析记录</p>;
  }
  // 按 created_at desc 已由后端排序
  return (
    <div className="divide-y">
      {plans.map((p, idx) => {
        const summary = p.analysis_summary;
        const isActive = idx === 0;  // 最新 plan = 当前活跃
        if (!summary) {
          // Plan 关联 analysis 但 rendering 缺失 → 降级展示
          return (
            <a key={p.id}
               href={p.analysis_id ? `/analysis/${p.analysis_id}` : "#"}
               className="block py-3 px-2 hover:bg-accent">
              <div className="flex items-center gap-2 text-sm">
                {isActive && <Badge variant="secondary">★ 当前</Badge>}
                <span className="text-muted-foreground">分析 #{p.analysis_id ?? "—"}</span>
                <span className="text-xs text-muted-foreground ml-auto">
                  {formatDateTime(p.created_at)}
                </span>
              </div>
            </a>
          );
        }
        return (
          <a key={p.id}
             href={`/analysis/${summary.analysis_id}`}
             className="block py-3 px-2 hover:bg-accent transition-colors">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              {isActive && <Badge variant="secondary">★ 当前</Badge>}
              {summary.signal_raw && (
                <Badge variant={signalVariant(summary.signal_raw)} className="text-xs">
                  {signalLabel(summary.signal_raw)}
                </Badge>
              )}
              {summary.rating && (
                <Badge variant="outline" className="text-xs">{summary.rating}</Badge>
              )}
              {typeof summary.confidence_pct === "number" && (
                <span className="text-xs text-muted-foreground">
                  置信 {summary.confidence_pct}%
                </span>
              )}
              <span className="text-xs text-muted-foreground ml-auto">
                {formatDateTime(summary.created_at)}
              </span>
            </div>
            {summary.action_direction && (
              <div className="text-sm font-medium mb-1">📍 {summary.action_direction}</div>
            )}
            {(summary.executive_summary || summary.one_line_takeaway) && (
              <p className="text-xs text-muted-foreground line-clamp-2">
                {summary.executive_summary || summary.one_line_takeaway}
              </p>
            )}
          </a>
        );
      })}
    </div>
  );
}
```

**视觉参考**：[analysis-inbox v1.18 R-fix-12G `HistoryPage` 列表行风格](./analysis-inbox.md)（divide-y + hover bg-accent + 三态 Badge + ★ 当前标记）。

**「按 Event」tab 不动**：仍由现有 `_renderPtvTimeline` / `EventList` 渲染（单个 event 不必映射到分析）。

### 28.3 § 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md) L0→L4 阶梯：

**L0 项目内复用**：
- [`_parse_rendering`](../../stock_trading_system/web/app.py#L175) 已有 helper（解析 `rendering_json` → dict，缺失/坏 JSON 静默 None） —— 后端 helper 直接调用
- [`_db.get_analysis_by_id`](../../stock_trading_system/portfolio/database.py) 已有，含 `executive_summary` / `rendering_json` 列
- [`_db.get_user_advice`](../../stock_trading_system/portfolio/database.py) 已正确隔离 per-user advice，**不改**
- 前端 [`signalLabel` / `signalVariant`](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)（[analysis-inbox v1.3](./analysis-inbox.md#v13)）已 export，直接 import
- 前端 [`<ConfidenceMeter>`](../../stock_trading_system/web/frontend/src/islands/analysis/cards/OverviewCard.tsx)（analysis-rendering v1.0+）已是独立组件
- shadcn `<Badge>` / lucide `<ScrollText>` 已在 bundle 中

**L1 依赖库**：
- 无新增

**L2/L3/L4**：
- 后端 ~70 LOC（`_signal_to_tri_state` + `_rendering_summary_for_analysis` + 3 处 detail 端点 wiring）
- 前端 ~150 LOC（`<ActiveStrategyCard>` 重写 + `<PlanHistory>` 改 `<AnalysisHistoryList>` + 删 AI 最终决策卡）
- 总计 ~220 LOC，**0 业务逻辑新增**，全部是把现有 rendering pipeline 在 ticker 详情页上接通

### 28.4 § 不动清单（防回滚踩坑）

明确**不**改的部分：
- `paper_trade_plans` schema / `session_store.save_plan` 事务 / supersede 逻辑（v1.3 F1 已稳定）
- `event_executor.py` plan 触发链 / [`plan_parser.py`](../../stock_trading_system/strategy/paper_trader/plan_parser.py) regex 解析（作为 LLM 失败 fallback 仍保留）
- `latest_advice`（`get_user_advice` per-user 隐私边界，[v1.18 R-fix-12](./analysis-inbox.md) 已建立）
- `events` / `dailies` / `trades` / `active_orders` / `session` 字段（不动）
- "按 Event" tab 渲染 / 时间轴逻辑（不动）
- `analysis_history.rendering_json` / `executive_summary` 列 schema（不动，仅读）
- OverviewCard / 8 tab Card 组件（不动，详情页仍是 canonical view，ticker 详情页只是入口/浓缩）
- `RoundtableResult` dataclass / screener 链路（不动）

### 28.5 § 测试

新增 `tests/frontend/paper-trade/active-strategy-card.test.tsx`：

```tsx
describe("ActiveStrategyCard v1.4", () => {
  test("renders rating badge + tri-state signal + executive summary", () => {
    const summary = {
      analysis_id: 42, signal_raw: "Overweight", signal_tri: "Buy",
      rating: "买入", action_direction: "分批建仓",
      executive_summary: "公司 AI 资本支出可由现金流轻松覆盖", confidence_pct: 78,
    };
    render(<ActiveStrategyCard plan={{ id: 1, analysis_summary: summary } as any} fallback={null} />);
    expect(screen.getByText("Buy")).toBeInTheDocument();  // signalLabel(Overweight)
    expect(screen.getByText("买入")).toBeInTheDocument();  // rating
    expect(screen.getByText(/分批建仓/)).toBeInTheDocument();
    expect(screen.getByText(/AI 资本支出/)).toBeInTheDocument();
    expect(screen.getByText("查看完整分析 →")).toHaveAttribute("href", "/analysis/42");
    expect(screen.queryByText(/parse_method/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/regex/i)).not.toBeInTheDocument();
  });

  test("falls back to latest_analysis_summary when no active_plan", () => {
    const fallback = { analysis_id: 7, signal_tri: "Hold", action_direction: "观望" };
    render(<ActiveStrategyCard plan={null} fallback={fallback as any} />);
    expect(screen.getByText("Hold")).toBeInTheDocument();
    expect(screen.getByText(/观望/)).toBeInTheDocument();
  });

  test("renders nothing when both plan and fallback are null", () => {
    const { container } = render(<ActiveStrategyCard plan={null} fallback={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AnalysisHistoryList v1.4", () => {
  test("each row links to /analysis/<id> and first row marked ★ 当前", () => {
    const plans = [
      { id: 10, analysis_id: 42, analysis_summary: { analysis_id: 42, signal_raw: "Buy", action_direction: "建仓", created_at: "2026-05-04 10:00:00" } },
      { id: 9,  analysis_id: 41, analysis_summary: { analysis_id: 41, signal_raw: "Hold", action_direction: "观望", created_at: "2026-05-03 10:00:00" } },
    ];
    render(<AnalysisHistoryList plans={plans as any} />);
    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveAttribute("href", "/analysis/42");
    expect(links[1]).toHaveAttribute("href", "/analysis/41");
    expect(screen.getByText("★ 当前")).toBeInTheDocument();
  });

  test("no AI 最终决策 card rendered (deleted in v1.4)", () => {
    render(<PaperTradePage />);  // mocked detail data with latest_trade_decision: <md>
    expect(screen.queryByText("AI 最终决策")).not.toBeInTheDocument();
  });
});
```

后端 `tests/test_paper_trade_ticker_detail_v1_4.py`：

```python
def test_active_plan_carries_analysis_summary(client, db):
    # arrange: insert analysis_history row with rendering_json + executive_summary
    # arrange: insert paper_trade_plans row linked to that analysis_id
    resp = client.get("/api/paper/tickers/MSFT").get_json()
    ap = resp["active_plan"]
    assert ap["analysis_summary"]["signal_tri"] in ("Buy", "Sell", "Hold")
    assert ap["analysis_summary"]["executive_summary"]
    assert ap["analysis_summary"]["analysis_id"] == ana_id

def test_plan_history_no_longer_contains_trade_decision_markdown(client, db):
    resp = client.get("/api/paper/tickers/MSFT").get_json()
    for row in resp["plan_history"]:
        assert "trade_decision" not in row or not row["trade_decision"]
        assert "analysis_summary" in row

def test_signal_to_tri_state_underweight_is_sell():
    assert _signal_to_tri_state("Underweight") == "Sell"  # not Buy via 'weight' substring
    assert _signal_to_tri_state("Strong Buy") == "Buy"
    assert _signal_to_tri_state(None) == "Hold"
```

### 28.6 § 实施顺序

1. 后端 helper（`_signal_to_tri_state` + `_rendering_summary_for_analysis`）+ 单测
2. `api_paper_ticker_detail` wiring（attach `analysis_summary` 到 `active_plan` / `plan_history[]` / 顶层 `latest_analysis_summary`）+ 集成测试
3. 前端 `<ActiveStrategyCard>` 新组件 + 替换 [PaperTradePage.tsx:155-180](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx)
4. 删除「AI 最终决策」卡 [PaperTradePage.tsx:240-256](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx)
5. 前端 `<AnalysisHistoryList>` 替换 `<PlanHistory>` 内容
6. vitest 套件
7. 手动回归 `/paper-trade/MSFT` 三处对照截图

每步独立 commit，独立回滚单位。

---

*v1.4 修订结束 — 等待确认后开始实施*
