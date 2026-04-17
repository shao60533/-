# 自我迭代美股分析 Agent 技术方案

> **版本**: 2.0  
> **日期**: 2026-04-18  
> **状态**: 草稿 — 待评审  
> **依据**: A 股自我迭代方案（ATLAS 哲学）→ 美股独立模块  
> **定位**: 与现有 TradingAgents 分析管线并行的**独立功能**，不依赖、不改动 TradingAgents

---

## 一、核心思想

**prompt 是权重，Sharpe 是 loss，git 是优化器。**

建一套独立的自我迭代分析系统：
1. **四层 Agent Pipeline** — 宏观→板块→风格→决策，全程 `qwen3.6-plus` 驱动
2. **Scorecard** — 记录每个 agent 每次 call 的后续真实表现
3. **Darwinian 权重** — 每日根据 scorecard 动态调节 agent 话语权
4. **Meta Agent** — 每周自动改写表现最差 agent 的 prompt

---

## 二、为什么独立

| 维度 | 现有 TradingAgents | 本方案 |
|------|-------------------|-------|
| 定位 | 单票深度分析（7 Agent LangGraph 管线） | 市场全局扫描 + 自我进化 |
| 模型 | Gemini / 多 provider | **统一 qwen3.6-plus** |
| Agent 结构 | 固定 4 analysts + 辩论 + 风控 | 四层（宏观/板块/风格/决策）+ 可增减 |
| Prompt 管理 | 硬编码在 Python 文件里 | **外置 .md 文件 + 版本管理 + 自动改写** |
| 自我改进 | 无（BM25 记忆是辅助，不改 prompt） | **Scorecard → Darwinian 权重 → Meta Agent 改写 prompt** |
| 调用方式 | 用户手动触发 | **每日盘后自动运行** + 用户可手动触发 |
| 输出 | 单票的 AnalysisResult | 市场日报 + 板块观点 + 个股信号列表 + agent 健康度 |

两套系统并行，用户可以：
- 用 TradingAgents 做某只股票的深度分析（已有）
- 用本系统每日自动获得全局市场视图 + 自我进化的信号（新增）

---

## 三、模型选择

**统一使用 `qwen3.6-plus`**，不做模型分层。

| 理由 | 说明 |
|------|------|
| 简单 | 一个模型打天下，不用管 flash/plus/max 的分派逻辑 |
| 够用 | qwen3.6-plus 是当前 Qwen 最新主力模型，MoE 架构，性价比最优 |
| 一致性 | 所有 agent 用同一模型，Scorecard 的 Sharpe 对比才公平 |
| Meta Agent 也用 | 每周才跑 3-5 次，不值得单独用更贵的模型 |

**唯一例外**：如果 qwen3.6-plus 出现限流，fallback 到 `qwen-plus`（上一代）。

**成本估算**（qwen3.6-plus 按 Qwen-plus 价格估）：

| 组件 | 日调用 | tokens/次 | 月成本估算 |
|------|--------|----------|-----------|
| L1 宏观 × 5 | 5 | ~2K | ~¥6 |
| L2 板块 × 6 | 6 | ~3K | ~¥12 |
| L3 风格 × 4 | 4×N 只标的 | ~2K | ~¥15（10 只） |
| L4 决策 × 3 | 3×N 只 | ~3K | ~¥15 |
| Meta Agent | 3-5/周 | ~5K | ~¥4 |
| **合计** | | | **~¥52/月**（10 只标的） |

---

## 四、系统架构

