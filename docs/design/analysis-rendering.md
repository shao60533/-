# 技术方案：AI 分析结构化渲染

| 项 | 值 |
|---|---|
| Feature | `analysis-rendering` |
| 版本 | v1.0 |
| 日期 | 2026-05-01 |
| 关联 | [ui-react-island-regression v1.13 R-fix-7E](./ui-react-island-regression.md)（8 tab 切分）+ [paper-trade v1.3 F3](./paper-trade.md)（已用 `with_structured_output(ExecutiveSummary)` 验证可行）|
| 关联测试 | `tests/agents/test_rendering_extractor.py`、`tests/web/test_analysis_rendering.py`、`tests/frontend/analysis-cards.spec.ts` |

## 1. 背景

当前 `/analysis/<id>` 8 个 tab 直接把 LLM 输出的 markdown 喂给 `react-markdown + remark-gfm + rehype-sanitize`（v1.13 R-fix-7F 通道）。问题：
1. 决策结论（评级 / 行动方向 / 关键数字）被埋在长文里
2. "三派辩论""核心决策依据"应是卡片网格 / 编号步骤，现在是连续段落
3. 关键 KPI（PE / RSI / VIX / 价位）应突出，markdown 表格扁平显示
4. 长文与结论权重一致，扫读不到重点

## 2. 总览

**分层渲染**：每个 tab = `结构化卡片头`（结论/数字/网格） + `Markdown 主体`（论述/细节，折叠）。

- LLM 在 analyzer 完成 7 agent 报告之后做一次**抽取后处理**：用 quick_think_llm + `with_structured_output` 把每个报告 markdown → 该 tab 的 Pydantic schema → JSON
- 结果存到 `analysis_history.rendering_json`（共享研究字段，不含个人 advice）
- 前端拿到 JSON 优先渲染专属卡片组件；JSON 缺失或单 tab key 为 null 时降级到原 markdown（保持现状）
- 长文 markdown 块保留为**可折叠详情区**，默认关闭

## 3. 边界

### 共享 vs 私有（与 v1.13 R-fix-7D 一致）

`rendering_json` 是**共享研究字段**：
- 评级 / 信号方向 / 技术面价位（支撑 / 阻力 / 关键 SMA） / KPI / 三派辩论 / 风险评估 ✅
- 个人仓位百分比 / 个人 entry price / 个人 stop loss / 个人 take profit / 反映持仓的 advice ❌（这些走 `user_analysis_advice`）

"决策" tab 的 `entry_zone / stop_loss / take_profit` 来自**技术面分析的客观价位**（如 "200-SMA $50.44 是结构性止损位"），不是基于用户持仓的个性化 advice。两者本来就不同源——`StrategyEngine.generate_advice(result, holdings, current_price)` 才是个人化推荐。

### 不改的现状（强约束）

- 不改 `markdown` 主路径（react-markdown + remark-gfm + rehype-sanitize）—— 始终保留作 fallback
- 不改 v1.13 R-fix-7B 元数据列 / R-fix-7D 私有 advice 表 / R-fix-7C TaskStore 后门
- 不在 rendering 流程做 LLM provider 切换（沿用 analyzer 当前 active provider）
- 抽取失败不阻断分析任务（best-effort，写空 + 前端降级）

## 4. 数据模型

### 4.1 schema 总览（8 tab）

| Tab key | Schema | 关键字段 |
|---|---|---|
| `summary` | `OverviewCard` | rating / action_direction / confidence / key_metrics / debate_synthesis / decision_drivers / one_line_takeaway |
| `Market` | `MarketCard` | trend / indicators / support_resistance / patterns / summary |
| `Sentiment` | `SentimentCard` | mood / mood_score / drivers / contrarian_signal / summary |
| `News` | `NewsCard` | headlines / catalysts / summary |
| `Fundamentals` | `FundamentalsCard` | valuation / growth / profitability / balance_sheet / quality_score / summary |
| `Investment Debate` | `DebateCard` | bull_arguments / bear_arguments / neutral_synthesis / verdict |
| `Risk Assessment` | `RiskCard` | aggressive / conservative / neutral × Stance + verdict + top_risks |
| `Decision` | `DecisionCard` | final_action / conviction / entry_zone / structural_stop / take_profit_levels / time_horizon / preconditions / exit_conditions / alternative_scenarios |

