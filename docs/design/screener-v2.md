# 智能选股 V2 技术方案 — Agent 驱动 · Guru 哲学

> **版本**: 1.0
> **日期**: 2026-04-15
> **依据**: `ARCHITECTURE_UPGRADE_PROPOSAL.md` + `demo_screener_v2.html`
> **范围**: 仅升级选股模块（`screener/`），不改动其他模块

---

## 一、目标与范围

### 1.1 升级目标

| # | 目标 | 衡量 |
|---|------|------|
| G1 | 从单一 AI 评估改为 **8 Agent 并行打分** | 每只股票有 8 个独立分数 |
| G2 | 引入 **投资大师哲学**（Buffett/Graham/Lynch/O'Neil/Munger/Marks/Soros/Simons） | 每只股票有 8 维大师匹配度 |
| G3 | **市场环境自适应权重**（牛/熊/震荡） | Regime Agent 自动切换权重 |
| G4 | **异步任务 + 留痕**（复用 TaskManager） | task_id 可回看，支持重试 |
| G5 | **数据源对齐架构方案**：Qwen 主力 + Local Cache + yfinance 兜底 | 零新数据源 |
| G6 | **自然语言查询**：Qwen 解析"AI 板块被低估成长股" → JSON filter | 可选，P1 |
| G7 | **透明化评分**：每 Agent 独立字母等级（Seeking Alpha 风格） | UI 显示归因 |

### 1.2 非目标（明确不做）

- ❌ **不动分析模块** (`agents/analyzer.py`)
- ❌ **不动持仓/预警/报告模块**
- ❌ **不改 TaskManager 核心**（只新增 screen_v2 worker 注册）
- ❌ **不引入新数据源**（IB/Polygon 依旧跳过，维持现状）
- ❌ **不做多 LLM provider**（只用现有 Qwen）

### 1.3 改动边界

| 可改 | 不可改 |
|------|--------|
| `screener/` 全部 | `agents/` |
| `web/app.py` 的 `/api/screen*` 路由 | `portfolio/` |
| `web/templates/index.html` 选股页 | `alerts/` `reports/` `strategy/` |
| `web/static/js/app.js` 选股相关函数 | 其他页面 |
| `web/static/css/style.css` 选股相关样式 | |

---

## 二、架构设计

### 2.1 模块组织

```
screener/
├── __init__.py
├── criteria.py                     ← 保留，补充 V2 字段
├── finviz_screener.py              ← 保留（V1 兼容 + V2 universe filter）
├── akshare_screener.py             ← 保留
├── ib_scanner.py                   ← 保留（已跳过不调用）
├── screener.py                     ← V1 保留，标记 deprecated
│
├── v2/                             ← 新增 V2 目录
│   ├── __init__.py
│   ├── orchestrator.py             ← V2 入口 (ScreenerV2)
│   ├── regime_detector.py          ← 市场环境分类
│   ├── universe.py                 ← Qwen 宇宙过滤
│   ├── aggregator.py               ← 聚合 8 Agent 分数 + 大师一致性
│   ├── nl_parser.py                ← 自然语言查询解析（P1）
│   │
│   ├── agents/                     ← 8 Agent
│   │   ├── __init__.py
│   │   ├── base.py                 ← BaseAgent 抽象基类
│   │   ├── momentum.py
│   │   ├── quality_value.py
│   │   ├── catalyst.py
│   │   ├── sentiment.py
│   │   ├── technical.py
│   │   ├── regime_relative.py
│   │   ├── guru.py                 ← 大师哲学聚合
│   │   └── risk.py
│   │
│   └── gurus/                      ← 8 大师哲学
│       ├── __init__.py
│       ├── base.py                 ← BaseGuru 抽象
│       ├── buffett.py
│       ├── graham.py
│       ├── lynch.py
│       ├── oneil.py
│       ├── munger.py
│       ├── marks.py
│       ├── soros.py
│       └── simons.py
```

**设计原则**：V1 和 V2 共存，通过配置 `screener.version` 切换。V1 保留以防回退。

### 2.2 数据流