```
┌────────────────────────────────────────────────────────────┐
│  Meta Agent (qwen3.6-plus)                                  │
│  每周日跑一次：                                              │
│  - 读 scorecard 找最差 agent                                │
│  - 生成 prompt diff + 修改理由                               │
│  - 新版本进入 5 天 A/B 验证期                                │
│  - Sharpe 决定生死                                          │
└───────────────┬────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────┐
│  四层 Agent Pipeline（每交易日盘后自动跑）                    │
│  全程 qwen3.6-plus                                          │
│                                                              │
│  L1 宏观层 (5 agents)                                       │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Fed Watcher     — 联储利率路径、FOMC、点阵图          │  │
│  │ Risk Gauge      — VIX、MOVE、信用利差、恐慌指数       │  │
│  │ Dollar/Rates    — DXY、10Y yield、2s10s curve        │  │
│  │ Flows Tracker   — 13F 机构持仓、ETF 资金流向          │  │
│  │ Commodities     — 原油、黄金、铜（通胀预期）           │  │
│  └─────────────────────────────────────────────────────┘  │
│       ↓ 宏观综述 context                                    │
│                                                              │
│  L2 板块层 (6 agents)                                       │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Tech/AI         — 半导体、Cloud、AI 算力              │  │
│  │ Healthcare      — 生物科技、制药、医疗设备             │  │
│  │ Financials      — 银行、保险、券商                     │  │
│  │ Energy          — 石油、天然气、新能源                 │  │
│  │ Consumer        — 零售、食品、奢侈品                   │  │
│  │ Defense/Infra   — 军工、基建、工业                     │  │
│  └─────────────────────────────────────────────────────┘  │
│       ↓ 板块信号 + top picks                                │
│                                                              │
│  L3 风格层 (4 agents) — 对每只候选标的打分                   │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Value           — 深度价值（Buffett/Graham 风格）      │  │
│  │ Growth          — 高成长（Cathie Wood/Peter Lynch）    │  │
│  │ Momentum        — 趋势跟随（动量+突破）                │  │
│  │ Mean Reversion  — 低位反转（超跌反弹+均值回归）        │  │
│  └─────────────────────────────────────────────────────┘  │
│       ↓ 4 维评分                                            │
│                                                              │
│  L4 决策层 (3 agents)                                       │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Risk CRO        — 风险把关（否决权）                   │  │
│  │ Alpha Hunter    — 发现 alpha 机会                     │  │
│  │ CIO             — 综合决策（加权采信所有 agent）       │  │
│  └─────────────────────────────────────────────────────┘  │
│       ↓ 最终信号列表                                        │
└───────────────┬────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────┐
│  Scorecard DB (SQLite)                                      │
│  每个 agent 每只股票每次 call + 后续 5/20 日涨跌            │
│  → 滚动 Sharpe → Darwinian 权重 → 反馈到 L4 CIO           │
└────────────────────────────────────────────────────────────┘
```

### 4.1 层间数据流

```
L1 (5 agents 各自独立运行)
  → 各自输出 {signal, confidence, key_factors[], summary}
  → 汇总为 macro_context 字符串

L2 (6 agents，接收 macro_context)
  → 各自输出 {signal, momentum, key_drivers[], risks[], top_picks[]}
  → 汇总 top_picks → 去重 → 候选标的池（~20-30 只）

L3 (4 agents，对每只候选标的评分)
  → 输入：ticker + K 线 + 基本面 + macro_context + sector_view
  → 输出：{ticker, score: 1-100, grade: A+~F, signal: BUY/HOLD/SELL, rationale}
  → 四维评分矩阵

L4 (3 agents，综合决策)
  → Risk CRO：审查 L3 评分，标记高风险标的，可否决
  → Alpha Hunter：在 L3 结果中找共识度高的机会
  → CIO：按 Darwinian 权重加权综合，输出最终排名 + 信号
```

### 4.2 与现有系统的关系

```
┌─────────────────────────────────────────────┐
│  stock-trading-system                        │
│                                               │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │ TradingAgents │    │ Self-Iterating    │   │
│  │ (深度单票分析) │    │ Agents (市场扫描) │   │
│  │ Gemini/多模型  │    │ qwen3.6-plus     │   │
│  │ 用户手动触发   │    │ 每日自动+手动     │   │
│  └──────┬───────┘    └────────┬─────────┘   │
│         │                     │               │
│         ▼                     ▼               │
│  ┌──────────────────────────────────────┐   │
│  │  analysis_history（共用结果存储）      │   │
│  │  agent_scorecards（新：agent 记分卡） │   │
│  │  TaskManager（共用任务调度）           │   │
│  │  Portfolio / Paper Trade / Alerts     │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## 五、Qwen 客户端封装

```python
# agents/iterative/qwen_client.py

from openai import OpenAI
import os
import json

