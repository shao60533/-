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

## 13. v1.1 增量：News / Fundamentals 改用真实数据源 + Quick-info 三卡

### 13.1 背景

详情页顶部"最近新闻 / 基本面指标 / 多空辩论"三张 quick-info 卡当前实现：
- `extractFundamentals()` 用 regex 从 LLM markdown 抽 PE/ROE/D/E（line ~432）
- `newsSnippet = (reportContent.News || "").slice(0, 200)` 直接截 LLM 报告头
- `extractDebateCount()` 数 markdown 里 "看多/看空" 字符出现次数

结果（生产截图）：两张卡显示成 `FINAL TRANSACTION PROPOSAL: **BUY** # 宏观经济与科技巨头市场状态综合研究报告 ## 一、 全球宏观...` —— 是 LLM 报告的 markdown 头，不是新闻头条 / 真数字。

### 13.2 现成数据源（已在项目里）

| 源 | 端点 / 方法 | 字段 |
|---|---|---|
| yfinance | `Ticker.info` via [data_manager.get_fundamentals](../../stock_trading_system/data/data_manager.py:194) | `trailingPE / forwardPE / priceToBook / priceToSalesTrailing12Months / pegRatio / returnOnEquity / returnOnAssets / debtToEquity / currentRatio / quickRatio / grossMargins / operatingMargins / profitMargins / revenueGrowth / earningsGrowth / freeCashflow / marketCap / enterpriseValue / sector / industry` 全套 |
| Polygon | `list_ticker_news` via [data_manager.get_news](../../stock_trading_system/data/data_manager.py:211) | `[{title, url, published, source}]` |
| 已有路由 | [`/api/fundamentals/<ticker>`](../../stock_trading_system/web/app.py) / [`/api/news/<ticker>`](../../stock_trading_system/web/app.py) | 已就绪，无需新建 |

**结论**：基本面数字 / 新闻头条不需要 LLM 抽 markdown。LLM 只在数据源**没有的字段**（行业对比、quality_score、sentiment 标注、综述 summary）介入。

### 13.3 v1.1 数据策略（混合源）

| Tab | 真数据源 | LLM 责任 | 不变（与 v1.0 同） |
|---|---|---|---|
| **News** | `data_manager.get_news(ticker)` 拉 headlines（title/url/published/source） | 给每条 headline 标 `sentiment / impact`、综合 `summary`、抽 `catalysts[]` | NewsCard schema 不变 |
| **Fundamentals** | `data_manager.get_fundamentals(ticker)` 拉 valuation/growth/profitability/balance_sheet 真数字 | 仅写 `valuation.vs_industry`（行业对比文字） + `quality_score` 1-5 + `summary` | FundamentalsCard schema 不变 |
| 其它 6 tab | — | 与 v1.0 同 | 不变 |

### 13.4 后端：`data_sources.py` + 修订 RenderingExtractor

新建 [stock_trading_system/agents/rendering/data_sources.py](../../stock_trading_system/agents/rendering/data_sources.py)：