```
┌─────────────────────────────────────────────────────────────┐
│ POST /api/screen/v2                                          │
│   body: {market, strategy, enabled_gurus[], nl_query?}       │
└───────────────────┬──────────────────────────────────────────┘
                    ↓
          TaskManager.submit("screen_v2", ...)
                    ↓
          [返回 task_id，立即响应]
                    ↓
          screen_v2_worker(params, progress_cb)
                    ↓
┌───────────────────────────────────────────────────────────┐
│ ScreenerV2.run()                                           │
│                                                             │
│ L0  [自然语言解析 (可选)]    nl_parser.parse(query)         │
│       → {sector, min_mcap, ...} filter JSON                │
│                                                             │
│ L1  [市场环境检测]          regime_detector.detect()        │
│       → regime="bull"/"bear"/"sideways", weights={}         │
│                                                             │
│ L2  [宇宙过滤 200 只]       universe.filter(market, cr)     │
│       数据源：Qwen screen_stocks 或 finviz + 本地规则       │
│                                                             │
│ L3  [8 Agent 并行评分 ★]   ThreadPoolExecutor(max=8)       │
│       每 Agent → {ticker, score 0-100, grade, rationale}    │
│                                                             │
│ L4  [8 Guru 打分]           同样并行，每大师独立规则引擎     │
│       每 Guru → {ticker, match_pct, fit/unfit}              │
│                                                             │
│ L5  [聚合排名 Top 20]       aggregator.aggregate(agents,    │
│       conviction = 0.5*agent_weighted +                     │
│                    0.15*agent_consensus +                   │
│                    0.20*guru_consistency +                  │
│                    0.15*debate_score (L6 填充)              │
│                                                             │
│ L6  [多空辩论终审 Top 5]    调 analyzer 做精细分析（可选）   │
│       注意：不改 analyzer，只调用                           │
│                                                             │
│ 全程 progress_cb 推送：                                     │
│   0%   → "市场环境检测中..."                                │
│   10%  → "宇宙过滤完成 (200 只)"                            │
│   20%→80% → "Agent 评分中..." (每完成一个 +10%)             │
│   85%  → "大师匹配度计算..."                                │
│   90%  → "聚合排名..."                                      │
│   95%  → "多空辩论终审..."                                  │
│   100% → Done                                               │
└───────────────────────────────────────────────────────────┘
                    ↓
          写入 screen_results_v2 表
                    ↓
          推送 task_completed + screen_v2_result WS 事件
```

### 2.3 8 Agent 职责与数据源

| Agent | 职责 | 数据源 | 关键指标 |
|-------|------|--------|----------|
| **MomentumAgent** | 动量 | Local Cache (bars) | 1/3/6/12M 收益率、MA 排列、52W 新高距离 |
| **QualityValueAgent** | 质量价值 | Qwen fundamentals | ROE、毛利率、FCF yield、PEG、债务比 |
| **CatalystAgent** | 事件催化 | Qwen news | 财报/指引/FDA/M&A/评级分类 + 强度 |
| **SentimentAgent** | 情绪 | Qwen web search | 评级修正、社交热度、Put/Call |
| **TechnicalAgent** | 技术指标 | Local Cache (bars) | RSI/MACD/布林带、形态、放量突破 |
| **RegimeRelativeAgent** | 环境与相对强度 | yfinance (SPY/ETF) + Local | VS SPY RS 排名、RRG 象限 |
| **GuruAgent** | 大师哲学聚合 | Qwen + 基本面 | 调用 8 gurus，返回聚合匹配度 |
| **RiskAgent** | 风险识别 | Local + Qwen | Beta、MDD、ATR、流动性、做空比 |

### 2.4 8 Guru 判断逻辑

每个 Guru 是**规则引擎 + LLM 校准**的混合：

| Guru | 判断规则（示意） |
|------|------------------|
| **Buffett** | ROE > 15% AND debt/equity < 0.5 AND FCF margin > 10% AND moat score (Qwen 评估) > 7/10 |
| **Graham** | P/E < 15 AND P/B < 1.5 AND current_ratio > 2 AND earnings stable 10y |
| **Lynch** | PEG < 1 AND revenue_growth > 20% AND niche leader (Qwen) |
| **O'Neil** | CANSLIM 7 字母 → EPS 加速、新高、RS > 80、机构增持 |
| **Munger** | 高质量 + 简单商业模式 + 管理层诚信（Qwen 评估） |
| **Marks** | 周期位置（VIX 高 + 行业估值低分位 → 加分） |
| **Soros** | 反身性信号（价格 + 基本面共振，宏观趋势强） |
| **Simons** | 统计异常（Z-score 偏离、均值回归概率） |