class IterativeQwenClient:
    """自我迭代 Agent 专用 Qwen 客户端。"""
    
    MODEL = "qwen3.6-plus"
    FALLBACK_MODEL = "qwen-plus"
    
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    
    def call(self, system: str, user: str, json_mode: bool = False) -> str:
        """调用 qwen3.6-plus，限流时 fallback。"""
        kwargs = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        
        try:
            resp = self.client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                kwargs["model"] = self.FALLBACK_MODEL
                resp = self.client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content
            raise
    
    def call_json(self, system: str, user: str) -> dict:
        """调用并解析 JSON 输出。"""
        raw = self.call(system, user, json_mode=True)
        return json.loads(raw)
```

---

## 六、Agent 基类与 Prompt 管理

### 6.1 Agent 基类

```python
# agents/iterative/base.py

class IterativeAgent:
    """自我迭代 Agent 基类。"""
    
    def __init__(self, agent_id: str, layer: str, prompt_path: str):
        self.agent_id = agent_id
        self.layer = layer
        self.prompt_path = prompt_path
        self._qwen = IterativeQwenClient()
    
    @property
    def system_prompt(self) -> str:
        """从文件加载当前 active 版本的 prompt。"""
        # 优先从 prompt_versions 表取 active 版本
        active = db.get_active_prompt(self.agent_id)
        if active:
            return active["prompt_text"]
        # 否则读文件（初始版本）
        return open(self.prompt_path).read()
    
    @property
    def weight(self) -> float:
        """当前 Darwinian 权重。"""
        return db.get_current_weight(self.agent_id) or 1.0
    
    def run(self, context: str) -> dict:
        """运行 agent，返回结构化结果。"""
        response = self._qwen.call_json(self.system_prompt, context)
        return response
    
    def record_scorecard(self, ticker: str | None, signal: str,
                         rationale: str, raw: str):
        """记录到 scorecard 表。"""
        db.insert_scorecard({
            "agent_id": self.agent_id,
            "agent_layer": self.layer,
            "prompt_version": self._get_prompt_version(),
            "date": today_str(),
            "ticker": ticker,
            "call_signal": signal,
            "call_rationale": rationale,
            "call_raw": raw,
            "price_at_call": get_close_price(ticker) if ticker else None,
            "darwinian_weight": self.weight,
        })
```

### 6.2 Prompt 文件结构

```
stock_trading_system/
└── agents/
    └── iterative/
        ├── __init__.py
        ├── qwen_client.py          ← Qwen 客户端
        ├── base.py                 ← Agent 基类
        ├── pipeline.py             ← 四层管线编排
        ├── scorecard.py            ← Scorecard 记录 + 回填 + 指标
        ├── darwinian.py            ← 权重更新
        ├── meta_agent.py           ← 自动改写 prompt
        │
        ├── L1_macro/               ← L1 宏观 agent
        │   ├── fed_watcher.py
        │   ├── risk_gauge.py
        │   ├── dollar_rates.py
        │   ├── flows_tracker.py
        │   └── commodities.py
        │
        ├── L2_sector/              ← L2 板块 agent
        │   ├── tech_ai.py
        │   ├── healthcare.py
        │   ├── financials.py
        │   ├── energy.py
        │   ├── consumer.py
        │   └── defense_infra.py
        │
        ├── L3_style/               ← L3 风格 agent
        │   ├── value.py
        │   ├── growth.py
        │   ├── momentum.py
        │   └── mean_reversion.py
        │
        ├── L4_decision/            ← L4 决策 agent
        │   ├── risk_cro.py
        │   ├── alpha_hunter.py
        │   └── cio.py
        │
        └── prompts/                ← 可 git 跟踪的 prompt 文件
            ├── L1_fed.md
            ├── L1_risk.md
            ├── L1_rates.md
            ├── L1_flows.md
            ├── L1_commodities.md
            ├── L2_tech_ai.md
            ├── L2_healthcare.md
            ├── L2_financials.md
            ├── L2_energy.md
            ├── L2_consumer.md
            ├── L2_defense_infra.md
            ├── L3_value.md
            ├── L3_growth.md
            ├── L3_momentum.md
            ├── L3_mean_reversion.md
            ├── L4_risk_cro.md
            ├── L4_alpha_hunter.md
            ├── L4_cio.md
            └── meta_agent.md
```

---

## 七、Pipeline 编排

### 7.1 每日自动运行流程

```python
# agents/iterative/pipeline.py