```python
"""Real data fetchers for News / Fundamentals tabs.

Why this lives here: the v1.0 extractor asked the LLM to recover
quantitative facts from its own free-text reports. That round-tripped
hallucinations (made-up PE ratios) and produced unstable values. v1.1
short-circuits to the existing data_manager providers and lets the LLM
do only what it is good at — labelling sentiment, writing summaries,
naming catalysts. Schema shape stays identical to v1.0; only the
fill source changes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from stock_trading_system.agents.rendering.schemas import (
    Headline, Valuation, Growth, Profitability, BalanceSheet,
)

logger = logging.getLogger("agents.rendering.data_sources")


def fetch_fundamentals_facts(ticker: str, data_manager) -> dict:
    """Pull yfinance/Polygon/IB facts → split across our 4 fundamentals
    sub-blocks. Returns ``{"valuation","growth","profitability",
    "balance_sheet","sector","industry","market_cap"}``.

    Missing fields stay None — never invent."""
    info = {}
    try:
        info = data_manager.get_fundamentals(ticker) or {}
    except Exception as e:
        logger.warning("fetch_fundamentals_facts(%s) failed: %s", ticker, e)
        return {}
    if not isinstance(info, dict):
        return {}
    val = Valuation(
        pe=_safe(info.get("trailingPE")),
        pb=_safe(info.get("priceToBook")),
        ps=_safe(info.get("priceToSalesTrailing12Months")),
        ev_ebitda=_safe(info.get("enterpriseToEbitda")),
        peg=_safe(info.get("pegRatio") or info.get("trailingPegRatio")),
    )
    growth = Growth(
        revenue_yoy_pct=_pct(info.get("revenueGrowth")),
        eps_yoy_pct=_pct(info.get("earningsGrowth")),
        fcf_yoy_pct=_pct(info.get("freeCashflowGrowth")),  # may be None
    )
    prof = Profitability(
        gross_margin_pct=_pct(info.get("grossMargins")),
        op_margin_pct=_pct(info.get("operatingMargins")),
        roe_pct=_pct(info.get("returnOnEquity")),
        roic_pct=_pct(info.get("returnOnAssets")),  # ROA is best yfinance proxy
    )
    bs = BalanceSheet(
        debt_to_equity=_safe(info.get("debtToEquity")),
        current_ratio=_safe(info.get("currentRatio")),
        cash_ratio=_safe(info.get("quickRatio")),
    )
    return {
        "valuation": val.model_dump(),
        "growth": growth.model_dump(),
        "profitability": prof.model_dump(),
        "balance_sheet": bs.model_dump(),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
    }


def fetch_news_headlines(ticker: str, data_manager, limit: int = 8) -> list[dict]:
    """Pull recent headlines. Map to v1.0 Headline schema (without
    sentiment/impact — those are LLM-labelled in extractor)."""
    try:
        items = data_manager.get_news(ticker) or []
    except Exception as e:
        logger.warning("fetch_news_headlines(%s) failed: %s", ticker, e)
        return []
    out = []
    for n in items[:limit]:
        out.append(Headline(
            title=str(n.get("title") or ""),
            source=str(n.get("source") or "") or None,
            date=_normalize_date(n.get("published")),
            sentiment="neutral",  # LLM will overwrite
            impact="medium",      # LLM will overwrite
        ).model_dump())
    return out


# ── helpers ─────────────────────────────────────────────
def _safe(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _pct(x):
    """yfinance returns 0.12 for 12%; we store percent."""
    v = _safe(x)
    return round(v * 100, 2) if v is not None else None


def _normalize_date(raw) -> str | None:
    if not raw:
        return None
    s = str(raw)
    # yfinance gives epoch int as string; Polygon gives ISO
    try:
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=timezone.utc).strftime("%Y-%m-%d")
        return s[:10]  # ISO → keep date part
    except Exception:
        return None
```

修订 `RenderingExtractor`：构造时多传一个 `data_manager`；News / Fundamentals 走专门方法；其它 6 tab 仍走 v1.0 通用 path。