### 4.2 Pydantic 详细 schema

```python
# stock_trading_system/agents/rendering/schemas.py
from typing import Literal
from pydantic import BaseModel, Field


# ── 共享 helper ───────────────────────────────────────────
class KeyMetric(BaseModel):
    label: str = Field(..., description="指标名，如 '现价 / 200-SMA'")
    value: str = Field(..., description="格式化后字符串，如 '$61.86 / $50.44 (+22.6%)'")
    tone: Literal["positive", "negative", "neutral"] = "neutral"
    hint: str | None = None  # 鼠标悬浮说明


class Stance(BaseModel):
    """三派之一的论点 / 证据 / 局限。"""
    claim: str
    evidence: str
    limitation: str


class Argument(BaseModel):
    """单条多空论点。"""
    claim: str
    evidence: str
    weight: Literal["primary", "secondary", "tertiary"] = "secondary"


# ── Tab 1: Overview ──────────────────────────────────────
RatingLiteral = Literal[
    "Strong Buy", "Buy", "Overweight", "Hold",
    "Underweight", "Sell", "Strong Sell",
]
ConfLiteral = Literal["high", "medium", "low"]


class DebateSynthesis(BaseModel):
    aggressive: Stance
    conservative: Stance
    neutral: Stance
    verdict: str = Field(..., description="综合判断段落,1-3 句")


class DecisionDriver(BaseModel):
    headline: str = Field(..., description="一句话标题,如 '技术延伸与动量疲劳'")
    detail: str = Field(..., description="1-3 句论据 + 关键数字")


class OverviewCard(BaseModel):
    rating: RatingLiteral
    action_direction: str = Field(..., description="一句话执行方向,可含数字")
    confidence: ConfLiteral
    key_metrics: list[KeyMetric] = Field(default_factory=list, max_length=6)
    debate_synthesis: DebateSynthesis | None = None
    decision_drivers: list[DecisionDriver] = Field(default_factory=list, max_length=5)
    one_line_takeaway: str


# ── Tab 2: Market (技术面) ────────────────────────────────
TrendLiteral = Literal["bullish", "bearish", "neutral", "range"]


class TechnicalIndicator(BaseModel):
    name: str          # RSI / MACD / Bollinger / ATR / SMA50/200
    value: str         # "70.2" / "顶背离" / "$67.68 上轨"
    signal: Literal["bullish", "bearish", "neutral"]


class PriceLevel(BaseModel):
    price: float
    kind: Literal["support", "resistance", "pivot"]
    strength: Literal["strong", "medium", "weak"] = "medium"
    note: str | None = None  # "200-SMA" / "前期高点"


class MarketCard(BaseModel):
    trend: TrendLiteral
    indicators: list[TechnicalIndicator] = Field(default_factory=list, max_length=8)
    support_resistance: list[PriceLevel] = Field(default_factory=list, max_length=6)
    patterns: list[str] = Field(default_factory=list, max_length=4)
    summary: str = Field(..., description="1-3 句技术面综述")


# ── Tab 3: Sentiment ─────────────────────────────────────
MoodLiteral = Literal["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]


class SentimentDriver(BaseModel):
    source: Literal["news", "social", "options", "analyst", "insider"]
    theme: str
    polarity: Literal["bullish", "bearish", "mixed"]


class SentimentCard(BaseModel):
    mood: MoodLiteral
    mood_score: int = Field(..., ge=-100, le=100)
    drivers: list[SentimentDriver] = Field(default_factory=list, max_length=5)
    contrarian_signal: bool = False
    contrarian_reason: str | None = None
    summary: str


# ── Tab 4: News ──────────────────────────────────────────
class Headline(BaseModel):
    title: str
    source: str | None = None
    date: str | None = None  # YYYY-MM-DD
    sentiment: Literal["bullish", "bearish", "neutral"] = "neutral"
    impact: Literal["high", "medium", "low"] = "medium"


class Catalyst(BaseModel):
    kind: Literal["earnings", "macro", "sector", "company", "regulatory"]
    summary: str
    date: str | None = None


class NewsCard(BaseModel):
    headlines: list[Headline] = Field(default_factory=list, max_length=8)
    catalysts: list[Catalyst] = Field(default_factory=list, max_length=5)
    summary: str


# ── Tab 5: Fundamentals ──────────────────────────────────
class Valuation(BaseModel):
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_ebitda: float | None = None
    peg: float | None = None
    vs_industry: str | None = None  # "PE 高于行业 30%"


class Growth(BaseModel):
    revenue_yoy_pct: float | None = None
    eps_yoy_pct: float | None = None
    fcf_yoy_pct: float | None = None


class Profitability(BaseModel):
    gross_margin_pct: float | None = None
    op_margin_pct: float | None = None
    roe_pct: float | None = None
    roic_pct: float | None = None


class BalanceSheet(BaseModel):
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    cash_ratio: float | None = None


class FundamentalsCard(BaseModel):
    valuation: Valuation = Field(default_factory=Valuation)
    growth: Growth = Field(default_factory=Growth)
    profitability: Profitability = Field(default_factory=Profitability)
    balance_sheet: BalanceSheet = Field(default_factory=BalanceSheet)
    quality_score: int = Field(3, ge=1, le=5)
    summary: str


# ── Tab 6: Investment Debate ─────────────────────────────
class DebateCard(BaseModel):
    bull_arguments: list[Argument] = Field(default_factory=list, max_length=5)
    bear_arguments: list[Argument] = Field(default_factory=list, max_length=5)
    neutral_synthesis: str
    verdict: Literal["bull", "bear", "draw"]
    key_disagreement: str = Field(..., description="一句话点出最核心分歧")


# ── Tab 7: Risk Assessment ───────────────────────────────
class TopRisk(BaseModel):
    risk: str
    probability: Literal["high", "medium", "low"]
    severity: Literal["high", "medium", "low"]
    mitigation: str | None = None


class RiskCard(BaseModel):
    aggressive: Stance
    conservative: Stance
    neutral: Stance
    verdict: str
    top_risks: list[TopRisk] = Field(default_factory=list, max_length=5)


# ── Tab 8: Decision ──────────────────────────────────────
ActionLiteral = Literal["BUY", "SELL", "HOLD", "REDUCE", "ADD", "WAIT"]
HorizonLiteral = Literal["intraday", "swing", "short", "medium", "long"]


class PriceZone(BaseModel):
    low: float
    high: float


class TakeProfitLevel(BaseModel):
    price: float
    weight_pct: int = Field(..., ge=1, le=100)  # 该档止盈占比
    rationale: str | None = None


class AlternativeScenario(BaseModel):
    condition: str       # "若跌破 $58.50"
    action: str          # "全部减仓 + 等待重新介入"


class DecisionCard(BaseModel):
    final_action: ActionLiteral
    conviction: ConfLiteral
    entry_zone: PriceZone | None = None
    structural_stop: float | None = None
    take_profit_levels: list[TakeProfitLevel] = Field(default_factory=list, max_length=4)
    time_horizon: HorizonLiteral
    preconditions: list[str] = Field(default_factory=list, max_length=4)
    exit_conditions: list[str] = Field(default_factory=list, max_length=4)
    alternative_scenarios: list[AlternativeScenario] = Field(default_factory=list, max_length=3)
    one_line_summary: str
```