class IterativePipeline:
    """四层 Agent 管线 — 每日盘后自动跑。"""
    
    def __init__(self, config):
        self.watchlist = config.get("iterative_watchlist", [])
        # 初始化 18 个 agent
        self.L1_agents = [FedWatcher(), RiskGauge(), DollarRates(), 
                          FlowsTracker(), Commodities()]
        self.L2_agents = [TechAI(), Healthcare(), Financials(),
                          Energy(), Consumer(), DefenseInfra()]
        self.L3_agents = [Value(), Growth(), Momentum(), MeanReversion()]
        self.L4_agents = [RiskCRO(), AlphaHunter(), CIO()]
    
    def run_daily(self, date: str, progress_cb=None) -> dict:
        """完整日度运行。"""
        
        # ── L1 宏观 ──
        progress_cb(5, "L1 宏观分析")
        macro_results = {}
        for agent in self.L1_agents:
            result = agent.run(date)
            agent.record_scorecard(ticker="SPY", signal=result["signal"],
                                   rationale=result["summary"], raw=str(result))
            macro_results[agent.agent_id] = result
        
        macro_context = self._format_macro_context(macro_results)
        
        # ── L2 板块 ──
        progress_cb(20, "L2 板块分析")
        sector_results = {}
        candidate_tickers = set(self.watchlist)  # 自选标的始终包含
        
        for agent in self.L2_agents:
            result = agent.run(date, macro_context)
            agent.record_scorecard(ticker=agent.primary_etf, signal=result["signal"],
                                   rationale=result.get("summary", ""), raw=str(result))
            sector_results[agent.sector_id] = result
            # 收集板块 top picks
            candidate_tickers.update(result.get("top_picks", []))
        
        sector_context = self._format_sector_context(sector_results)
        candidates = list(candidate_tickers)
        
        # ── L3 逐只评分 ──
        progress_cb(35, f"L3 风格评分（{len(candidates)} 只）")
        ticker_scores = {}  # ticker -> {agent_id -> AgentScore}
        
        for i, ticker in enumerate(candidates):
            ticker_context = self._build_ticker_context(ticker, date, 
                                                         macro_context, sector_context)
            ticker_scores[ticker] = {}
            
            for agent in self.L3_agents:
                result = agent.score(ticker, ticker_context)
                agent.record_scorecard(ticker=ticker, signal=result["signal"],
                                       rationale=result["rationale"], raw=str(result))
                ticker_scores[ticker][agent.agent_id] = result
            
            pct = 35 + int((i + 1) / len(candidates) * 45)  # 35% → 80%
            progress_cb(pct, f"L3 评分 {ticker} ({i+1}/{len(candidates)})")
        
        # ── L4 决策 ──
        progress_cb(85, "L4 综合决策")
        
        # Risk CRO 审查
        risk_review = self.L4_agents[0].review(ticker_scores, macro_context)
        
        # Alpha Hunter 找机会
        alpha_picks = self.L4_agents[1].find_alpha(ticker_scores, sector_context)
        
        # CIO 最终决策（加权综合）
        weights = {a.agent_id: a.weight for a in 
                   self.L1_agents + self.L2_agents + self.L3_agents}
        final_signals = self.L4_agents[2].decide(
            ticker_scores, weights, risk_review, alpha_picks,
            macro_context, sector_context
        )
        
        # 记录 L4 scorecard
        for item in final_signals:
            for agent in self.L4_agents:
                agent.record_scorecard(
                    ticker=item["ticker"], signal=item["signal"],
                    rationale=item.get("rationale", ""), raw=str(item)
                )
        
        progress_cb(99, "完成")
        
        return {
            "date": date,
            "macro": macro_results,
            "sectors": sector_results,
            "candidates": len(candidates),
            "signals": final_signals,
            "agent_count": 18,
        }