```python
class RenderingExtractor:
    def __init__(self, llm, data_manager=None, *, per_tab_timeout: float = 45.0):
        self._llm = llm
        self._dm = data_manager
        self._timeout = per_tab_timeout

    def extract(self, result, ticker: str) -> dict:
        """Now needs ticker so News/Fundamentals can hit data_manager."""
        # 与 v1.0 类似,但 News / Fundamentals 走 _extract_news / _extract_fundamentals
        ...

    def _extract_news(self, result, ticker: str) -> dict | None:
        """Real headlines + LLM sentiment/impact + summary + catalysts."""
        headlines = []
        if self._dm:
            headlines = fetch_news_headlines(ticker, self._dm, limit=8)
        # 让 LLM 在已有 headlines 基础上 enrich:
        # 1) 给每条 headline 写 sentiment + impact
        # 2) 抽 catalysts
        # 3) 写 summary
        # 输入 headlines JSON + result.news_report markdown 作上下文
        prompt = (
            f"Real headlines (from data API):\n{json.dumps(headlines, ensure_ascii=False)}\n\n"
            f"LLM news_report context:\n{result.news_report or ''}"
        )
        sys = (
            "Enrich the provided real headlines: keep title/source/date/url AS-IS "
            "and only fill sentiment/impact based on the LLM context. "
            "Do NOT invent headlines. Add catalysts derived from context. "
            "Write a 1-3 sentence summary."
        )
        try:
            structured = self._llm.with_structured_output(NewsCard)
            card = structured.invoke([
                {"role": "system", "content": sys},
                {"role": "user", "content": prompt},
            ])
            # Hard guard: replace LLM's headlines with the real ones, only
            # keeping LLM's sentiment/impact if it matched a real title.
            real_by_title = {h["title"]: h for h in headlines}
            merged = []
            for hl in (card.headlines or []):
                base = real_by_title.get(hl.title)
                if not base:
                    continue  # drop hallucinated ones
                merged.append({**base, "sentiment": hl.sentiment, "impact": hl.impact})
            # If LLM dropped some, append untagged real headlines
            tagged_titles = {h["title"] for h in merged}
            for h in headlines:
                if h["title"] not in tagged_titles:
                    merged.append(h)
            return {
                "headlines": merged,
                "catalysts": [c.model_dump() for c in (card.catalysts or [])],
                "summary": card.summary,
            }
        except Exception as e:
            logger.warning("News extraction failed: %s", e)
            # Last resort: return headlines without LLM enrichment
            return {"headlines": headlines, "catalysts": [],
                    "summary": ""} if headlines else None

    def _extract_fundamentals(self, result, ticker: str) -> dict | None:
        """Real numbers + LLM only writes vs_industry / quality_score / summary."""
        facts = {}
        if self._dm:
            facts = fetch_fundamentals_facts(ticker, self._dm)
        # 让 LLM 仅写 valuation.vs_industry / quality_score / summary
        # 给它真实 facts JSON + 报告 markdown 作上下文
        if not facts:
            # Fall back to pure-LLM path (v1.0 behavior)
            return self._extract_one("Fundamentals", FundamentalsCard,
                                       result.fundamentals_report or "")

        prompt = (
            f"Real fundamentals facts (from data API):\n{json.dumps(facts, ensure_ascii=False)}\n\n"
            f"LLM fundamentals_report context:\n{result.fundamentals_report or ''}"
        )
        sys = (
            "Use the provided real facts AS-IS. Do NOT change pe/pb/ps/peg/"
            "ev_ebitda/growth/profitability/balance_sheet numbers. Only "
            "write valuation.vs_industry (1 sentence comparing to sector), "
            "quality_score (1-5 integer), and summary (1-3 sentences)."
        )
        try:
            structured = self._llm.with_structured_output(FundamentalsCard)
            card = structured.invoke([
                {"role": "system", "content": sys},
                {"role": "user", "content": prompt},
            ])
            # Hard guard: overwrite LLM-emitted numeric blocks with real facts.
            return {
                "valuation": {**facts["valuation"],
                               "vs_industry": (card.valuation.vs_industry
                                                if card.valuation else None)},
                "growth": facts["growth"],
                "profitability": facts["profitability"],
                "balance_sheet": facts["balance_sheet"],
                "quality_score": int(card.quality_score or 3),
                "summary": card.summary or "",
            }
        except Exception as e:
            logger.warning("Fundamentals extraction failed: %s", e)
            return None
```

### 13.5 前端：Quick-info 三卡改直接拉 API

[AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) `AnalysisDetailView`：

```tsx
const [news, setNews] = useState<{title:string; source?:string; published?:string; url?:string}[]>([])
const [fund, setFund] = useState<Record<string, any> | null>(null)

useEffect(() => {
  if (!detail.ticker) return
  apiGet<any[]>(`/api/news/${detail.ticker}`).then(r => setNews((r ?? []).slice(0, 3))).catch(() => {})
  apiGet<Record<string, any>>(`/api/fundamentals/${detail.ticker}`)
    .then(setFund).catch(() => setFund(null))
}, [detail.ticker])

// 删除 extractFundamentals / extractDebateCount / newsSnippet.slice(0,200)
```