**输出**：每个 Guru 对每只股票返回 `{ticker, match_pct: 0-100, fit: true/false, reasoning: "..."}`。

### 2.5 Regime 权重表

| Regime | Momentum | Quality | Catalyst | Sentiment | Technical | RegimeRel | Guru | Risk |
|--------|----------|---------|----------|-----------|-----------|-----------|------|------|
| **Bull** | 0.20 | 0.10 | 0.12 | 0.10 | 0.12 | 0.15 | 0.10 | 0.11 |
| **Bear** | 0.08 | 0.22 | 0.10 | 0.08 | 0.10 | 0.10 | 0.20 | 0.12 |
| **Sideways** | 0.12 | 0.15 | 0.15 | 0.10 | 0.15 | 0.10 | 0.12 | 0.11 |

Bull 偏动量 + 相对强度；Bear 偏质量 + 大师（安全边际）；Sideways 均衡。

### 2.6 Regime 检测逻辑

读取 SPY 历史：
- **Bull**：SPY 在 200MA 上方 AND VIX < 20 AND 市场宽度 > 60%
- **Bear**：SPY 在 200MA 下方 OR VIX > 30
- **Sideways**：其他

VIX 和市场宽度通过 yfinance `^VIX` 获取，宽度用 SPY 成分股中高于 50MA 的比例近似（简化为"当前 vs 3M 高点"）。

---

## 三、数据库 schema 新增

```sql
-- 选股 V2 结果表
CREATE TABLE IF NOT EXISTS screen_results_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,                           -- 关联 tasks.id
    market TEXT,                            -- us|cn|all
    strategy TEXT,                          -- growth|value|...
    regime TEXT,                            -- bull|bear|sideways
    regime_confidence REAL,
    enabled_gurus TEXT,                     -- JSON array
    nl_query TEXT,                          -- 原始自然语言查询（若有）

    -- 完整结果（JSON）：top picks 列表
    -- 每只股票含：ticker, name, conviction, agent_scores{8}, guru_matches{8},
    --           horizon, risk_tag, bull_thesis, bear_thesis,
    --           entry/stop/target/rr
    results_json TEXT NOT NULL,

    universe_count INTEGER,                 -- L2 过滤后数量
    scored_count INTEGER,                   -- L3 评分数量
    final_count INTEGER,                    -- L6 最终输出数

    duration_ms INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_screen_v2_created ON screen_results_v2(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_screen_v2_task ON screen_results_v2(task_id);
```

**设计理由**：一整条记录 = 一次选股运行。不拆分 top picks 到单独表 — 结果是完整快照，不需关系查询。

---

## 四、API 设计

### 4.1 新增端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /api/screen/v2/submit` | POST | 提交选股任务，返回 `{task_id}` |
| `GET /api/screen/v2/result/:id` | GET | 查询 V2 结果（按 id 或 task_id） |
| `GET /api/screen/v2/history` | GET | V2 选股历史列表（轻量） |
| `GET /api/screen/v2/gurus` | GET | 列出 8 位大师元数据（用于前端面板） |

### 4.2 保留兼容端点

- `POST /api/screen` V1 保留（不动）— 根据 config `screener.version` 决定是否转发到 V2

### 4.3 submit 参数

```json
POST /api/screen/v2/submit
{
    "market": "us",
    "strategy": "growth",                       // 预设策略
    "enabled_gurus": ["buffett","lynch","oneil"], // 启用的大师
    "nl_query": "AI 板块被低估的成长股",          // 可选
    "final_count": 5,
    "skip_debate": true                           // 是否跳过 L6 多空辩论（加速）
}
```

### 4.4 result 返回

```json
{
    "id": 42,
    "task_id": "scr_v2_7f3a92...",
    "regime": "bull",
    "regime_confidence": 0.87,
    "weights": { "momentum": 0.20, ... },
    "duration_ms": 42800,
    "picks": [
        {
            "rank": 1,
            "ticker": "NVDA",
            "name": "NVIDIA Corp",
            "sector": "Semiconductors",
            "conviction": 89,
            "agent_scores": {
                "momentum": { "score": 94, "grade": "A+", "rationale": "..." },
                "quality_value": { "score": 88, "grade": "A", "rationale": "..." },
                ...
            },
            "guru_matches": {
                "buffett": { "match_pct": 61, "fit": false, "reason": "估值偏高" },
                "oneil": { "match_pct": 92, "fit": true, "reason": "CANSLIM 4/7 强标准" },
                ...
            },
            "bull_thesis": "AI 资本开支周期...",
            "bear_thesis": "估值已充分...",
            "horizon": "3-6 months",
            "risk_tag": "med",
            "entry": "$892-905",
            "stop": "$840",
            "target": "$1100",
            "risk_reward": 3.8
        }
    ]
}
```