```

### 7.2 输出结构

每日运行产出的 `final_signals`：

```json
[
    {
        "rank": 1,
        "ticker": "NVDA",
        "signal": "BUY",
        "conviction": 87,
        "style_scores": {
            "value": {"score": 45, "grade": "C"},
            "growth": {"score": 95, "grade": "A+"},
            "momentum": {"score": 88, "grade": "A"},
            "mean_reversion": {"score": 30, "grade": "D"}
        },
        "sector": "Tech/AI",
        "macro_alignment": "positive",
        "risk_flag": null,
        "rationale": "L3 三维高分 + L2 板块强势 + L1 宏观配合",
        "entry": "$890-905",
        "stop": "$840",
        "target": "$1050"
    },
    ...
]
```

---

## 八、Scorecard 系统

### 8.1 表结构

```sql
CREATE TABLE agent_scorecards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    agent_layer TEXT NOT NULL,      -- L1/L2/L3/L4
    prompt_version TEXT,
    date TEXT NOT NULL,
    ticker TEXT,                    -- L1 用 SPY，L2 用板块 ETF
    
    call_signal TEXT,               -- BUY/HOLD/SELL 或 bullish/bearish/neutral
    call_score REAL,                -- 1-100（L3 agent）
    call_rationale TEXT,
    call_raw TEXT,
    
    price_at_call REAL,
    price_5d REAL,
    price_20d REAL,
    return_5d REAL,
    return_20d REAL,
    
    sharpe_30d REAL,
    hit_rate_30d REAL,
    darwinian_weight REAL DEFAULT 1.0,
    
    created_at TEXT NOT NULL
);

CREATE INDEX idx_sc_agent_date ON agent_scorecards(agent_id, date DESC);
CREATE INDEX idx_sc_ticker_date ON agent_scorecards(ticker, date DESC);
CREATE INDEX idx_sc_pending_5d ON agent_scorecards(date) WHERE return_5d IS NULL AND price_at_call IS NOT NULL;
```

### 8.2 每日盘后回填 + 指标更新

```python
# agents/iterative/scorecard.py

def daily_scorecard_update():
    """每日盘后运行：回填价格 + 更新 Sharpe + 更新权重。"""
    backfill_returns()        # 回填 5d/20d
    update_rolling_metrics()  # 更新 Sharpe + 命中率
    update_darwinian_weights() # 更新权重