### 4.3 存储

`analysis_history` 加 1 列：

```sql
rendering_json TEXT  -- JSON: { "summary": OverviewCard, "Market": MarketCard, ... }
```

每 tab 一个 key（与 `REPORT_TABS.key` 严格一致），单 tab 抽取失败时该 key 写 `null`，前端按 key 缺失/null 降级到 markdown。**不**为每 tab 单建一列——保持 schema 演进灵活。

幂等迁移：`_migrate_analysis_history.additions` 追加 `("rendering_json", "TEXT")`。

## 5. 抽取流程

```python
# stock_trading_system/agents/rendering/extractor.py
class RenderingExtractor:
    def __init__(self, llm):
        # llm 来自 analyzer 当前 active provider 的 quick_think_llm
        # （与 analyzer._configure_qwen / _configure_gemini 一致）
        self._llm = llm

    def extract(self, result: AnalysisResult) -> dict:
        """Return {tab_key: dict | None}. Each tab failure is isolated."""
        tasks = [
            ("summary",            OverviewCard,     self._build_overview_input(result)),
            ("Market",             MarketCard,       result.market_report or ""),
            ("Sentiment",          SentimentCard,    result.sentiment_report or ""),
            ("News",               NewsCard,         result.news_report or ""),
            ("Fundamentals",       FundamentalsCard, result.fundamentals_report or ""),
            ("Investment Debate",  DebateCard,       str(result.investment_debate or "")),
            ("Risk Assessment",    RiskCard,         str(result.risk_assessment or "")),
            ("Decision",           DecisionCard,     str(result.trade_decision or "")),
        ]
        out: dict = {}
        # 8 calls 并发执行（asyncio.gather 或 ThreadPoolExecutor.max_workers=8）
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(self._extract_one, schema, prompt, key): key
                for (key, schema, prompt) in tasks
            }
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    out[key] = fut.result(timeout=45).model_dump()
                except Exception as e:
                    logger.warning("rendering extract %s failed: %s", key, e)
                    out[key] = None
        return out

    def _extract_one(self, schema, prompt_input, key):
        structured = self._llm.with_structured_output(schema)
        sys = (
            "You convert a stock-analysis report into a strict JSON schema. "
            "Use ONLY information present in the input — never invent prices, "
            "indicator values, or news. If a field is unknown, leave it null "
            "(or omit if optional). Return concise text suitable for UI cards "
            "(verdict 1-3 sentences, claim 1 sentence, evidence 1-2 sentences)."
        )
        return structured.invoke([
            {"role": "system", "content": sys},
            {"role": "user",   "content": f"[REPORT — {key}]\n{prompt_input}"},
        ])

    def _build_overview_input(self, result):
        # Overview 综合 7 个报告,需要全文输入。其它 tab 各取本报告。
        return "\n\n".join([
            f"## Market\n{result.market_report or ''}",
            f"## Sentiment\n{result.sentiment_report or ''}",
            f"## News\n{result.news_report or ''}",
            f"## Fundamentals\n{result.fundamentals_report or ''}",
            f"## Debate\n{result.investment_debate or ''}",
            f"## Risk\n{result.risk_assessment or ''}",
            f"## Decision\n{result.trade_decision or ''}",
        ])
```

