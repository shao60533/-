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

*v1.2 修订结束 — 全量自动追踪。等待确认后开始 Phase 1 实施*