```

（回填和指标计算逻辑与 v1.0 方案第五节相同，此处不重复。）

---

## 九、Darwinian 权重

每日盘后更新：

```python
def update_darwinian_weights():
    """Top 25% × 1.05, Bottom 25% × 0.95, 边界 [0.3, 2.5]。"""
    rankings = get_agent_rankings_by_sharpe()  # 最近 30 天 Sharpe 排序
    
    n = len(rankings)
    if n < 4:
        return
    
    top_25 = set(r["agent_id"] for r in rankings[:n//4])
    bottom_25 = set(r["agent_id"] for r in rankings[-(n//4):])
    
    for r in rankings:
        old_w = r.get("current_weight", 1.0)
        
        if r["agent_id"] in top_25:
            new_w = old_w * 1.05
        elif r["agent_id"] in bottom_25:
            new_w = old_w * 0.95
        else:
            new_w = old_w
        
        new_w = max(0.3, min(2.5, new_w))
        save_weight(r["agent_id"], new_w)
```

**权重应用**：L4 CIO agent 的 prompt 中会注入每个 agent 的权重：

```
各分析师可信度权重（基于近 30 天 Sharpe）：
- L3_growth: 1.85 ★ (top performer)
- L3_momentum: 1.42
- L1_fed: 1.15
- L3_value: 0.88
- L2_energy: 0.45 ⚠ (underperforming)

请在综合决策时，更多采信高权重 agent 的观点。
```

---

## 十、Meta Agent（Prompt 自我进化）

### 10.1 每周流程

1. **找目标**：Scorecard 30 天 Sharpe 排名最后的 agent
2. **收集证据**：该 agent 最差 10 次 call + 真实后续涨跌 + 同层最佳 agent 的 prompt
3. **qwen3.6-plus 生成新 prompt**：输出改进版 + 修改理由
4. **进入 A/B 验证期**：新旧 prompt 并行跑 5 个交易日，分别记录 scorecard
5. **Sharpe 决生死**：改善 → activate，没改善 → retire

### 10.2 Prompt 版本管理

```sql
CREATE TABLE prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    prompt_text TEXT NOT NULL,
    reasoning TEXT,                  -- Meta Agent 的修改理由
    status TEXT DEFAULT 'testing',   -- testing | active | retired
    sharpe_before REAL,
    sharpe_after REAL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    UNIQUE(agent_id, version)
);
```

### 10.3 A/B 测试

验证期内，同一 ticker 用 active 和 testing prompt 各跑一次：
- active 版本的结果用于实际决策
- testing 版本仅记录 scorecard，不影响信号输出
- 5 天后对比两个版本的 Sharpe
- ATLAS 实盘数据：~30% 保留率（新 prompt 比旧的好）

---

## 十一、数据源

| 数据类型 | 来源 | 用途 | 已有 |
|---------|------|------|------|
| 行情 K 线 | yfinance | L3 评分 + scorecard 回填 | ✅ |
| 基本面 | Qwen web search | L3 Value/Growth agent | ✅ |
| 新闻 | Qwen web search | L1/L2/L3 多层共用 | ✅ |
| VIX / MOVE / DXY / 10Y | yfinance | L1 Risk/Rates | ✅ |
| 商品期货 | yfinance（CL=F, GC=F, HG=F） | L1 Commodities | ✅ |
| 板块 ETF | yfinance（XLK, XLV, XLF, XLE, XLY, ITA） | L2 板块 | ✅ |
| 机构持仓 / ETF 资金流 | Qwen web search | L1 Flows | 新增 |

全部通过 yfinance + Qwen 获取，**不引入新数据源**。

---

## 十二、新增表汇总

| 表名 | 用途 |
|------|------|
| `agent_scorecards` | Agent 每次 call 记录 + 后续验证 |
| `prompt_versions` | Prompt 版本管理 + A/B 验证 |
| `macro_signals` | L1 宏观 agent 每日产出 |
| `sector_signals` | L2 板块 agent 每日产出 |
| `darwinian_weights` | Agent 权重历史 |
| `iterative_daily_reports` | 每日管线输出汇总 |

```sql
CREATE TABLE macro_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT,
    confidence REAL,
    key_factors TEXT,     -- JSON
    summary TEXT,
    raw_output TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(agent_id, date)
);

CREATE TABLE sector_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    sector TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT,
    momentum TEXT,
    key_drivers TEXT,     -- JSON
    risks TEXT,           -- JSON
    top_picks TEXT,       -- JSON
    raw_output TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(agent_id, date)
);

CREATE TABLE darwinian_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    date TEXT NOT NULL,
    weight REAL NOT NULL,
    sharpe_30d REAL,
    hit_rate_30d REAL,
    rank INTEGER,
    UNIQUE(agent_id, date)
);

CREATE TABLE iterative_daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    task_id TEXT,
    macro_json TEXT,       -- L1 汇总
    sectors_json TEXT,     -- L2 汇总
    signals_json TEXT,     -- 最终信号列表
    candidates_count INTEGER,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);
```

---

## 十三、任务集成

### 13.1 TaskManager 注册

| 任务类型 | Worker | 触发 |
|---------|--------|------|
| `iterative_daily` | 完整四层管线 | 每交易日盘后 / 手动 |
| `scorecard_backfill` | 回填 + 指标 + 权重 | 每交易日盘后 |
| `meta_autoresearch` | Meta Agent 改写 prompt | 每周日 |
| `prompt_ab_settle` | A/B 测试结算 | 每周五 |

### 13.2 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /api/iterative/run` | POST | 手动触发当日管线（走 TaskManager） |
| `GET /api/iterative/latest` | GET | 最近一次管线结果（信号列表） |
| `GET /api/iterative/history` | GET | 历史日报列表 |
| `GET /api/iterative/agents` | GET | 所有 agent 的 Sharpe / 权重 / 命中率 |
| `GET /api/iterative/agent/:id` | GET | 单个 agent 详情 + scorecard 历史 |
| `GET /api/iterative/agent/:id/prompt-history` | GET | prompt 版本历史 |
| `POST /api/iterative/config` | POST | 更新 watchlist / 开关 |

### 13.3 前端页面

新增独立页面 **"AI 迭代信号"**（`page-iterative`），侧边栏新入口：