`StockAnalyzer.analyze` 在 `progress_cb({"type":"pipeline_done"})` 之前插入：

```python
        # ── Structured rendering extraction (best-effort) ────────────
        try:
            from stock_trading_system.agents.rendering.extractor import RenderingExtractor
            llm = self._build_quick_llm()  # 沿用 _configure_qwen/_configure_gemini 的 quick_think 配置
            rendering = RenderingExtractor(llm).extract(result)
            result.rendering = rendering   # 挂在 dataclass 上,供 worker 序列化
        except Exception as e:
            logger.warning("rendering extraction failed (non-fatal): %s", e)
            result.rendering = {}
```

`AnalysisResult` dataclass 加字段 `rendering: dict = field(default_factory=dict)`。

worker 序列化：

```python
# workers.py make_analysis_worker
out["rendering_json"] = json.dumps(getattr(result, "rendering", {}) or {},
                                     ensure_ascii=False)
```

`TaskStore._save_analysis_result` INSERT 加 `result.get("rendering_json", "")`。

`PortfolioDatabase.save_analysis` 同步加列写入。

## 6. 前端

### 6.1 组件清单

```
src/components/analysis/
├── shared/
│   ├── RatingBadge.tsx          // 7 档评级 + 配色
│   ├── KpiRow.tsx               // KeyMetric[] grid
│   ├── StanceCard.tsx           // 三派 stance 一卡 (claim/evidence/limitation)
│   ├── ConfidenceMeter.tsx      // high/medium/low 圆环
│   └── MoodGauge.tsx            // mood_score -100..100 半圆
├── OverviewCard.tsx
├── MarketCard.tsx
├── SentimentCard.tsx
├── NewsCard.tsx
├── FundamentalsCard.tsx
├── DebateCard.tsx
├── RiskCard.tsx
└── DecisionCard.tsx
```

### 6.2 Tab 渲染骨架

`AnalysisDetailView` 每个 `<TabsContent>`：