三卡内容改为：

```tsx
<QuickInfoCard
  icon={<Newspaper className="h-4 w-4" />}
  title="最近新闻"
  onClick={() => scrollToTab("News")}
>
  {news.length === 0 ? (
    <p className="text-xs text-muted-foreground">暂无新闻数据</p>
  ) : (
    <ul className="space-y-1.5">
      {news.map((n, i) => (
        <li key={i} className="text-xs leading-snug">
          <span className="line-clamp-2">{n.title}</span>
          {(n.source || n.published) && (
            <span className="text-[10px] text-muted-foreground mt-0.5">
              {n.source}{n.source && n.published && " · "}{n.published}
            </span>
          )}
        </li>
      ))}
    </ul>
  )}
</QuickInfoCard>

<QuickInfoCard
  icon={<BarChart3 className="h-4 w-4" />}
  title="基本面指标"
  onClick={() => scrollToTab("Fundamentals")}
>
  {!fund ? (
    <p className="text-xs text-muted-foreground">暂无基本面数据</p>
  ) : (
    <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-xs">
      {fund.trailingPE != null && <KV k="PE" v={fmtNum(fund.trailingPE, 1)} />}
      {fund.priceToBook != null && <KV k="P/B" v={fmtNum(fund.priceToBook, 1)} />}
      {fund.returnOnEquity != null && <KV k="ROE" v={fmtPct(fund.returnOnEquity)} />}
      {fund.debtToEquity != null && <KV k="D/E" v={fmtNum(fund.debtToEquity, 0)} />}
      {fund.profitMargins != null && <KV k="净利率" v={fmtPct(fund.profitMargins)} />}
      {fund.revenueGrowth != null && <KV k="营收增长" v={fmtPct(fund.revenueGrowth)} />}
    </div>
  )}
</QuickInfoCard>

<QuickInfoCard
  icon={<Scale className="h-4 w-4" />}
  title="多空辩论"
  onClick={() => scrollToTab("Investment Debate")}
>
  {(() => {
    const debate = detail.rendering?.["Investment Debate"]
    const synthesis = detail.rendering?.summary?.debate_synthesis
    if (debate) {
      const bull = debate.bull_arguments?.length ?? 0
      const bear = debate.bear_arguments?.length ?? 0
      return (
        <div className="space-y-1">
          <div className="text-xs">看多 <b>{bull}</b> · 看空 <b>{bear}</b> · 结论 <Badge variant="muted" className="text-[10px]">{debate.verdict ?? '—'}</Badge></div>
          <p className="text-xs text-muted-foreground line-clamp-3">{debate.key_disagreement || debate.neutral_synthesis}</p>
        </div>
      )
    }
    if (synthesis) {
      return <p className="text-xs text-muted-foreground line-clamp-3">{synthesis.verdict}</p>
    }
    return <p className="text-xs text-muted-foreground">暂无辩论数据</p>
  })()}
</QuickInfoCard>
```

helper 内联：