### 4.5 WebSocket 事件

复用现有 TaskManager 事件：
- `task_created` / `task_progress` / `task_completed` / `task_failed`

前端监听 `task_progress.task_id === current_screen_task_id`，更新管线进度条 + Agent 卡片状态。

---

## 五、前端改造

### 5.1 原则

严格对齐 `demo_screener_v2.html`，**不自创样式**。复用现有 CSS 变量（`--accent-*`, `--font-mono` 等）。

### 5.2 HTML 改造点（`index.html` 选股页）

原页面的：
- 市场/策略下拉
- 3 层简单漏斗

替换为：
- 自然语言搜索框（顶部）
- 8 Guru 开关面板
- Regime 横幅
- 8 Agent 并行评分卡
- 筛选管线（4 步：宇宙/并行/聚合/辩论）
- Pick 卡片（含置信度环、8 Agent 分数、Guru 匹配徽章、交易计划）

### 5.3 JS 改造点（`app.js`）

新增函数：
- `async function runScreenV2()` — submit 任务，监听 WS 事件
- `function updateAgentCard(agent, status)` — 实时更新 Agent 卡片状态
- `function renderRegimeBanner(regime, confidence)` — 渲染环境横幅
- `function renderPicks(picks)` — 渲染 pick 卡片（置信度环、评分格子、大师徽章）
- `function toggleGuru(name)` — 开关大师
- `function parseNLQuery()` — 自然语言 → filter 预览

复用：
- 现有 Toast 系统
- 现有 `analyzeFromScreen(ticker)` 跳转
- 现有 `openHistoryDetail(id)` 弹窗（V2 结果也用同一弹窗）

### 5.4 CSS 改造点（`style.css`）

新增样式段落（从 demo 迁移）：
- `.guru-card` / `.guru-avatar` / `.guru-switch` / `.guru-principles` / `.guru-motto`
- `.agent-card` / `.agent-status` / `.agent-data-tag`
- `.regime-banner`
- `.pick-card` / `.conv-ring` / `.agent-scores` / `.score-cell` / `.grade-*`
- `.trade-plan`

---

## 六、实施阶段

### Phase 1（最小可用）— 2-3 天

1. ✅ 创建 `screener/v2/` 目录 + 占位文件
2. ✅ `regime_detector.py`（SPY + VIX 检测）
3. ✅ `universe.py`（复用 finviz，补充 Qwen 宇宙过滤）
4. ✅ `agents/base.py` + `momentum.py` + `technical.py`（纯本地数据，最先完成）
5. ✅ `agents/quality_value.py` + `catalyst.py` + `sentiment.py`（Qwen 数据）
6. ✅ `agents/regime_relative.py` + `risk.py`
7. ✅ `gurus/` 前 4 位（Buffett/Graham/Lynch/O'Neil，后 4 位留 TODO）
8. ✅ `agents/guru.py` 聚合
9. ✅ `aggregator.py`（权重聚合 + 置信度公式）
10. ✅ `orchestrator.py`（入口 + progress_cb）
11. ✅ `task_store` 新增 `screen_v2_worker` 注册
12. ✅ API 路由（submit/result/history/gurus）
13. ✅ DB schema migration（`screen_results_v2`）

### Phase 2（UI）— 2 天

1. ✅ HTML 模板改造
2. ✅ JS 函数实现
3. ✅ CSS 样式迁移
4. ✅ WS 事件对接

### Phase 3（增强）— 可选 1-2 天

1. ⏳ `nl_parser.py`（自然语言查询）
2. ⏳ 其余 4 位大师（Munger/Marks/Soros/Simons）
3. ⏳ L6 多空辩论接入

---

## 七、关键实现细节

### 7.1 Agent 抽象基类