```tsx
const renderingForTab: Record<string, React.FC<{data:any}>> = {
  "summary":            OverviewCard,
  "Market":             MarketCard,
  "Sentiment":          SentimentCard,
  "News":               NewsCard,
  "Fundamentals":       FundamentalsCard,
  "Investment Debate":  DebateCard,
  "Risk Assessment":    RiskCard,
  "Decision":           DecisionCard,
}

REPORT_TABS.map(tab => {
  const md = reportContent[tab.key] || ""
  const struct = detail.rendering?.[tab.key]
  const Card = renderingForTab[tab.key]
  return (
    <TabsContent key={tab.key} value={tab.key} className="mt-4 space-y-4">
      {struct && Card ? <Card data={struct} /> : null}
      {md ? (
        <details className="rounded border border-border/50">
          <summary className="cursor-pointer px-4 py-2 text-xs text-muted-foreground">
            完整论述（点击展开）
          </summary>
          <div className="prose prose-invert prose-sm max-w-none px-4 py-3">
            <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSanitize, mdSchema]]}>
              {md}
            </Markdown>
          </div>
        </details>
      ) : (!struct && <p className="text-sm text-muted-foreground py-8 text-center">暂无数据</p>)}
    </TabsContent>
  )
})
```

### 6.3 OverviewCard 视觉契约（参考截图诊断）

```
┌─决策横幅─────────────────────────────────────────────────────┐
│ [TQQQ] [Underweight: 大字 + 红色 Badge] [Conf: 中  半圆环]   │
│ 📍 减仓现有头寸 30–40%, 停止市价追多, 等待统计优势区间       │
│                                                              │
│ ┌─KPI 行: 4-6 张窄卡片───────────────────────────────────┐ │
│ │ 现价 / SMA200    MACD 信号    RSI       VIX     ATR   │ │
│ │ $61.86 / +22.6%  顶背离       70.2     ~18    $2.40   │ │
│ │   (negative)    (negative)  (negative)(neutral)(neutral)│ │
│ └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘

┌─三派辩论 (3-col grid in DebateSynthesis)─────────────────────┐
│ ┌─🔥 激进派────┐ ┌─🛡️ 保守派────┐ ┌─⚖️ 中立派────┐         │
│ │ 论点         │ │ 论点         │ │ 论点         │         │
│ │ ────         │ │ ────         │ │ ────         │         │
│ │ 证据         │ │ 证据         │ │ 证据         │         │
│ │ ────         │ │ ────         │ │ ────         │         │
│ │ 局限         │ │ 局限         │ │ 局限         │         │
│ └──────────────┘ └──────────────┘ └──────────────┘         │
│ ┃ 综合判断: …  (highlighted callout)                  ┃     │
└──────────────────────────────────────────────────────────────┘

┌─核心决策依据 (numbered)──────────────────────────────────────┐
│ ① 技术延伸与动量疲劳                                         │
│   TQQQ 较 200-SMA 偏离 22.6%, MACD 顶背离…                  │
│ ② 杠杆衰减的数学不可避免性                                   │
│   每日重置在 ATR $2.40 环境下…                              │
│ ③ 宏观风险叠加                                              │
│   VIX~18, 油价破百, 隔夜跳空高发期…                         │
└──────────────────────────────────────────────────────────────┘

[完整论述 ▼]  ← <details> 折叠老 markdown
```

### 6.4 其它 7 个 Card 的视觉契约（要点）

- **MarketCard** — TrendBadge + IndicatorChip 列表 + SupportResistance 价位轴 + Patterns chip + 1-3 句 summary
- **SentimentCard** — MoodGauge（半圆 -100..100） + DriverList（带 source 图标） + ContrarianBanner（如有）+ summary
- **NewsCard** — Headlines 列表（每条 sentiment dot + impact 高度条） + Catalyst Timeline + summary
- **FundamentalsCard** — 4 列 KPI 块（Valuation/Growth/Profit/Balance）+ QualityScore 5 星 + summary
- **DebateCard** — 左右双栏（看多 / 看空 Argument 列表，weight 排序）+ verdict Badge + key_disagreement callout + neutral_synthesis 段
- **RiskCard** — 复用 Overview 的三派 grid + TopRisks 表格（probability×severity 矩阵着色） + verdict
- **DecisionCard** — ActionBadge 大字 + ConvictionMeter + EntryZone bar + StopLoss line + TakeProfit 多档 weight + Horizon chip + Preconditions / ExitConditions checklist + Scenarios 表

## 7. 后端契约改动

### 7.1 新建 module