```
┌─────────────────────────────────────────────────────────────┐
│  AI 迭代信号 · 2026-04-18                    [手动运行] [设置] │
├──────────────────────────┬──────────────────────────────────┤
│  L1 宏观综述              │  L2 板块热力图                    │
│  Fed: dovish 🟢          │  Tech/AI    ████████ bullish     │
│  Risk: risk_on 🟢        │  Healthcare ████     neutral     │
│  DXY: weakening 🟢       │  Financials ██████   bullish     │
│  Flows: inflow 🟢        │  Energy     ███      bearish     │
│  Commodities: stable 🟡  │  Consumer   █████    neutral     │
│                           │  Defense    ██████   bullish     │
├──────────────────────────┴──────────────────────────────────┤
│  今日信号（按 conviction 排序）                               │
│  1. NVDA  BUY  87分  Growth A+ / Momentum A / Value C       │
│  2. MSFT  BUY  82分  Growth A  / Value B+ / Momentum B+     │
│  3. META  HOLD 71分  Value A   / Growth B  / MeanRev C      │
│  ...                                                         │
├──────────────────────────────────────────────────────────────┤
│  Agent 健康度                                                │
│  ┌─ Top 3 ──────────────┐  ┌─ Bottom 3 ─────────────────┐  │
│  │ L3_growth  Sharpe 1.8│  │ L2_energy  Sharpe -0.3     │  │
│  │ L1_fed     Sharpe 1.5│  │ L3_mean_rev Sharpe -0.1    │  │
│  │ L3_momentum Sharpe 1.2│ │ L1_commodities Sharpe 0.1  │  │
│  └──────────────────────┘  └─────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 十四、配置

```yaml
# config.yaml 新增节

iterative:
  enabled: false              # 总开关，默认关闭
  model: "qwen3.6-plus"
  fallback_model: "qwen-plus"
  
  watchlist:                  # 自选标的（始终包含在候选池）
    - AAPL
    - MSFT
    - NVDA
    - TSLA
    - GOOG
    - AMZN
    - META
    - AMD
  
  schedule:
    daily_run_time: "17:00"   # 美东时间盘后
    meta_day: "sunday"
    meta_time: "20:00"
  
  scorecard:
    backfill_5d: true
    backfill_20d: true
    rolling_window_days: 30
    min_samples_for_sharpe: 5
  
  darwinian:
    top_boost: 1.05
    bottom_decay: 0.95
    weight_min: 0.3
    weight_max: 2.5
  
  meta:
    ab_test_days: 5           # 新 prompt 验证期
    max_rewrites_per_week: 3  # 每周最多改几个 agent