```python
# screener/v2/agents/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class AgentScore:
    score: float          # 0-100
    grade: str            # A+, A, B+, B, C, D+, D, F
    rationale: str        # 一句话说明
    signals: dict         # 关键指标详情

class BaseAgent(ABC):
    name: str
    data_source: str      # "local_cache" | "qwen" | "yfinance" | "mixed"

    @abstractmethod
    def score(self, ticker: str, context: dict) -> AgentScore: ...

    @staticmethod
    def to_grade(score: float) -> str:
        if score >= 93: return "A+"
        if score >= 87: return "A"
        if score >= 80: return "B+"
        if score >= 73: return "B"
        if score >= 66: return "C+"
        if score >= 60: return "C"
        if score >= 50: return "D+"
        if score >= 40: return "D"
        return "F"
```

### 7.2 Orchestrator 核心流程

```python
# screener/v2/orchestrator.py
class ScreenerV2:
    def __init__(self, config):
        self.regime_detector = RegimeDetector(config)
        self.universe = UniverseFilter(config)
        self.agents = {
            "momentum": MomentumAgent(config),
            "quality_value": QualityValueAgent(config),
            # ...
        }
        self.gurus = load_enabled_gurus(config)
        self.aggregator = Aggregator()

    def run(self, params: dict, progress_cb) -> dict:
        progress_cb(5, "检测市场环境")
        regime = self.regime_detector.detect()

        progress_cb(10, f"宇宙过滤中（{params.get('market')}）")
        candidates = self.universe.filter(params)

        progress_cb(20, f"8 Agent 并行评分（共 {len(candidates)} 只）")
        scored = self._parallel_score(candidates, regime, progress_cb)

        progress_cb(85, "大师哲学匹配")
        guru_matches = self._score_gurus(scored, params.get("enabled_gurus"))

        progress_cb(90, "聚合排名")
        picks = self.aggregator.aggregate(scored, guru_matches, regime.weights)
        top = picks[: params.get("final_count", 5)]

        progress_cb(95, "生成交易计划")
        top = self._enrich_trade_plan(top)

        progress_cb(100, "完成")
        return {
            "regime": regime.label,
            "regime_confidence": regime.confidence,
            "weights": regime.weights,
            "picks": top,
        }
```

### 7.3 Worker 注册

```python
# web/app.py - _register_default_workers
def screen_v2_worker(params, progress_cb):
    from stock_trading_system.screener.v2.orchestrator import ScreenerV2
    sv2 = _get_screener_v2()  # lazy
    result = sv2.run(params, progress_cb)
    # 持久化
    sid = _get_task_store().save_screen_v2_result(...)
    return {"result_ref": f"screen_results_v2:{sid}", "picks_count": len(result["picks"])}

tm.register("screen_v2", screen_v2_worker)
```

### 7.4 并行评分实现

```python
def _parallel_score(self, tickers, regime, progress_cb):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}  # ticker -> {agent_name -> AgentScore}

    with ThreadPoolExecutor(max_workers=8) as pool:
        # 每个 Agent 评分所有 tickers（Agent 内部可再并发）
        futures = {
            pool.submit(agent.score_batch, tickers): name
            for name, agent in self.agents.items()
        }
        done_count = 0
        total = len(futures)
        for f in as_completed(futures):
            agent_name = futures[f]
            scores_by_ticker = f.result()
            for ticker, s in scores_by_ticker.items():
                results.setdefault(ticker, {})[agent_name] = s
            done_count += 1
            pct = 20 + int((done_count / total) * 65)  # 20→85
            progress_cb(pct, f"{agent_name} 完成")
    return results
```

---

## 八、配置扩展

```yaml
# ~/.stock_trading/config.yaml
screener:
  version: "v2"                      # v1 | v2
  v2:
    default_final_count: 5
    skip_debate: true                # 跳过 L6 多空辩论（默认启用）
    enabled_gurus:                   # 默认启用的大师
      - buffett
      - lynch
      - oneil
    regime_detection:
      spy_ma_period: 200
      vix_bull_threshold: 20
      vix_bear_threshold: 30
    cache:
      fundamentals_ttl: 86400        # 24h
      news_ttl: 3600                 # 1h
      regime_ttl: 1800               # 30min
    weights:
      bull:   { momentum: 0.20, quality: 0.10, ... }
      bear:   { momentum: 0.08, quality: 0.22, ... }
      sideways: { ... }
```