```
stock_trading_system/agents/rendering/
├── __init__.py
├── schemas.py        # 8 Pydantic schemas + helpers
└── extractor.py      # RenderingExtractor + ThreadPoolExecutor 并发
```

### 7.2 PortfolioDatabase + TaskStore

- `analysis_history` 加 `rendering_json TEXT` 列 + idempotent ALTER（v1.13 R-fix-7B 同款）
- `save_analysis` INSERT 加 `data.get("rendering_json", "")`
- TaskStore `_ensure_analysis_history_table` CREATE TABLE 同步加列；`_save_analysis_result` INSERT 加 `result.get("rendering_json", "")`

### 7.3 详情 DTO

`history_detail_dto`（v1.18 R-fix-12A）补字段：

```python
DETAIL_REPORT_FIELDS = (... 现有 ..., "rendering_json")
# DTO 解析:
rendering = {}
if record.get("rendering_json"):
    try:
        rendering = json.loads(record["rendering_json"])
    except Exception:
        rendering = {}
out["rendering"] = rendering or {}
```

`/api/history/<id>` response 加 `rendering: { [tabKey]: object | null }`，绝不暴露 `rendering_json` 原字符串。

## 8. 实施分期（一次做完）

| 步 | 范围 | 工时 |
|---|---|---|
| 1 | 后端：8 schemas + extractor + analyzer 集成 + DB schema + DTO | ~3.5h |
| 2 | 前端：8 个 Card 组件 + 4 共享子组件 + Tab 渲染骨架 + folded markdown | ~4.5h |
| 3 | 测试：抽取单元 + 端到端 + 失败降级 + 前端快照 | ~1.5h |
| 4 | 文档/迁移：可选 backfill CLI（老分析重跑 extractor） | ~0.5h |
| **合计** | | **~10h** |

## 9. 验证

| 验证 | 方法 |
|---|---|
| 8 schemas 实例化 / 序列化 | `pytest tests/agents/test_rendering_schemas.py -q` |
| Extractor 单 tab 失败隔离 | 模拟 1 个 tab raise → 其它 7 个仍写入 |
| 详情 API 不暴露 `rendering_json` 原串 | DTO 测试断言 `body["rendering"]` 为 dict 且无 `rendering_json` 顶层字段 |
| 老分析降级 | rendering_json IS NULL → 前端无卡片，仅 markdown |
| `npm run build` ✓ + `pytest tests/agents tests/web tests/tasks -q` 全绿 |  |

## 10. 复用

依据 [engineering-principles.md](./engineering-principles.md)：

- **L0 项目内**：v1.13 R-fix-7B 元数据迁移模式 + paper-trade v1.3 F3 `with_structured_output(ExecutiveSummary)` 模式 + v1.13 R-fix-7F rehype-sanitize 通道 + shadcn `Card / Badge / Tabs / Separator`
- **L1 库**：`pydantic` / `langchain-core.with_structured_output`（已装）/ `react-markdown + remark-gfm + rehype-sanitize`（已装）
- **L4 自写**：~1500 LOC（schemas 400 + extractor 200 + 8 Card 组件 ~700 + 共享 ~200）

## 11. 风险与边界

| 风险 | 缓解 |
|---|---|
| LLM 抽取出错或幻觉数字 | system prompt 强制 "use ONLY information present"；前端不基于 rendering 触发交易 |
| 8 并发 LLM call 成本（~$0.04/次） | 用 quick_think_llm（qwen-plus / gemini-flash）；与 paper-trade v1.3 F3 同档；可在 settings 加 `analysis.rendering.enabled` 关闭 |
| schema 演进破坏老数据 | rendering_json 单列 JSON，schema 改字段时前端容错（默认值 / 可选字段）；不支持的字段忽略 |
| LLM 输出与 markdown 主体冲突 | 卡片头优先（结论），markdown 折叠为参考；用户可对照 |
| 抽取阻塞 pipeline_done 事件 | extractor 在 `pipeline_done` emit 之**前**完成；超时 45s 单 tab；超时即 null（不阻断 task） |

## 12. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-01 | 初版：8 tab × Pydantic schema（Overview/Market/Sentiment/News/Fundamentals/Debate/Risk/Decision）+ `analysis_history.rendering_json` 单列 JSON 存储 + RenderingExtractor 并发 8 calls + 8 Card 组件 + folded markdown 主体 + 单 tab 失败隔离降级 |