```tsx
const fmtNum = (v: number, d: number) => v.toFixed(d)
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`
const KV = ({ k, v }: { k: string; v: string }) => (
  <div className="flex items-center justify-between"><span className="text-muted-foreground">{k}</span><span>{v}</span></div>
)
```

### 13.6 删除（强约束）

- 删除 `extractFundamentals(text: string)` 整函数
- 删除 `extractDebateCount(text: string)` 整函数
- 删除 `const newsSnippet = (reportContent.News || "").slice(0, 200)`
- 删除 `const fundSnippet = extractFundamentals(...)` / `const debateSnippet = extractDebateCount(...)` 全部对应调用

### 13.7 缓存

`/api/fundamentals/<ticker>` + `/api/news/<ticker>` 已有 LocalCache（v1.6 R-perf 30s TTL）。Quick-info 卡 + Fundamentals/News tab 抽取共用同一份缓存，不会双拉。

### 13.8 风险与边界

| 风险 | 缓解 |
|---|---|
| yfinance .info 字段缺失（小盘股、ADR） | facts 字段允许 None，前端 `v != null && <KV/>` 不渲染缺项 |
| 数据源延迟（yfinance 偶发 1-3s） | 与 LLM 8 并发同源池跑（ThreadPoolExecutor），不串行；LocalCache 复用 |
| API key 缺失（Polygon 关，仅 yfinance）| `data_manager.get_news` 已有 fallback 链；data_sources.py 不感知 |
| LLM 仍幻觉 headlines / 改了真数字 | 提取后做 hard guard：headlines 必须 title 命中真集合；valuation/growth/profitability/balance_sheet 字典直接以 facts 覆盖 LLM |

## 14. v1.6 增量：Executive Summary 入 OverviewCard 操作建议位

### 14.1 现状

详情页 `/analysis/<id>` 概览 tab `<OverviewCard>` Decision banner 当前布局（[OverviewCard.tsx:48-65](../../stock_trading_system/web/frontend/src/components/analysis/OverviewCard.tsx)）：
1. RatingBadge (`Overweight`) + ConfidenceMeter (`中置信`)
2. 📍 action_direction (`分批建仓`)
3. KpiRow (PE / 现金流 / SMA / MACD / ATR …)

后端 DTO `history_detail_dto` 已 expose `executive_summary`（[app.py:1564](../../stock_trading_system/web/app.py)），来自 [paper-trade v1.3 F3](./paper-trade.md) 的 `with_structured_output(ExecutiveSummary)` 抽取列。但前端：
- AnalysisPage.tsx 仅在 `reportContent["summary"] = detail.summary` 把它塞进 markdown body 折叠区（line 772）
- 截图中"轻松支撑 645 亿美元的 AI 资本支出"零散小字脱离 Decision banner —— 没有视觉容器
- OverviewCard 不接收 executive_summary，banner 内只有 action_direction 一句话方向，缺**具体可执行的操作建议**段落

### 14.2 改动

**目标**：把 `executive_summary` 移到 OverviewCard Decision banner 内、`action_direction` 下方、`KpiRow` 上方，结构化展示作为「操作建议」。

布局调整：
```
┌─Decision Banner──────────────────────────────────┐
│  [Overweight] [Conf 中置信]                       │
│  📍 分批建仓                                       │
│  ┌─📋 执行总结──────────────────────────────────┐ │ ← 新增
│  │ 微软当前估值合理 + AI 资本支出 645 亿美元   │ │
│  │ 支撑长期增长动能；建议在 50 SMA $396 附近   │ │
│  │ 分批建仓，关注 MACD 与净利润率边际变化       │ │
│  └────────────────────────────────────────────────┘│
│  [KPI Row: PE 21.45 / 现金流 / SMA / MACD / ATR]  │
└────────────────────────────────────────────────────┘
```

视觉规则：
- 标题行：`<ScrollText className="h-4 w-4 text-[var(--color-accent-blue)]" />` + `执行总结`
- 主体：left border accent (`border-l-4 border-primary/60`) + `bg-primary/5` + 段落正文
- 字号：`text-sm leading-relaxed`，最长 `line-clamp-4` 不滚动（保持 banner 紧凑）
- 完整段落仍保留在折叠 markdown body —— 这里只是结构化露出关键操作建议

### 14.3 数据流

后端不需要改 —— `executive_summary` 已在 detail DTO（v1.0/v1.1 落地后无破坏）。

前端：
- `OverviewCardData` 类型保持不变（Pydantic mirror）
- `<OverviewCard>` 加可选 prop `executiveSummary?: string | null`（不进 schema，避免污染 rendering JSON）
- AnalysisPage.tsx 渲染 OverviewCard 时把 `detail.executive_summary` 作为 prop 透传：
  ```tsx
  <OverviewCard data={rendering.summary} executiveSummary={detail.executive_summary} />
  ```
- 兼容路径：`AnalysisCards` lazy-bundle dispatcher 接收并透传该 prop（对其它 7 tab 无副作用）
- 留 markdown body 不动 —— `executive_summary` 仍在折叠区可访问（双展示无害，因为 banner 是结构化卡，markdown 是完整原文）

### 14.4 边界

- 不动 OverviewCard schema / Pydantic / extractor / rendering_json 存储
- 不动其它 7 tab Card
- `executiveSummary` 缺失（老分析没跑 paper-trade v1.3 F3 抽取）→ 静默不渲染该子卡（与现有 `nonEmptyStr` defensive 风格一致）
- 不引入新 LLM call、不发明新端点
- 不改 `detail.summary` 字段含义（仍是 `executive_summary || trade_decision` fallback 链，给 markdown body / inbox 行展开摘要用）

### 14.5 测试

`tests/frontend/src/components/analysis/__tests__/OverviewCard.executive.test.tsx`（新增）：
- `renders executive summary block when prop provided` — render `<OverviewCard data={...} executiveSummary="...">` → 断言 DOM 含「执行总结」标题 + summary 文本
- `omits executive summary block when prop empty` — render with `executiveSummary={null}` 或 `""` → 断言无「执行总结」标题
- `executive summary positioned between action_direction and KpiRow` — 断言 DOM 顺序: action_direction 元素 < executive 元素 < KpiRow 元素
- `falls back gracefully on whitespace-only string` — `executiveSummary="   "` → 静默（用 `nonEmptyStr`）

## 12. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-01 | 初版：8 tab × Pydantic schema（Overview/Market/Sentiment/News/Fundamentals/Debate/Risk/Decision）+ `analysis_history.rendering_json` 单列 JSON 存储 + RenderingExtractor 并发 8 calls + 8 Card 组件 + folded markdown 主体 + 单 tab 失败隔离降级 |
| v1.1 | 2026-05-01 | News / Fundamentals 改混合源：直接调 `data_manager.get_news / get_fundamentals` 拿真实头条 + 真实数字（PE/PB/ROE/D/E/营收增长全套来自 yfinance .info / Polygon news），LLM 仅做 sentiment/impact 标注 + catalysts + summary + vs_industry + quality_score；Hard guard 防 LLM 改真数字（valuation/growth/profitability/balance_sheet 字典覆盖）+ 防 LLM 编造头条（title 必须命中真集合）；前端 quick-info 三卡（最近新闻 / 基本面指标 / 多空辩论）改为直接拉 `/api/news` `/api/fundamentals`，删除 `extractFundamentals` regex / `newsSnippet.slice(0,200)` / `extractDebateCount` 三个脆弱函数；多空辩论卡改用 `detail.rendering["Investment Debate"]` schema |
| v1.6 | 2026-05-03 | Executive Summary 入 OverviewCard 操作建议位（用户截图反馈）：现状概览 tab 顶部"轻松支撑 645 亿美元的 AI 资本支出"零散小字（来自 `detail.executive_summary`，paper-trade v1.3 F3 抽取列）脱离 Decision banner，无视觉容器；banner 内仅 `action_direction`（"分批建仓"）一句话方向，缺具体可执行操作建议。后端 DTO 已 expose（`app.py:1564 history_detail_dto.executive_summary`），改动仅前端：(A) `<OverviewCard>` 加可选 prop `executiveSummary?: string \| null`，渲染在 `action_direction` 下方、`KpiRow` 上方，视觉 = `<ScrollText>` 图标 + "执行总结" 标题 + left border accent (`border-l-4 border-primary/60` + `bg-primary/5`) + `text-sm leading-relaxed line-clamp-4` 段落；(B) AnalysisPage.tsx 渲染 OverviewCard 时透传 `detail.executive_summary`；(C) `AnalysisCards` lazy-bundle dispatcher 接收并向 OverviewCard 透传，对其它 7 tab 无副作用；(D) 缺失或纯空白时静默不渲染（用现有 `nonEmptyStr` defensive helper）；(E) markdown body 折叠区保留原 `executive_summary`（双展示无害，banner 结构化、body 完整）。**不动** OverviewCard Pydantic schema / RenderingExtractor / `rendering_json` 存储 / 其它 7 tab Card / `detail.summary` 字段含义 / inbox 行展开摘要逻辑。新增 4 个 vitest case 验证位置/缺失降级/whitespace 兜底 |