---

## 九、依赖与风险

### 9.1 新依赖

**无**。所有功能基于现有库：pandas、yfinance、openai（Qwen）、flask、socketio。

### 9.2 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Qwen 批量调用超限 | 中 | 高 | 单轮选股 Agent 用一次大 prompt 批量评分，非逐只调用 |
| 选股耗时过长 (>5min) | 中 | 中 | `skip_debate=true` 默认开启，L6 辩论改为可选 |
| 大师规则过于严格无匹配 | 中 | 低 | match_pct 使用连续值而非布尔，低匹配仍显示 |
| Regime 误判 | 低 | 中 | regime_confidence < 0.6 时用 sideways 权重 |
| 前端 Task WS 丢失事件 | 低 | 低 | 补偿：定时轮询 `/api/tasks/:id` |

---

## 十、核心文件清单

| 文件 | 新增/修改 | 行数估计 |
|------|-----------|----------|
| `screener/v2/orchestrator.py` | 新增 | ~200 |
| `screener/v2/regime_detector.py` | 新增 | ~100 |
| `screener/v2/universe.py` | 新增 | ~80 |
| `screener/v2/aggregator.py` | 新增 | ~120 |
| `screener/v2/agents/base.py` | 新增 | ~60 |
| `screener/v2/agents/*.py` (×8) | 新增 | ~100 each |
| `screener/v2/gurus/base.py` | 新增 | ~40 |
| `screener/v2/gurus/*.py` (×4 Phase1) | 新增 | ~80 each |
| `web/app.py` | 修改 | +80 行 |
| `tasks/task_store.py` | 修改 | +30 行 (save_screen_v2_result) |
| `web/templates/index.html` | 修改 | 选股页重写 ~300 行 |
| `web/static/js/app.js` | 修改 | 选股相关函数重写 ~400 行 |
| `web/static/css/style.css` | 修改 | +400 行（从 demo 迁移） |

**总估算**：新增约 1800 行后端 + 1100 行前端 = **~2900 行**。

---

*文档结束*

---

# 方案修订 V1.1 — NL 驱动优先

> **修订日期**: 2026-04-16
> **动因**: 用户反馈"选股应该按 NL 输入来，strategy chip 只是辅助提示"

---

## 十一、核心流程调整

### 11.1 新旧对比

**旧流程（V1.0）**：
```
用户选 market + strategy ("成长动能")
  → UniverseFilter 按策略映射固定筛选条件
  → 拿到 ~40 只默认股票
  → 8 Agent 评分
  → 聚合排名
```
问题：**strategy 字段硬编码，NL 输入只是"装饰"**，实际根本没用到。

**新流程（V1.1）**：
```
用户输入自然语言（"AI 板块被低估的成长股"）
  → L0 NL Parser (Qwen): NL → FilterSpec JSON
  → L1 Regime Detector（不变）
  → L2 Universe Filter：按 FilterSpec 走 Qwen universe → 候选股票列表
  → L3 8 Agent 评分（不变）
  → L4 Guru 评估（不变）
  → L5 聚合排名（不变）
```

### 11.2 FilterSpec 规范

NL Parser 必须产出以下 JSON（Qwen `response_format=json_object`）：

```json
{
    "intent_summary": "AI 板块低估成长股",
    "market": "us",                      // us | cn
    "sectors": ["Technology", "Semiconductors"],
    "themes": ["AI", "Cloud Computing"],
    "criteria": {
        "min_market_cap": 5000000000,    // nullable
        "max_market_cap": null,
        "max_pe": 40,
        "min_pe": null,
        "min_revenue_growth_pct": 15,    // percent
        "max_pb": null,
        "min_roe_pct": null,
        "min_price": 5,
        "recent_signal": null             // e.g. "positive_earnings_revision"
    },
    "exclude_tickers": [],
    "target_count": 30,                   // universe 初筛目标数
    "natural_fallback": ["AI chip stocks", "Large cap tech"]
}
```

### 11.3 执行策略（二级回退）