```

---

## 十五、美股注意事项

| # | 坑 | 应对 |
|---|----|----|
| 1 | 盘后/盘前交易 | Scorecard 只用收盘价（`Adj Close`），忽略盘后 |
| 2 | Earnings season | L2 agent prompt 注入当前日期是否在财报季（1/4/7/10 月中下旬） |
| 3 | FOMC 日历 | L1 Fed Watcher prompt 注入下次 FOMC 日期 |
| 4 | 股票拆分/分红 | yfinance 默认 adj close，scorecard 回填用 adj close |
| 5 | 小盘股流动性 | 日均成交额 < $1M 的标的标记 `low_liquidity`，不计入 Sharpe |
| 6 | 美股休市日 | 定时任务需检查 `pandas_market_calendars` 或硬编码假日列表 |
| 7 | ETF 可能不在 Qwen 知识范围 | L2 用 yfinance 取 ETF 价格数据，不依赖 Qwen 报 ETF 行情 |

---

## 十六、分阶段实施

### Phase 1 — 骨架 + Scorecard（1 周）

| 步骤 | 内容 |
|------|------|
| 1.1 | 新建 `agents/iterative/` 目录结构 |
| 1.2 | 实现 `qwen_client.py` + `base.py` |
| 1.3 | 建表：`agent_scorecards` + `darwinian_weights` |
| 1.4 | 实现 `scorecard.py`（记录 + 回填 + 指标） |
| 1.5 | 实现 `darwinian.py`（权重更新） |
| 1.6 | 写 3 个 agent 跑通闭环：1 个 L1（Fed Watcher）+ 1 个 L2（Tech/AI）+ CIO |
| 1.7 | 注册 `iterative_daily` + `scorecard_backfill` 到 TaskManager |
| 1.8 | 测试：手动触发 → 3 个 agent 跑完 → scorecard 有记录 |

### Phase 2 — 补全 18 个 Agent（1 周）

| 步骤 | 内容 |
|------|------|
| 2.1 | 写 19 个 prompt 文件（`prompts/*.md`） |
| 2.2 | 实现剩余 4 个 L1 + 5 个 L2 + 4 个 L3 + 2 个 L4 agent |
| 2.3 | 实现 `pipeline.py` 完整四层编排 |
| 2.4 | 建表：`macro_signals` + `sector_signals` + `iterative_daily_reports` |
| 2.5 | 端到端测试：完整管线跑一次 |

### Phase 3 — Meta Agent 自我进化（1 周）

| 步骤 | 内容 |
|------|------|
| 3.1 | 建表：`prompt_versions` |
| 3.2 | 实现 `meta_agent.py` |
| 3.3 | 实现 A/B 测试机制 |
| 3.4 | 实现验证期结算 |
| 3.5 | 注册 `meta_autoresearch` + `prompt_ab_settle` 到 TaskManager |

### Phase 4 — 前端 + API（1 周）

| 步骤 | 内容 |
|------|------|
| 4.1 | 新增 API 端点（7 个） |
| 4.2 | 前端"AI 迭代信号"页面 |
| 4.3 | Agent 健康度仪表盘 |
| 4.4 | 设置页增加 iterative 配置面板 |
| 4.5 | 定时调度接入 APScheduler |

---

## 十七、测试用例

### Scorecard（10 例）

| ID | 用例 | 预期 |
|----|------|------|
| SC-1 | 记录 L1 agent scorecard | agent_scorecards 新增 1 条，ticker=SPY |
| SC-2 | 记录 L3 agent scorecard | 4 个 L3 agent 各 1 条，ticker=AAPL |
| SC-3 | 5 天后回填 return_5d | price_5d 和 return_5d 正确 |
| SC-4 | 20 天后回填 return_20d | price_20d 和 return_20d 正确 |
| SC-5 | Sharpe 计算 | 与手动计算一致 |
| SC-6 | 命中率计算 | BUY+涨 / SELL+跌 / HOLD+横盘 |
| SC-7 | < 5 条数据不计算 | sharpe_30d 保持 NULL |
| SC-8 | 并发记录安全 | 3 个 agent 同时写不冲突 |
| SC-9 | 过期数据清理 | 90 天前的记录可清理 |
| SC-10 | prompt_version 关联 | testing 和 active 版本分别记录 |

### Darwinian 权重（5 例）

| ID | 用例 | 预期 |
|----|------|------|
| DW-1 | Top 25% 上调 | 新权重 = old × 1.05 |
| DW-2 | Bottom 25% 下调 | 新权重 = old × 0.95 |
| DW-3 | 边界限制 | 不超过 2.5 / 不低于 0.3 |
| DW-4 | 中间 50% 不变 | 权重保持 |
| DW-5 | CIO 注入权重 | CIO context 含权重信息 |

### Pipeline（8 例）

| ID | 用例 | 预期 |
|----|------|------|
| PL-1 | 完整 L1→L4 流程 | 返回 signals 列表 |
| PL-2 | L2 top_picks 汇入候选池 | 候选池 = watchlist ∪ top_picks |
| PL-3 | L3 对每只候选评分 | 4 × N 条 scorecard |
| PL-4 | L4 CIO 产出排名 | signals 按 conviction 降序 |
| PL-5 | Risk CRO 否决高风险 | 被否决的标的 risk_flag != null |
| PL-6 | progress_cb 调用 | 至少 5 次进度更新 |
| PL-7 | 空 watchlist | 仅依赖 L2 top_picks |
| PL-8 | 单只 agent 失败不影响整体 | 失败 agent score=0 + error rationale |

### Meta Agent（5 例）

| ID | 用例 | 预期 |
|----|------|------|
| MA-1 | 找最差 agent | 返回 Sharpe 最低者 |
| MA-2 | 生成新 prompt | 含 PROMPT_START/END 标记 |
| MA-3 | A/B 并行运行 | active 和 testing 各有 scorecard |
| MA-4 | Sharpe 改善 → activate | prompt_versions status 更新 |
| MA-5 | Sharpe 没改善 → retire | 旧版本继续使用 |

---

*方案 v2.0 结束。请审阅后确认。*