```
Layer A — Qwen universe query
    使用 Qwen screen_stocks(criteria_text, count=target_count)
    直接返回 ticker 列表（Qwen 联网搜索 + 筛选）
    适合：主题股 / 板块股 / 特殊条件

Layer B — Heuristic narrow
    如果 Qwen 不可用或返回为空:
    - Exchange: 根据 market 选 US (NASDAQ+NYSE top 300) 或 CN (沪深 300)
    - 按 FilterSpec.criteria 用本地市值/PE/PB/ROE 数据做本地筛选
    - 按 sectors 过滤（如果给出）

Layer C — Default fallback
    两层都失败时退到 40 只大盘股默认列表（保持 V1 行为）
```

---

## 十二、模块变更清单

### 12.1 新增

`screener/v2/nl_parser.py`
- `NLParser.parse(query: str, market_hint: str | None) -> FilterSpec`
- 调用 Qwen：固定 system prompt，`response_format=json_object`，强制返回合法 JSON
- 失败时返回 `FilterSpec` 空对象 + `natural_fallback=[query]`
- 缓存 key = `hash(query)`，TTL 10 分钟（同一 query 复用解析结果）

### 12.2 修改

`screener/v2/universe.py`（大改）
- 新接口：`filter(spec: FilterSpec) -> list[str]`
- 执行上面三层回退
- 使用现有 `QwenProvider.screen_stocks` 做 Layer A
- Layer B 复用 `DataHelper.get_fundamentals` 过滤

`screener/v2/orchestrator.py`
- 新增 L0 步骤：`nl = self._nl_parser.parse(params.nl_query)` → `filter_spec`
- L2 改为 `self._universe.filter(filter_spec)`
- 把 `filter_spec` 透传到 `context`，让 Agent 能感知（例如 CatalystAgent 可以针对 `recent_signal`）
- 把 `intent_summary` 保存到结果，前端展示"AI 理解你的意图是..."

### 12.3 前端调整

HTML 选股页：
- **NL 输入框升级为"主行动输入"**（更大、更显眼）
- **Market / Strategy 下拉退化为"可选提示"**（右侧次要按钮，用户不填也能用）
- **新增"AI 理解"徽章**：结果返回后显示 `intent_summary`（"已按 AI 板块低估成长股 筛选"）

JS：
- `runScreenV2` 不再强制要 strategy，只要 `nl_query` 或 `strategy` 之一
- 结果渲染时显示 intent_summary badge

---

## 十三、FilterSpec 示例（真实用例）

| 用户输入 | Qwen 解析输出（摘要） |
|----------|---------------------|
| "AI 板块被低估的成长股" | `sectors=[Tech,Semi], themes=[AI], max_pe=40, min_revenue_growth_pct=15` |
| "近期突破新高、机构增持的中概股" | `market=cn, criteria.recent_signal=new_high_volume, target_count=20` |
| "股息高、低 Beta、稳健型大盘股" | `min_market_cap=20e9, criteria.min_dividend_yield_pct=3, max_beta=1` |
| "有回购计划、现金流稳定的公司" | `criteria.recent_signal=buyback, min_fcf_yield_pct=5` |
| （空输入） | 回退到 `market` 参数 + 默认大盘股，等同旧流程 |

---

## 十四、测试用例补充

| ID | 用例 | 预期 |
|----|------|------|
| NL-1 | 中文 NL 解析 | "AI 板块低估成长股" → FilterSpec.sectors 含 Tech |
| NL-2 | 英文 NL 解析 | "undervalued AI growth stocks" → 同上 |
| NL-3 | 空 NL | FilterSpec 只有 market + 默认 target_count |
| NL-4 | Qwen 失败 | 降级到 Layer B，不报错 |
| NL-5 | 参数冲突 | NL 说"低 PE"但同时 user 勾了"成长动能" → NL 优先 |
| NL-6 | 缓存命中 | 同一 query 10min 内二次调用 → 不再请 Qwen |
| NL-7 | universe 空 | Qwen 返回 0 只 → 前端显示"意图过窄，已尝试宽松匹配" |
| NL-8 | intent_summary 展示 | 前端结果页显示 AI 理解徽章 |

---

## 十五、实施顺序

1. ✅ 更新方案文档（本章节）
2. ✅ 新增 `screener/v2/nl_parser.py`
3. ✅ 改造 `universe.py`（三层回退）
4. ✅ 改造 `orchestrator.py`（L0 步骤）
5. ✅ 前端 HTML + JS：NL 输入为主，strategy 退化为 hint
6. ✅ 端到端测试一条 NL 查询

*修订完成*
