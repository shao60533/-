# 技术方案：UI React Island 迁移回归修复

| 项 | 值 |
|---|---|
| Feature | `ui-react-island-regression` |
| 版本 | v1.0 |
| 日期 | 2026-04-25 |
| 关联主方案 | [ui-react-island.md](./ui-react-island.md) v1.0 / v2.0 |
| 关联施工图 | [ui-react-island-pages.md](./ui-react-island-pages.md) v1.0 |
| 关联移动端基线 | [mobile-optimization.md](./mobile-optimization.md) v1.0 |
| 关联测试 | [../test-cases/ui-react-island-regression.md](../test-cases/ui-react-island-regression.md) |

## 0. 实施进度（v1.4 截止 2026-04-25 晚）

R-1 ~ R-7 commits 已落地（6e583b4..5370863）。审计 22 P0 项实际状态：

| 状态 | 数量 | 项 |
|---|---|---|
| ✅ DONE | **19** | Portfolio P-P0-1/2 · Paper-trade PT-P0-1/2/3 · Dashboard D-P0-1~4 · Analysis A-P0-1/2 · Tasks T-P0-1~6 · Menu M-P0-1~3 |
| ❌ MISSING（v1.4 已知）| **6** | **MS-P0-1~4 整套 LLMSwitcher** · **SE-P0-1 缺 Gemini+Qwen API key** · **A-P0-3 Pipeline DAG** |
| ❌ MISSING（v1.5 实测新增）| **6** | **HE-P0-1 History 跳分析详情 404** · **SV3-P0-1 Screener V3 结果页未建** · **A-P0-4 TradingView K线 widget**（现在 ECharts）· **A-P0-5 新闻+基本面侧卡** · **B-P0-1 Backtest 结果详情页**（只有表单）· **D-P0-5 /backtest-v2 死链** |
| ⚠ R-6 未真实落地 | 4 | HE-P1-1/2 对比+timeline · AL-P1-2 阈值建议 · SE-P1-1/2 调度器+数据源 · R-P2-12 reports 导出（暂不阻塞 P0 闸门）|
| ⚠ 性能问题（v1.6 实测）| 1 | **PERF-P0-1 Dashboard / Portfolio 加载慢**（每次访问 = 2 次全量价格拉取，~3s）|
| ❌ MISSING（v1.7 实测新增）| 2 | **PT-P0-4 paper-trade ticker 详情页空白**（PT-P0-3 fix 未真实落地，pathname.split 仍是老代码）· **A-P0-7 分析提交后跳 /tasks 不是 /analysis 详情**（用户看不到 DAG 流式进度 + 7-tab 报告流入）|
| ❕ 功能补强（v1.8 新增）| 2 | **D-FEAT-1 仪表盘净值曲线自动回溯**（从最早 snapshot 数据起到今天每日，而非固定 30 天）· **P-FEAT-1 持仓表加盈亏绝对值列**（除百分比外补 PnL 美元值） |
| ❌ MISSING（v1.9 实测新增）| 1 | **A-P0-8 AI 分析运行中态完全空白**（点开始分析后页面无内容；应该立即显示 K线/新闻/基本面 + Pipeline DAG 实时进度 + 7-tab 占位 skeleton，agent 完成后逐个填充）|
| ❌ 实测仍未真修（v1.10 prod 验证）| 5 | **D-FEAT-1 净值曲线只 1 个点**（后端 days=30 硬编码未改 None）· **P-FEAT-1 Dashboard 持仓 top3 没加绝对值列**（仅 PortfolioPage 加了）· **SV3-P0-1 V3 结果"加载失败"**（前端用 task_id 拉 result，但后端期望 result_id 整数）· **PT-P0-4 paper-trade ErrorBoundary 真触发**（内部 render 抛错，需修内部 null check）· **R-5.3 K线区域空白**（TVChart 已挂但 klineData 空，需修 quote/history API 接入）|
| ❌ v1.11 修了代码但没修数据（v1.12 实测）| 1 | **D-FEAT-1 净值曲线仍只 1 个点**：v1.11 后端代码 ✅ 正确（返 daily_snapshots 全量），但 **DB 里只有 3 行 snapshot**（2026-04-14/15/16/19），距今缺 11 天。根因：调度器 [task_scheduler.py:105](../../stock_trading_system/scheduler/task_scheduler.py) take_snapshot 没真跑 + 缺历史回填脚本 → 需 R-fix-6 同时补 (a) 历史回填 (b) 调度器修复 (c) UI 触发入口 |
| ❌ AI 分析模块产品&技术缺口（v1.13 用户提）| 7 | **A-FIX-A K线初始 Skeleton 早 return** [TVChart.tsx:108](../../stock_trading_system/web/frontend/src/components/shared/TVChart.tsx) 导致 chart 容器永不挂载；**A-FIX-B analysis_history 缺 `created_by/provider/config_hash/task_id/duration_sec/bookmarked` 元数据**（[database.py:81](../../stock_trading_system/portfolio/database.py) schema 缺 + [task_store.py:368](../../stock_trading_system/tasks/task_store.py) INSERT 不写）；**A-FIX-C 旧 `/api/analyze`** [app.py:852](../../stock_trading_system/web/app.py) 仍开 daemon thread + 直写 history + 硬编码 `gemini.deep_think_model` 不走 active provider；**A-FIX-D advice 与共享分析未拆分**（advice_json 和 trade_decision 同表，其他用户能看到原作者的持仓上下文）；**A-FIX-E `/analysis` 首页缺 5 条最近卡片 + 深度选择 + 8 tab + 决策独立 tab + 操作按钮齐**；**A-FIX-F Markdown 无 sanitize**（[AnalysisPage.tsx:393](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 仅 react-markdown + remark-gfm，缺 rehype-sanitize）；**A-FIX-G `_record_agent_scores`** [workers.py:135](../../stock_trading_system/tasks/workers.py) 为拿 analysis_id 先 save 半成品行 → 历史页双重记录 |

**T-P0-6 任务中心空白 bug 已修复**（实测 2026-04-25）：
- ✅ 后端 [app.py:1713-1719](../../stock_trading_system/web/app.py) 返回 `{tasks, items, total, limit, offset}` 双字段向后兼容
- ✅ 前端 [TasksPage.tsx:67-70](../../stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx) fallback 链 `tasks || items || []`

若 `/tasks` 仍显示空白，根因不在 schema 而在数据/过滤层（可能：DB 无数据 / type chip 默认过滤过严 / scope=my 当前用户无任务），需运行时排查。

→ 余 R-1.x 收尾批次（~5h）见 [§6.1](#61-r-1x-收尾批次p0-余项) 详细合并指令。

完成 R-1.x 后 P0 闸门全绿，可进入 R-6 / R-7（已完成的部分回归测试 + 真实数据跑一遍）。

## 1. 背景

[ui-react-island](./ui-react-island.md) v1.0 + v2.0 完成了 11 页全部迁移到 React，但实施时**为了赶交付简化了 page 内部的功能实现**，导致两类回归：

1. **功能消失 / 退化**（59 项）：图表 / 表单字段 / Tab 报告 / 模板控件等被简化或漏写
2. **移动端适配缺失**（15 项）：Stat 数字溢出、grid 不塌陷、form 不堆叠等，未应用 [mobile-optimization](./mobile-optimization.md) 的 7 通用组件 + 3 断点

用户实测后逐个发现，需要**系统化的回归修复 backlog**。本文档是修复总规划，不引入新功能，只补回已有功能。

### 1.1 严格约束（用户两次明确）

> **不允许改用户已确认的功能行为。只补回缺失的，不重构已工作的。**

修复期间：
- 后端 API 字段不改（只接，不改）
- React 已有路由不动（仅补未实现的子页 / Modal / Tab）
- 已工作的 React 组件不重写（只在外面套响应式 wrapper 或加缺失字段）
- 页面 URL 不改（除非引入兼容 redirect）

## 2. 总览

### 2.1 问题分布（按页 × 严重度）

| 页 | CRITICAL | HIGH | MEDIUM | LOW | 移动端 |
|---|---|---|---|---|---|
| Dashboard | **2** 净值曲线 + 仓位分布饼图缺失 | 3 | 2 | 0 | **CRIT** stat-value 溢出 |
| Analysis | **3** K 线 + 7-tab 报告 + Pipeline DAG 缺失 | 2 | 4 | 0 | **HIGH** 3-col grid 挤压 + form 横排 |
| History | 0 | 2 对比模式 + 演变 timeline | 1 | 0 | LOW（基本 OK） |
| Screener-v3 | 0 | 0 | 2 | 1 | MEDIUM cost grid 3-col 挤 |
| **Portfolio** | **2** 🚨 卖出表 + 修正成本 modal | 3 | 3 | 0 | MEDIUM stat grid 不塌陷 |
| Alerts | 0 | 2 模板 chips + 阈值建议 | 3 | 0 | MEDIUM grid + row 不堆叠 |
| Reports | 0 | 0 | 1 | 0 | MEDIUM form sm vs 576 不一致 |
| Backtest | 0 | 3 结果页 + 净值图 + 明细表 | 1 | 0 | MEDIUM 5 字段挤 + 日期 picker |
| **Paper-trade** | **3** 🚨🚨 权益曲线 + 列表页 + ticker 详情空白 bug | 1 日度 tab | 3 | 0 | LOW |
| **Settings** | **1** 🚨 缺 Gemini + Qwen API key 字段 | 2 调度器 + 数据源卡 | 1 | 0 | MEDIUM provider grid 窄 |
| **Tasks** | **6** 🚨 历史无分页 / 无类型 + scope 过滤 / 无跳转落地页 / 详情操作不全 / **空白 bug**（API schema 不匹配） | 0 | 2 | 0 | LOW |
| **Model-Switch UI** | **4** 🚨🚨 整个 Nav 下拉组件 + 4 状态处理（active/缺 key/env 锁定/loading）完全缺失 | 0 | 0 | 0 | — |
| **总计** | **22** | **18** | **23** | **1** | 6 项移动端独立问题 |

### 2.2 五大共性根因

| # | 根因 | 影响范围 |
|---|---|---|
| 1 | **图表大批失踪** | 6 个图：dashboard 净值/分布、analysis K 线、backtest 净值、paper-trade 权益、portfolio 趋势 |
| 2 | **多字段表单被简化** | Portfolio 卖出 4 字段 → 0、Alerts 5 模板+7 条件 → 简单 dialog、Backtest 动态参数 → fixed |
| 3 | **多 Tab 报告整体丢失** | Analysis 7 tab、Paper-trade 日度 tab、Portfolio 交易记录 tab |
| 4 | **辅助控件被删** | 快速模板 / 首次使用 tip / 测试规则 / 阈值建议 / 修正成本 modal |
| 5 | **移动端响应式没全套用 mobile-optimization 规范** | Stat / Form grid / cost grid 等 6 处未对齐断点；Tailwind `sm:` (640px) ≠ 设计标准 576px |

## 3. 修复策略

### 3.1 三阶段（P0 / P1 / P2）

| 阶段 | 范围 | 阈值 | 估时 |
|---|---|---|---|
| **P0 紧急修复** | 22 CRITICAL（含 paper-trade 列表+ticker bug + Tasks 5+空白 bug + Settings keys + Model-Switch UI 4 + Dashboard stat）+ 菜单重组 | 上线前必完 | ~28h |
| **P1 高优先恢复** | 18 HIGH + 移动端 form/grid 标准化（6 处） | 第 1 周内 | ~15h |
| **P2 完善** | 23 MEDIUM + 1 LOW + 测试覆盖 | 第 2-3 周 | ~14h |

总修复工时 ~57h。

### 3.2 移动端规范统一（横切要求）

P0/P1 阶段所有改动必须遵守 [mobile-optimization.md](./mobile-optimization.md)：

```css
/* 强制断点：与 Tailwind sm 不同！ */
@media (max-width: 575.98px) { /* 移动专用 */ }
@media (max-width: 767.98px) { /* 平板及以下 */ }

/* 关键 token */
--fs-stat: clamp(16px, 4.6vw, 22px);    /* Stat value 强制 */
--fs-hero: clamp(22px, 7vw, 40px);      /* signal-value 强制 */
--touch-min: 44px;
```

要求：
- 所有 `text-2xl` 在 stat / 金额场景一律改用 `var(--fs-stat)` + `font-mono tabular-nums` + `truncate` 三件套
- 所有 `grid-cols-N` (N>1) 必须在 `≤575.98px` 显式塌陷为 1 列
- 所有 form 多字段 row 必须套 `.form-row-mobile` 类
- 所有 button + 行点击区 `min-height: 44px`

## 4. 11 页详细 backlog

下文每页按 `P0 → P1 → P2` 顺序列举。代码改动给具体文件路径，不写实现代码（实施期由 Code 来）。

### 4.1 Dashboard

**P0**：
- [D-P0-1] 🚨 **stat-value 文本溢出**：[islands/dashboard/](../../stock_trading_system/web/frontend/src/islands/dashboard/) Stat 组件应用 `--fs-stat` clamp + `tabular-nums` + 容器 `overflow-hidden` + `text-overflow:ellipsis`
- [D-P0-2] 🚨 **净值曲线图 chart-pnl** 完全缺失 → 补上 ECharts line + drawdown markArea；数据来自 `/api/dashboard.equity_curve`
- [D-P0-3] 🚨 **仓位分布饼图 chart-allocation** 缺失 → ECharts pie；数据来自 `/api/dashboard.allocation` 或 `/api/portfolio/allocation`
- [D-P0-4] stat 卡 grid `≤575.98px` 单列塌陷

**P1**：
- [D-P1-1] 4 个快捷按钮缺失：生成报告 / 分析全部持仓 / 预警中心 / 策略回测 → 加 4 个 link button 跳对应页
- [D-P1-2] 当前持仓表只 3 列 → 补回市场、成本、现价、收益率 4 列
- [D-P1-3] 净值曲线 range switcher（7D / 1M / 3M / 1Y）

**P2**：
- 持仓总数 / 市值概览数字补全
- 移动端 stat 数字小屏字号梯度

### 4.2 Analysis

**P0**：
- [A-P0-1] 🚨 **K 线图完全缺失** → 复用 [old index.html:294-326] 的 TradingView widget（`tv-chart-container`）+ ECharts fallback（`chart-kline`）逻辑，移植到 React 组件 `<KLineChart ticker={...} />`
- [A-P0-2] 🚨 **7-Tab 多 Agent 报告全部消失**（技术面 / 基本面 / 情绪 / 新闻 / 多空辩论 / 风险 / 最终决策）→ 用 [shadcn Tabs](../../stock_trading_system/web/frontend/src/components/ui/tabs.tsx) 套 7 个 TabsContent，渲染 API 返回的对应字段（react-markdown）
- [A-P0-3] 🚨 **Pipeline DAG 进度可视化** 缺失 → 接 [unified-progress](./unified-progress.md) 的 `agent_stage_done` 事件流，每阶段一个 step 节点

**P1**：
- [A-P1-1] 基本面指标 card 缺失（[old:362-378]）→ 补 `<FundamentalsCard />` 渲染 ROE / D/E / FCF / 利润率 等
- [A-P1-2] 最近新闻 card 缺失（[old:381-396]）→ 补 `<NewsCard />` 列出近 5 条新闻 + 来源 + 时间
- [A-P1-3] 移动端：detail page `md:grid-cols-3` 在 ≤575.98px 塌陷为 1 列；form row 套 `.form-row-mobile`

**P2**：
- 置信度 card / 策略建议 card / 自动追踪 badge 视情况补
- ECharts K 线 range switcher

### 4.3 History

**P1**：
- [H-P1-1] 对比模式（多选 + 对比按钮）缺失 → 补 checkbox select + `<CompareModal />`
- [H-P1-2] 演变 timeline modal 缺失 → 补 `<TimelineModal analysisId={x} />`

**P2**：
- detail overlay 改为 inline expand 已在新版 → 视觉 OK，可不改

### 4.4 Screener V3

**P1**：
- [S-P1-1] 移动端 cost grid `grid-cols-3` 在 ≤575.98px 塌陷为 1 列或 column-flow

**P2**：
- 结果列表大师评分 + 理由展示完整度
- 首次使用 tip
- 流式进度展示

### 4.5 Portfolio 🚨

**P0**：
- [P-P0-1] 🚨 **卖出表单完全消失** → 在 [PortfolioPage.tsx](../../stock_trading_system/web/frontend/src/islands/portfolio/PortfolioPage.tsx) 加 `<SellDialog />`，4 字段（ticker / shares / price / notes），提交 `POST /api/portfolio/sell`；同时 BuyDialog 加 `notes` 字段（原 4 字段，新版只 3 字段）
- [P-P0-2] 🚨 **修正成本价 modal 消失** → 补 `<UpdateCostModal />`（点击持仓行触发）；提交对应后端接口（找原 `updateCost` 路由）

**P1**：
- [P-P1-1] 交易记录表完全缺失 → 补独立 Tab "交易记录"，DataTable 列：时间 / 操作 / 股票 / 数量 / 价格 / 备注
- [P-P1-2] 持仓表补市场列 + 市值列
- [P-P1-3] 快照按钮 + 一键分析全部持仓按钮恢复

**P2**：
- 移动端 stat grid `≤575.98px` 单列
- 移动卡片字号 token 化

### 4.6 Alerts

**P1**：
- [AL-P1-1] 5 个快速模板 chips 缺失（向上突破 / 向下跌破 / 止损 / 止盈 / 日内涨跌）→ NewAlertDialog 顶部加 chip-row
- [AL-P1-2] 阈值建议 ("当前价 X，±5% 为 Y~Z") 缺失 → 输入 ticker 后自动调 `/api/quote/<ticker>` 显示
- [AL-P1-3] 移动端 alert row 5 元素挤 → flex-wrap 或 ≤575.98px 改 `flex-col`

**P2**：
- 测试规则按钮 / 规则预览 / 规则帮助 panel
- 立即检查所有预警 button

### 4.7 Reports

**P2**：
- [R-P2-1] 报告内容 markdown 渲染（react-markdown + remark-gfm）

### 4.8 Backtest

**P1**：
- [B-P1-1] 回测结果页面缺失（在 backtest 页内显示，不必跳 tasks）→ 补 stat cards + 净值曲线图 + 交易明细表三段
- [B-P1-2] 净值曲线图 ECharts
- [B-P1-3] 交易明细表 DataTable

**P2**：
- 动态参数区（不同策略不同参数）
- 移动端 5 字段 grid 单列；日期 picker 聚焦时 `scrollIntoView({block:'center'})` 防键盘遮挡

### 4.9 Paper-trade 🚨🚨

**当前状态**（实测 2026-04-25）：
- ✅ `/paper-trade/<ticker>` 路由存在，可看单 ticker 详情（但缺日度图，见 PT-P0-1）
- ❌ **`/paper-trade` 路由根本不存在**，[Flask app.py:527](../../stock_trading_system/web/app.py) 只注册了 `/paper-trade/<ticker>`
- ❌ **没有 paper-trade-list island**，[islands/paper-trade/](../../stock_trading_system/web/frontend/src/islands/paper-trade/) 只有 detail 一个 entry
- ❌ 用户从导航点"纸面交易"或访问 `/paper-trade` → 报错或 404；只能直接敲 ticker URL 才能看

→ **整个入口都没有，比 v1.3 PT-P1-2 描述更严重，升级 CRITICAL P0**。

**P0**：
- [PT-P0-1] 🚨 **权益曲线图（盈利趋势 chart-ptv-equity）完全缺失** → 补"日度数据"tab 内的 ECharts area chart，对应 v1.3 F4 已设计的双 grid + drawdown markArea 配置（见 [paper-trade.md §27.2 F4](./paper-trade.md)）

- [PT-P0-2] 🚨 **`/paper-trade` 列表页完全不存在** → 新建 island `islands/paper-trade-list/`：
  - Flask 路由 `@app.route("/paper-trade")` → `render_template("islands/paper_trade_list.html")`
  - React 入口 `islands/paper-trade-list/main.tsx` + `PaperTradeListPage.tsx`
  - 数据：`GET /api/paper/sessions?scope=my`（已有 API）
  - 布局参考 [ui-react-island-pages.md §4.5](./ui-react-island-pages.md)：
    ```
    ┌─ 默认 session ★ 突出卡（系统追踪・全量自动）──────────┐
    │  总值 / Sharpe / 持仓天数 / [进入详情]                 │
    └────────────────────────────────────────────────────────┘
    ┌─ 工具栏 ──────────────────────────────────────────────┐
    │ [+ 新建 session]  [搜索]  [Tab: 我的 | 全部]           │
    │ [刷新所有日度数据]（恢复 old paper-ticker-grid 顶部按钮）│
    └────────────────────────────────────────────────────────┘
    ┌─ 会话卡 grid（响应式：桌面 3 列 / 平板 2 / 移动 1）────┐
    │ ┌──────┐ ┌──────┐ ┌──────┐                            │
    │ │ NVDA │ │ AAPL │ │ AI 实盘│                            │
    │ │ +5.2% │ │ -1.8%│ │ +12.4%│                            │
    │ │8 笔   │ │3 笔  │ │25 笔  │                            │
    │ │Sharpe │ │失效  │ │live  │                            │
    │ └──────┘ └──────┘ └──────┘                            │
    └────────────────────────────────────────────────────────┘
    ```
  - 卡片整卡可点 → 跳 `/paper-trade/<ticker>`
  - 卡右上 ⋯ 菜单：重命名 / 删除 / 导出
  - 移动端 ≤575.98px 单列，每张卡内 stat 应用 `--fs-stat` clamp

**P0 追补（实测发现）**：
- [PT-P0-3] 🚨 **`/paper-trade/<ticker>` 进入后数据空白**（实测 2026-04-25）
  - 根因：[PaperTradePage.tsx:68](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) `window.location.pathname.split("/").pop()` 在 URL 末尾有 `/` 时返回空字符串，触发 ticker="" 报错"未指定股票代码"
  - 修法：改用 `pathname.split("/").filter(Boolean).pop()` 或正则 `/paper-trade\/([^/]+)/.exec(pathname)?.[1]`
  - API 路由 `/api/paper/tickers/<ticker>` 已正确返回数据，仅前端解析 bug
  - 验收：`/paper-trade/AAPL` 和 `/paper-trade/AAPL/`（带末尾斜杠）都能正确渲染

**P1**：
- [PT-P1-1] 日度数据 tab 整个缺失 → 补 stat cards + 权益图 + 日度明细表（9 列）

**P2**：
- 日度指标卡数字
- 日度明细表移动端卡片视图

### 4.10 Settings

**P0 追补（实测发现）**：
- [SE-P0-1] 🚨 **API key 字段不全 —— 缺 Qwen + Gemini**（实测 2026-04-25）
  - 根因：[SettingsPage.tsx:227](../../stock_trading_system/web/frontend/src/islands/settings/SettingsPage.tsx) hardcoded 4 个 key：`["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY"]`，**缺 `GEMINI_API_KEY`**；并且 `DASHSCOPE_API_KEY` 名字虽对但用户认知应为"Qwen API Key"，UI 标签需改善
  - 老 Jinja [index.html L1113-1162](../../stock_trading_system/web/templates/index.html) 的 settings-config 是动态遍历 config 字段，因此覆盖完整
  - 修法：
    - 简单方案：硬编码列表追加 `GEMINI_API_KEY`，`DASHSCOPE_API_KEY` UI label 改"Qwen API Key (DashScope)"，加帮助提示链
    - 优雅方案：动态从 GET `/api/settings` 响应（含 `gemini.api_key_masked` / `qwen.api_key_masked`）渲染所有可配 key
  - 关联现有的 [model-switch.md](./model-switch.md) v1.0 + [multi-tenant.md](./multi-tenant.md) `user_settings.llm_provider`：用户级 key 配置写到自己的 user_settings 而非全局 yaml

**P1**：
- [SE-P1-1] 定时调度器卡完全缺失 → 补 `<SchedulerStatusCard />`（启动 / 停止 / 刷新 + 状态 + 任务列表）
- [SE-P1-2] 数据源状态卡缺失 → 补 `<DataSourceStatusCard />`

**P2**：
- 通用配置编辑器：列举原 settings-config 区域的所有字段并恢复（需 grep `/api/settings` 响应结构对照）
- footer 敏感字段说明
- 移动端 provider grid 单列塌陷

### 4.11 Tasks 🚨

**当前状态**（实测 2026-04-25，[TasksPage.tsx](../../stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx)）：
- ✅ 列表 + 状态过滤 chip 可用
- ❌ 只取 `?limit=50&offset=0`，**没有加载更多 / 无限滚动 / 翻页** → 用户看不到历史任务
- ❌ **无类型过滤**（analysis / screen / backtest / report / paper_trade / batch_analysis ... 全混在一起）
- ❌ **无 `scope=my|all` tab** —— 多租户场景下无法区分自己 vs 全体
- ❌ **无"查看结果"按钮 / 无跳转到对应落地页** —— 点卡片只跳 `/tasks/<id>` 详情，用户想看结果还得手动跳到对应页面

→ "历史任务 list 没了 + 跳转有问题" 复合问题，**升级为 P0 CRITICAL**。

**P0**：
- [T-P0-1] 🚨 **列表无法看历史任务** → 补无限滚动（IntersectionObserver）或 [加载更多] 按钮：
  - `apiGet("/api/tasks?limit=20&offset=<n>&scope=<my|all>&type=<any|analysis|screen_v3|...>")`
  - 移动端用无限滚动；桌面也优先无限滚动
  - 滚到底显示"已加载 N 个 · 共 M 个"

- [T-P0-2] 🚨 **新增类型过滤 chip-row** → 与状态 chip-row 并列两行：
  ```
  状态: [全部] [运行中] [等待中] [已完成] [失败] [已取消]
  类型: [全部] [AI 分析] [批量分析] [选股 V3] [回测] [报告] [纸面交易] [其他]
  ```
  - "其他"包含 qwen_fundamentals / qwen_news / agent_score_update / meta_evolution / paper_backfill / echo 等
  - 类型 chip 多选：选了"AI 分析 + 选股 V3"则同时显示两类

- [T-P0-3] 🚨 **新增 scope tab（我的 / 全部）** → 复用 [multi-tenant](./multi-tenant.md) 已实装的 `scope=my|all` 后端能力。我的（默认）= 仅自己；全部 = 含他人（admin 可见，普通用户也可见以做 transparency）

- [T-P0-4] 🚨 **每个任务行尾必须有"查看结果"按钮** + 整卡可点也跳到结果落地页（不是详情页）：
  按 task type 路由到对应 React 页面：

  | task.type | 落地页 URL（任务完成时） | 任务运行中点击行为 |
  |---|---|---|
  | `analysis` | `/analysis/<analysis_id>`（从 task.result_ref 取 id）| 跳 `/tasks/<id>` 详情看进度 |
  | `batch_analysis` | `/history?batch_id=<id>` 或 `/portfolio?from_batch=<id>` | 同上 |
  | `screen` / `screen_v2` / `screen_v3` | `/screener-v3?result=<task_id>` | 同上 |
  | `backtest` | `/backtest/<result_id>` | 同上 |
  | `report` | `/reports?id=<id>` | 同上 |
  | `paper_trade` | `/paper-trade/<ticker>`（从 params_json 取 ticker） | 同上 |
  | `paper_backfill` | `/paper-trade`（列表页）| 同上 |
  | `qwen_fundamentals` / `qwen_news` | `/analysis?ticker=<x>` | 同上 |
  | `agent_score_update` / `meta_evolution` / `echo` | `/tasks/<id>`（无业务落地页） | 同上 |

  实现：抽出 `getTaskResultUrl(task)` 函数（[lib/tasks.ts](../../stock_trading_system/web/frontend/src/lib/tasks.ts) 新增），列表行整卡 onClick 用之；额外加显式 `[查看结果 →]` 按钮（任务 success 时显示）

- [T-P0-5] 🚨 **详情页操作按钮齐全**：删除 / 重试 / 取消（仅 running/pending）/ 查看结果（success 时）

- [T-P0-6] 🚨 **任务中心完全空白**（实测 2026-04-25）
  - 根因：后端 [app.py:1710](../../stock_trading_system/web/app.py) `api_tasks_list()` 返回 `{ items: [...], limit, offset }`；前端 [TasksPage.tsx:67-69](../../stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx) fallback 链 `Array.isArray(data) ? data : (data as any).tasks || []`，**没匹配 `items` 字段** → 永远降级到空数组 `[]`
  - 修法（择一）：
    - **后端方案（推荐）**：API 改返回 `{ tasks: [...], total, limit, offset }` 符合常用约定
    - 前端方案：兜底链改为 `(data as any).items || (data as any).tasks || []`
  - 验收：`/tasks` 显示真实历史任务

**P1**：
- [T-P1-1] 任务详情 modal vs 页面 → 保留页面（已实装），但加"返回任务列表"按钮（顶部 breadcrumb）

**P2**：
- 跨页面导航兼容：`/#paper` 老书签 redirect 到 `/paper-trade`
- 任务卡片显示 task type icon（分析 / 选股 / 回测 等不同图标）
- 任务持续时间显示（"已运行 2m 35s"）
- 任务详情页加 `<ProgressStream>` 实时进度（若已实装则跳过）

## 4.13 Model-Switch UI 完全缺失 🚨🚨

### 4.13.1 现状

[docs/design/model-switch.md](./model-switch.md) v1.0 设计了顶部 Nav 模型下拉切换（Qwen ↔ Gemini）。**后端 100% 已实装**：

- [llm/router.py](../../stock_trading_system/llm/router.py) ✅ 优先级链 env > user_settings > yaml > legacy
- [app.py L1342-1370](../../stock_trading_system/web/app.py) ✅ 路由已注册：
  - `GET /api/settings/llm-provider` → `{active, has_qwen_key, has_gemini_key, locked_by_env}`
  - `POST /api/settings/llm-provider {provider}` → 切换并校验
- analyzer / nl_parser / universe / screener V3 都已用 `get_active_provider(config, user_id)`

**但前端没建任何 UI 组件**。Sidebar / NavTopbar / AppShell 里 grep 不到 `llm-provider` / `LLMSwitcher` / `model-switch`。

→ **整个用户可见层缺失**，model-switch v1.0 设计文档的"Nav 下拉"未交付。CRITICAL P0。

### 4.13.2 设计规格（参考 [model-switch.md §4.7](./model-switch.md)）

**位置**：桌面 NavTopbar 右侧（搜索框旁）；移动端 → 收进 Sidebar/更多 sheet 顶部

**组件**：`components/shared/LLMSwitcher.tsx`

```tsx
// 桌面态
<LLMSwitcher>
  ┌──────────────────────┐
  │ 模型: [● Qwen ▾]    │   ← 桌面 nav 右上
  └──────────────────────┘
       │ 点开
       ▼
  ┌──────────────────────────┐
  │ ● Qwen (通义千问)  ✓     │
  │ ○ Gemini                  │
  │ ─────────────────────    │
  │ 🔒 当前由环境变量锁定     │   ← 仅 locked_by_env=true 时显示
  └──────────────────────────┘
</LLMSwitcher>
```

**初始化逻辑**：
1. 挂载时 `apiGet("/api/settings/llm-provider")` 拉状态
2. 渲染 dropdown：当前 active 标 ✓
3. 缺 key 的选项灰显禁用（hover 提示"未配置 API key，请去设置页"）
4. `locked_by_env=true` → 整个下拉禁用 + 显示 🔒 + tooltip "由环境变量锁定，UI 不可改"

**切换逻辑**：
1. 选中另一项 → `apiPost("/api/settings/llm-provider", {provider: "gemini"})`
2. 成功 → toast.success("已切换到 Gemini，下次分析生效") + 更新本地 active state
3. 失败：
   - 400 `missing_api_key` → toast.error + 引导 "去设置页配置 Gemini API key" 的链接
   - 409 `locked_by_env` → toast.error "已被环境变量锁定"
4. 状态变化用乐观更新 + 失败回滚

**用户级覆盖**（multi-tenant 已实装）：
- alice 选 Qwen / bob 选 Gemini → 各自的 user_settings.llm_provider
- 不影响全局 yaml；env > user > yaml > legacy 优先级链 [router.py](../../stock_trading_system/llm/router.py) 已处理

### 4.13.3 实施

- [MS-P0-1] 🚨 新建 `components/shared/LLMSwitcher.tsx`（~120 LOC）
- [MS-P0-2] 🚨 集成到 NavTopbar（桌面）+ 移动 sheet 顶部
- [MS-P0-3] 🚨 处理 4 种状态：active 切换 / 缺 key 禁用 / env 锁定 / 切换中 loading
- [MS-P0-4] 错误码映射 toast 文案：missing_api_key / locked_by_env / network

### 4.13.4 测试

参见 [docs/test-cases/model-switch.md](../test-cases/model-switch.md) §7（前端 7 条 TC-MS-E1~E7）已设计；本回归只需补 React 实现，测试用例直接复用。

---

## 4.12 菜单重组（Sidebar / Mobile Tabbar 信息架构）

### 4.12.1 当前问题

现状 `<AppShell>` 的 Sidebar 是 **平铺 11 项**：

```
仪表盘 / AI 分析 / 分析记录 / 智能选股 / 持仓管理 / 预警中心
报告中心 / 策略回测 / 纸面交易 / 任务中心 / 设置
```

问题：
- 11 项一字排开 → 桌面侧栏滚动、移动 tabbar 无法容纳
- 项目类别混乱：分析 / 选股 / 持仓 / 系统 都平铺在一起
- 老 Jinja 没有这个问题（用 Bootstrap dropdown 收起一部分），React 直接平铺反而退化

### 4.12.2 新分类（6 大组 + 11 叶子）

```
═══ 概览 ═══
  · 仪表盘                  /

═══ 分析 ═══
  · AI 分析                 /analysis
  · 分析记录                /history
  · 报告中心                /reports

═══ 选股 ═══
  · 智能选股 V3             /screener-v3
  · 策略回测                /backtest

═══ 持仓 ═══
  · 持仓管理                /portfolio
  · 预警中心                /alerts

═══ 纸面交易 ═══
  · 全部会话                /paper-trade            ← 新建（PT-P0-2）
  · （单 ticker 通过列表点入 /paper-trade/<ticker>）

═══ 系统 ═══
  · 任务中心                /tasks
  · 设置                    /settings
```

**分组依据**：
- **概览**：单项，全局综合视图
- **分析**：从一个 ticker 触发 → 看历史 → 出报告，是一条信息流
- **选股**：从市场宽度发现机会 + 验证（screener + backtest）
- **持仓**：实盘持仓 + 围绕实盘的预警，强绑定
- **纸面交易**：模拟仓 + 全 session 列表，独立成组
- **系统**：基础设施（任务 / 设置）

### 4.12.3 桌面 Sidebar 设计

```tsx
// frontend/src/components/shared/Sidebar.tsx
<Sidebar>
  <SidebarGroup label="概览">
    <SidebarItem href="/" icon={<LayoutDashboard/>} label="仪表盘" />
  </SidebarGroup>

  <SidebarGroup label="分析">
    <SidebarItem href="/analysis" icon={<Brain/>} label="AI 分析" />
    <SidebarItem href="/history"  icon={<History/>} label="分析记录" />
    <SidebarItem href="/reports"  icon={<FileText/>} label="报告中心" />
  </SidebarGroup>

  <SidebarGroup label="选股">
    <SidebarItem href="/screener-v3" icon={<Target/>} label="智能选股" />
    <SidebarItem href="/backtest"     icon={<Beaker/>} label="策略回测" />
  </SidebarGroup>

  <SidebarGroup label="持仓">
    <SidebarItem href="/portfolio" icon={<Wallet/>} label="持仓管理" />
    <SidebarItem href="/alerts"    icon={<Bell/>}   label="预警中心" />
  </SidebarGroup>

  <SidebarGroup label="纸面交易">
    <SidebarItem href="/paper-trade" icon={<LineChart/>} label="全部会话" />
  </SidebarGroup>

  <SidebarGroup label="系统">
    <SidebarItem href="/tasks"    icon={<ListChecks/>} label="任务中心" />
    <SidebarItem href="/settings" icon={<Settings/>}   label="设置" />
  </SidebarGroup>
</Sidebar>
```

**视觉规范**：
- Group label：`text-[10px] uppercase tracking-wider text-muted-foreground` + 顶部 8px padding
- Group 之间 `<Separator>` 分隔（细线，opacity 0.15）
- Item active：左侧 2px accent-blue 竖条 + 背景 `--accent-blue 12%` 填色
- Item hover：背景 `--bg-secondary`
- Item 高度 36px，gap 6px

### 4.12.4 移动端 MobileTabbar 重组

旧 mobile-tabbar 显示 5 项（仪表盘/分析/选股/持仓/更多），点"更多"弹 sheet 显示其他。

新方案沿用此模式 + 调整内容：

**底部固定 5 项（≤768px 显示）**：
1. 仪表盘 `/`
2. 分析 `/analysis`
3. 选股 `/screener-v3`
4. 持仓 `/portfolio`
5. 更多（点开 sheet）

**"更多" sheet 内（4×2 grid）**：
- 分析记录 / 报告中心 / 策略回测
- 预警中心 / 纸面交易 / 任务中心
- 设置

复用 [mobile-optimization.md §3.6](./mobile-optimization.md) `more-sheet` 组件结构。

### 4.12.5 实施细节

**P0**：
- [M-P0-1] Sidebar 组件改造为分组结构（数据驱动 + `<SidebarGroup>` 抽象）
- [M-P0-2] MobileTabbar 5 主项 + 更多 sheet
- [M-P0-3] 与 PT-P0-2 联动：纸面交易组的"全部会话"指向新建的列表页

**P1**：
- [M-P1-1] Sidebar 折叠/展开（持久化 localStorage）
- [M-P1-2] 当前页面所在组自动展开 + active 高亮
- [M-P1-3] Group 名国际化预留（虽然 v1.0 只中文）

**P2**：
- 顶部面包屑显示当前 group › 当前 page
- ⌘K 命令面板内按 group 分组列出导航

### 4.12.6 兼容性

旧 hash 路由（`/#data-page=portfolio` 等）已在主方案废弃。本菜单重组**不影响**任何 URL，仅改 Sidebar 组件结构。

---

## 5. 共享改动（横切）

### 5.1 Stat 组件强制升级

[components/ui/stat.tsx](../../stock_trading_system/web/frontend/src/components/ui/stat.tsx)：
```tsx
// 当前：
<div className="text-2xl font-mono">$200,466.40</div>

// 必改为：
<div className="font-mono tabular-nums truncate"
     style={{ fontSize: "var(--fs-stat)" }}>
  $200,466.40
</div>
```

或者新建 `<NumResponsive>` 组件并强制 5 处 stat 使用（dashboard / portfolio / alerts / reports / backtest 页都有 stat）。

### 5.2 form-row-mobile 套接

所有当前用 `<div className="grid gap-4 sm:grid-cols-2">` 或 `flex sm:flex-row` 的表单 row 必须改：
```tsx
<div className="form-row-mobile">  {/* 触发 ≤575.98px 单列 */}
  <FieldA />
  <FieldB />
</div>
```

或在 Tailwind 配置自定义 utility（推荐），统一管理断点。

### 5.3 Tabs-scrollable 套接

Analysis 详情 7+ tab、Paper-trade 3 tab 在 ≤575.98px 必须 horizontal scroll：
```tsx
<TabsList className="overflow-x-auto scrollbar-hide flex-nowrap">
```

或独立组件 `<TabsListScrollable />`。

### 5.4 表格 → 卡片降级

Portfolio 持仓表 + 交易记录表、Alerts 规则表、Backtest 交易明细表必须有 ≤575.98px 卡片视图。复用 Portfolio 当前的 `hidden md:block` + `md:hidden` 模式扩到其他页。

### 5.5 ECharts 共享组件

新建 [components/shared/ChartPanel.tsx](../../stock_trading_system/web/frontend/src/components/shared/ChartPanel.tsx)：
- 包装 ECharts 初始化 + ResizeObserver + dispose
- props: `option / loading / height / theme="dark"`
- 6 个图表全部使用：dashboard 净值 + 分布、analysis K 线、backtest 净值、paper-trade 权益、portfolio 趋势

按 [ui-react-island-pages.md §3.4](./ui-react-island-pages.md) 已有 EChartsPanel 设计，**实施时直接补这一个组件即可解决 6 处图表缺失**（每页只剩配置工作）。

## 6. 实施顺序

7 Phase，每 Phase 独立 commit：

| Phase | 内容 | 估时 |
|---|---|---|
| **R-1** | 共享：升级 Stat 组件应用 `--fs-stat` clamp + 新建 ChartPanel 组件 + form-row-mobile 工具类 + Sidebar 分组重组 + MobileTabbar 5+更多 + 新建 `lib/tasks.ts::getTaskResultUrl(task)` + **新建 `<LLMSwitcher>` 组件挂 NavTopbar**（Model-Switch UI 整体补齐） | 8h |
| **R-2** | Portfolio CRITICAL：卖出表单 + 修正成本 modal | 2h |
| **R-3** | Paper-trade CRITICAL：**新建列表页 island /paper-trade** + 权益曲线 + 日度 tab + **修复 ticker 详情空白 bug**（pathname.split） | 5h |
| **R-3b** | **Tasks CRITICAL：API schema 修复（items→tasks）+ 分页/无限滚动 + 类型 chip-row + scope tab + 整卡跳转结果落地页 + 详情操作完整** | 5h |
| **R-4** | Dashboard CRITICAL：净值图 + 分布饼图 + 移动塌陷 | 2h |
| **R-5** | Analysis CRITICAL：K 线 + 7-tab 报告 + Pipeline DAG | 5h |
| **R-5b** | Settings P0：补 GEMINI_API_KEY + QWEN_API_KEY 字段（前端硬编码列表追加 + label 改善） | 1h |
| **R-6** | HIGH 批次（约 18 项）：history 对比 / portfolio 交易表 / alerts 模板 / backtest 结果 / settings 调度器+数据源 | 15h |
| **R-7** | MEDIUM + 移动端兜底：所有页 grid `≤575.98px` 单列规范化 + form-row-mobile 套接 + tabs-scrollable + 表格卡片降级 | 11h |

P0 = R-1 ~ R-5b（共 ~28h，含菜单重组 + 列表页 + Tasks 改造 + LLMSwitcher + Settings keys），P1 = R-6（~15h），P2 = R-7（~14h）。

**总修复工时 ~57h**。

### 6.1 R-1.x 收尾批次（P0 余项）

R-1 ~ R-7 落地后实测，**v1.4 已知 6 项 + v1.5 新发现 6 项 = 共 12 项 P0 未完成**。本批次集中收尾，~12h（v1.4 ~5h + v1.5 新增 ~7h）。**严格不动已完成的 19 项**。

#### v1.4 已知（5h）：
- **R-1.1 LLMSwitcher**（4 项 = MS-P0-1~4，~3h）
- **R-5b Settings keys**（1 项 = SE-P0-1，~10min）
- **R-5.1 Pipeline DAG**（1 项 = A-P0-3a，~2h）—— 注意 v1.5 已确认 DAG 组件存在但**只在表单视图里**，需移到详情视图

#### v1.5 新增（~7h）：
- **R-1.2 History → Analysis 链接修复**（HE-P0-1，~30min）
- **R-1.3 Dashboard 死链修复 backtest-v2**（D-P0-5，~5min）
- **R-5.2 Analysis 补 News + 基本面 quick-info 侧卡**（A-P0-5，~1h）
- **R-5.3 Analysis K线换 TradingView widget**（A-P0-4，~1.5h）
- **R-5b.2 Screener V3 结果页**（SV3-P0-1，~2h）—— 全新建，从 0 到 1
- **R-6b Backtest 结果详情页**（B-P0-1，~2h）—— 全新建

#### v1.6 新增（~1.5h）：
- **R-perf 后端价格层缓存 + request-scoped memoize**（PERF-P0-1，~1.5h）

#### v1.7 新增（~1.5h）：
- **R-3.1 Paper-trade ticker 空白真修**（PT-P0-4，~30min）
- **R-5.4 分析提交后留在 /analysis 流式显示**（A-P0-7，~1h）

##### R-3.1 · Paper-trade ticker 空白真修

实测 [PaperTradePage.tsx:68](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx)：
```ts
const ticker = window.location.pathname.split("/").pop()?.toUpperCase() || ""
```
**仍是老代码**！v1.3 PT-P0-3 标"DONE"是误判，前一轮 audit 当时没真验证。需要真改。

修法：
```ts
const ticker = window.location.pathname
  .replace(/\/+$/, "")           // 去末尾斜杠
  .split("/")
  .filter(Boolean)
  .pop()
  ?.toUpperCase() || ""
```

或更稳健用 URL match：
```ts
const m = window.location.pathname.match(/\/paper-trade\/([^/?#]+)/)
const ticker = m?.[1]?.toUpperCase() || ""
```

**额外**：检查"完全空白"是否还有别的根因——
1. `LoadingSkeleton` 实现是否真渲染（不是返回 null）：现在是 `<LoadingSkeleton />`，确认组件存在；如果 import 路径有问题会渲染空
2. API `/api/paper/tickers/META` 真实响应：如果 META 没有 paper session，应该返回 `{ session: null }` 而非 500
3. 加 React error boundary：`<ErrorBoundary fallback={<Alert>页面渲染异常</Alert>}>` 包裹整个 PaperTradePage 内容，避免 JS 抛错时整页空白

验收：
- `/paper-trade/META` (无 session) 显示 "未找到 META 的纸面交易会话" Alert
- `/paper-trade/NVDA/`（有末尾斜杠）也正确解析 NVDA
- JS 抛错也有可见错误，不再纯空白

##### R-5.4 · 分析提交后留在 /analysis 流式显示

实测 [AnalysisPage.tsx:85](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)：
```ts
if (res.task_id) setTimeout(() => { window.location.href = `/tasks/${res.task_id}` }, 800)
```
提交后 800ms 跳 `/tasks/<id>`——**用户看不到分析专属 UI**（Pipeline DAG / 7-tab 流入），跳到通用任务详情页只能看进度条和事件流，体验严重退化。

老 Jinja 行为：提交后留在 `/analysis`，inline 显示 DAG + 阶段流入 + 7 tab 渲染。

修法（需配合 R-5.1 Pipeline DAG 移到详情视图）：
1. 提交成功后**不跳 `/tasks/<id>`**，改跳 `/analysis/<task_id>`（或 `/analysis?task_id=<id>`）
2. AnalysisDetailView 顶层判断：
   - 若有 `task_id`（任务运行中）→ 显示 `<PipelineDAG taskId={task_id}>` + 7 tab 占位 skeleton
   - 任务完成（task_completed event）→ 取 `result_ref` 解析为 analysis_id → 重定向 `/analysis/<analysis_id>` 或就地把 7 tab 填满（取分析数据）
   - 若是历史 detailId → 直接显示完整详情
3. 保留 `[查看任务详情]` 链接给想看通用进度的用户

实施细节：
- AnalysisPage 顶层路径解析新增中间态：
  ```ts
  const path = window.location.pathname  // /analysis/<id>
  const id = path.startsWith("/analysis/") ? path.split("/")[2] : null
  // 判断 id 是否是 task_id（UUID）还是 analysis_id（int）
  // 简单规则：长度 > 10 视为 task_id；纯数字视为 analysis_id
  const idType = id && id.length > 10 ? 'task' : 'analysis'
  ```
- 表单 handleSubmit 改：
  ```ts
  if (res.task_id) window.location.href = `/analysis/${res.task_id}`
  ```
- 后端 Flask 加路由 `@app.route("/analysis/<id>")` 兼容 task_id（已在 R-1.2 改成无 int 限定）

验收：
- 点 [开始分析] → 跳 `/analysis/<task_id>` 立即显示 DAG
- 阶段逐个变绿（market_agent → ... → trader）
- 完成后自动切 7-tab 报告（或重定向到 `/analysis/<analysis_id>`）
- 移动端 DAG 纵向流

##### R-perf · 性能优化详细规格

**根因**（实测 2026-04-25 晚）：
- [app.py:594-604](../../stock_trading_system/web/app.py) `/api/dashboard` 调 `get_pnl()` + `get_history()`，**`get_pnl()` 内部又调 `get_holdings()` 拉所有股票实时价**
- [app.py:646](../../stock_trading_system/web/app.py) `/api/portfolio/allocation` 调 `get_allocation()` → 内部又调 `get_holdings()` 拉一次实时价
- [app.py:610](../../stock_trading_system/web/app.py) `/api/portfolio/holdings` → 拉一次实时价
- [PortfolioPage.tsx:42-46](../../stock_trading_system/web/frontend/src/islands/portfolio/PortfolioPage.tsx) Promise.all 调 holdings + summary（summary 内部又调 get_pnl → get_holdings）

**单页加载实测**：
- Dashboard: `/api/dashboard` + `/api/portfolio/allocation` = **2 次全量价格拉取**
- Portfolio: `/api/portfolio/holdings` + `/api/portfolio/summary` = **2 次全量价格拉取**

**单股价格拉取**：[data_manager.py](../../stock_trading_system/data/data_manager.py) `get_price()` 走 yfinance/Qwen/AkShare 网络 API，~200-800ms/股
**总耗时**：8 股并发 8 ≈ 800ms × 2 批 = **1.6-3 秒**

**修法（A + B 双管齐下，~1.5h）**：

##### Layer A · request-scoped memoize（~30min）

[stock_trading_system/portfolio/manager.py:112](../../stock_trading_system/portfolio/manager.py) `PortfolioManager.get_holdings()` 加 Flask `g` 级别缓存：

```python
def get_holdings(self) -> list[dict]:
    from flask import g, has_request_context
    if has_request_context() and hasattr(g, "_holdings_cache"):
        return g._holdings_cache
    # ... existing logic ...
    result = [...]
    if has_request_context():
        g._holdings_cache = result
    return result
```

收益：单次 HTTP request 内 get_holdings 仅一次实际拉价；同 request 内多次调用直接 hit cache。

Dashboard / Portfolio 各省 1 次价格拉取 → ~3s → ~1.5s（**砍半**）。

##### Layer B · 价格层 30s TTL 缓存（~1h）

[data_manager.py](../../stock_trading_system/data/data_manager.py) `get_price()` 复用现有 [data/local_cache.py](../../stock_trading_system/data/local_cache.py) 的 `LocalCache`：

```python
def get_price(self, ticker: str, market: str = "US") -> dict:
    cache_key = f"price:{ticker}:{market}"
    cached = LocalCache.get(category="quote", key=cache_key, max_age=30)  # 30s TTL
    if cached is not None:
        return cached
    # ... existing fetch logic ...
    LocalCache.set(category="quote", key=cache_key, value=data, ttl=30)
    return data
```

收益：30 秒内复访任意页面 0 网络拉取；首次访问仍走网络但第二次几乎即时。

##### 验收

- 第一次访问 `/`：< 1.5s（含全部图表）
- 30 秒内复访 `/portfolio` / `/`：< 200ms
- F5 刷新 5 次连续：第 1 次稍慢，第 2-5 次都 < 200ms
- 单次 request log 中 `data_manager.get_price` 调用次数 = 持仓股数（不是 2× 或 3×）
- Network 面板 `/api/dashboard` 响应 ≤ 1s（首次）/ ≤ 50ms（缓存命中）

##### 风险

- LocalCache 写并发安全：已自带（基于 SQLite WAL）
- 价格 30s 内可能略滞后：可接受（K 线 / 实时图本来就有延迟）
- 用户主动刷新需即时新数据：可加 `?fresh=1` 参数旁路缓存（v1.7 议题，本期不做）

#### 6.1.1 [R-1.1] LLMSwitcher 组件 + Sidebar 集成（~3h）

- 新建 `components/shared/LLMSwitcher.tsx`（~150 LOC）
- 用 shadcn `<DropdownMenu>` + `<DropdownMenuRadioGroup>` 实现切换
- 接 `GET /api/settings/llm-provider` 拉状态、`POST /api/settings/llm-provider` 切换
- 4 状态完整：active 切换 / 缺 key 选项灰显（label 加"未配置"）/ env 锁定整下拉禁用 + 🔒 / 切换 loading
- 错误码 toast 映射：
  - 400 `missing_api_key` → toast.error 含 "[去设置]" action 跳 `/settings`
  - 409 `locked_by_env` → toast.error "已被环境变量锁定"
  - 网络错 → toast.error "切换失败" + 回滚 active state
- 集成位置：
  - 桌面 [Sidebar.tsx](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx) Logo 下方
  - 移动 sheet 顶部（菜单 item 之前）
- 验收：TC-RG-P0-21, P0-22

#### 6.1.2 [R-5b] Settings 补 2 个 API key 字段（~10min）

- 编辑 [SettingsPage.tsx:227](../../stock_trading_system/web/frontend/src/islands/settings/SettingsPage.tsx) hardcoded API_KEYS 列表追加 2 项 + 改 1 项 label：
  ```ts
  { key: "DASHSCOPE_API_KEY",  label: "Qwen API Key (DashScope)" },   // 改 label
  { key: "GEMINI_API_KEY",     label: "Gemini API Key" },             // 新增
  { key: "QWEN_API_KEY",       label: "Qwen API Key (备用)" },        // 新增
  ```
- 验收：TC-RG-P0-20

#### 6.1.3 [R-5.1] Pipeline DAG 可视化（~2h）

- 新建 `components/shared/PipelineDAG.tsx`
- 数据：`subscribeTaskStream` 监听 `event=='agent_stage_done'` 事件
- 9 个固定阶段（按 TradingAgents 顺序）：
  ```
  market_agent → sentiment_agent → news_agent → fundamentals_agent
   → bull_researcher → bear_researcher → judge → risk_manager → trader
  ```
- 节点状态机：pending（灰）/ running（蓝色脉冲）/ done（绿✓）/ failed（红✗）
- 桌面横向流 + 连线箭头；移动端 ≤575.98px 改纵向流
- 点击节点 popover 展示该阶段简要 reasoning（若 payload 含）
- 集成：[AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) status='running' 时在结果区上方插入
- 验收：TC-RG-P0-8

#### 6.1.4 [R-3b.1] Tasks schema —— ✅ 已完成

实测确认：
- 后端 [app.py:1713-1719](../../stock_trading_system/web/app.py) 已返回 `{tasks, items, total, limit, offset}` 双字段
- 前端 [TasksPage.tsx:70](../../stock_trading_system/web/frontend/src/islands/tasks/TasksPage.tsx) fallback 链 `(data as any).tasks || (data as any).items || []`

T-P0-6 schema 不再需要修。若用户实测 `/tasks` 仍空白，排查方向（不在 R-1.x 范围）：
1. DB 实际是否有 task 记录：`SELECT COUNT(*) FROM tasks WHERE created_by = <current_user>`
2. 前端 type chip 默认值是否过滤过严（应默认空过滤）
3. scope 默认 "我的" 时当前登录用户是否有任务（admin 应该有）
4. 浏览器 Network 直查 `/api/tasks?limit=20` 返回 JSON，确认 `tasks` 字段实际有值

#### v1.7 新增（~1.5h）：

##### R-3.1 · Paper-trade ticker 详情空白真修（PT-P0-4，~30min）

[PaperTradePage.tsx:68](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) 当前仍是老代码：
```ts
const ticker = window.location.pathname.split("/").pop()?.toUpperCase() || ""
```
URL 末尾 `/` 时返回空 → "未指定股票代码"。v1.3 PT-P0-3 标 DONE 是 audit 误判。

修法（择一）：
- 方案 A regex：`const m = pathname.match(/\/paper-trade\/([^/?#]+)/); const ticker = m?.[1]?.toUpperCase() || ""`
- 方案 B filter：`pathname.replace(/\/+$/,"").split("/").filter(Boolean).pop()?.toUpperCase() || ""`

加 React ErrorBoundary 包裹 PaperTradePage（避免 JS 抛错全黑屏）。

##### R-5.4 · 分析提交后留在 /analysis 流式显示（A-P0-7，~1h）

[AnalysisPage.tsx:85](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 当前提交后跳 `/tasks/<id>`：
```ts
if (res.task_id) setTimeout(() => { window.location.href = `/tasks/${res.task_id}` }, 800)
```
用户看不到 Pipeline DAG / 7-tab 流入，体验严重退化。

修法（与 R-5.1 Pipeline DAG 联合）：
- 跳 `/analysis/<task_id>` 而非 `/tasks/<id>`
- AnalysisPage 顶层判断三种态：表单（无 id）/ 运行中（id 长度>10 视为 task UUID）/ 完成态（纯数字 analysis_id）
- 运行中态显示 PipelineDAG + 7 tab 占位 skeleton；订阅 `task_completed` 事件取 result_ref 切换到完成态
- 后端 `@app.route("/analysis/<id>")` 去掉 int 限定（已在 R-1.2）

#### v1.8 新增（~2h）：

##### D-FEAT-1 · 仪表盘净值曲线自动回溯（~1h）

**问题**：当前 [app.py:598](../../stock_trading_system/web/app.py) `/api/dashboard` 调 `pm.get_history(days=30)` 固定 30 天。用户希望"从有数据开始的所有日期"。

**修法**：
- 后端：[portfolio/manager.py](../../stock_trading_system/portfolio/manager.py) `get_history(days=None)` 默认 None 时返回全部 daily_snapshots（按 date asc）
- 数据库层：[portfolio/database.py](../../stock_trading_system/portfolio/database.py) `get_snapshots(days=None)` 兼容 None → `SELECT * FROM daily_snapshots WHERE user_id=? ORDER BY date ASC`
- API 端：`/api/dashboard` 返回的 history 字段不限天数；前端可选 query `?history_days=all|N` 灵活控制
- 缺日补全（可选 v1.9）：snapshots 不连续时用 transactions + 历史价格反推（暂不做，先按现有 snapshots 全量返）

**前端**：
- [DashboardPage.tsx](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 净值曲线 ChartPanel：
  - X 轴改为 `time` 类型自适应天数密度（数据 < 60 天显示日级、>= 60 < 180 显示日级 + 周筛、>= 180 周/月聚合）
  - 加 range switcher chip：`全部 / 1Y / 6M / 3M / 1M / 7D`，默认"全部"
  - dataZoom 横向滚动条（数据多时启用）

**验收**：
- 持仓系统已运行 90 天 → 默认显示 90 天曲线（不再固定 30）
- range switcher 切换可缩短到 1M / 7D 局部细节
- 移动端 ≤575.98px 默认显示近 90 天，长按可拖滑

##### P-FEAT-1 · 持仓表加盈亏绝对值列（~1h）

**问题**：当前 [PortfolioPage.tsx](../../stock_trading_system/web/frontend/src/islands/portfolio/PortfolioPage.tsx) 持仓表只显示 `pnl_pct` 百分比，缺绝对值（如 +$1,235.40）。

**后端**：已就绪。[portfolio/manager.py:141](../../stock_trading_system/portfolio/manager.py) `get_holdings()` 已计算 `pnl = (current_price - pos.avg_cost) * pos.shares` 并返回。

**前端**：
- 持仓 DataTable 在"收益率%"列前/后加一列"盈亏 $"：
  ```
  代码  持仓  成本  现价  盈亏 $        盈亏 %    信号
  NVDA  10    180   210   +$300.00     +16.7%    BUY
  ```
- 盈亏 $ 用 `<NumResponsive>`（v1.0 已加）+ `font-mono tabular-nums`
- 颜色规则：>0 绿、<0 红、=0 灰
- 移动端卡片视图同步加一行"盈亏 $1,235.40"

**额外**：dashboard 持仓概览（top 3）也加盈亏 $ 列。

**验收**：
- 桌面 / 移动 持仓表都有盈亏 $ + 盈亏 % 两列
- 长数字（$200,466.40）应用 num-responsive 不溢出
- 总值卡 "总盈亏" 同步用绝对 $ 显示

#### v1.9 新增（~3h）：

##### A-P0-8 · AI 分析运行中态完整布局（~3h，强化 A-P0-7 + A-P0-3a + A-P0-5 一起做）

**问题**（实测 2026-04-26）：点 [开始分析] 后页面只显示 "任务已提交 任务 ID: ..."，**整页空白**。用户期望看到：
1. 个股 K 线（即时可见，独立于 AI 分析）
2. 最近新闻（即时可见）
3. 基本面指标（即时可见）
4. AI 分析 Pipeline DAG 实时进度
5. 7-tab 报告占位 skeleton（agent 完成后逐个填充）

**核心理念**：运行中态本身是个有用的 dashboard，K线/新闻/基本面是 ticker 的"客观数据"——独立于 AI 分析，提交后**立即可拉**。Pipeline DAG 单独负责显示 AI 推理进度。这样用户提交分析后**立刻有内容看**，不用空等 3-5 分钟。

**实施**：

A. AnalysisPage 路径解析升级（与 R-5.4 合并）：
   - `/analysis` → 表单视图
   - `/analysis/<id>`（id 长度 > 10 视为 task_id UUID）→ **运行中态**（本节重点）
   - `/analysis/<id>`（纯数字 analysis_id）→ 完成态（详情视图）

B. handleSubmit 改：
   原: `window.location.href = '/tasks/' + task_id`
   改: `window.location.href = '/analysis/' + task_id`

C. 运行中态 `<AnalysisRunningView taskId={task_id} ticker={ticker} date={date}>` 布局（桌面）：

```
┌─ Header ──────────────────────────────────────────────────┐
│ {ticker} 分析中  · {date} · 模型: {provider}              │
│                                          [查看任务详情链接] │
└────────────────────────────────────────────────────────────┘

┌─ 主图区 ──────────────────────────────────────────────────┐
│ K 线图（TVChart 或 ECharts，独立拉 /api/quote/history）   │
│ 高度 ~360px                                                 │
└────────────────────────────────────────────────────────────┘

┌─ Pipeline DAG ────────────────────────────────────────────┐
│ market_agent → sentiment → news → fundamentals →           │
│   bull → bear → judge → risk → trader                      │
│ 节点状态：pending(灰) / running(蓝脉冲) / done(绿✓) / failed(红×) │
│ 订阅 subscribeTaskStream 接 agent_stage_done 事件           │
└────────────────────────────────────────────────────────────┘

┌─ 三列侧卡（桌面 grid-cols-3，≤575.98px 单列）────────────┐
│ 新闻 quick   │ 基本面 quick │ 多空比快览（占位）           │
│ 5 条最新新闻  │ PE/ROE/D/E   │ 等 judge 完成              │
│ + 来源 + 时间 │ 关键 5 指标   │ → 显示 bull/bear count       │
│ /api/news/<ticker> │ /api/fundamentals/<ticker> │             │
└──────────────┴──────────────┴──────────────────────────────┘

┌─ 7 Tab 报告占位（Skeleton 逐个填充）──────────────────────┐
│ [技术面] [基本面] [情绪] [新闻] [多空辩论] [风险] [决策]   │
│                                                              │
│ 当前 tab 内容：                                              │
│   pending → "等待 market_agent 完成..."                     │
│   running → spinner + "市场分析中（已耗时 12s）"            │
│   done    → 渲染对应 markdown 内容（react-markdown）        │
│                                                              │
│ 监听规则：每个 agent_stage_done 事件 envelope.payload.stage │
│   = 'market' / 'sentiment' / 'news' / ... 对应填充           │
└────────────────────────────────────────────────────────────┘
```

D. 数据获取（运行中态首次挂载并发拉，独立于任务状态）：
```ts
useEffect(() => {
  Promise.all([
    apiGet(`/api/quote/history?ticker=${ticker}&days=180`).catch(() => null),
    apiGet(`/api/news/${ticker}?limit=5`).catch(() => []),
    apiGet(`/api/fundamentals/${ticker}`).catch(() => null),
  ]).then(([ohlc, news, fund]) => { /* setState */ })
}, [ticker])
```

E. SocketIO 订阅：
```ts
useEffect(() => {
  const sub = subscribeTaskStream({
    taskIds: [taskId],
    onEvent: (env) => {
      if (env.event === 'agent_stage_done') {
        const { stage, content } = env.payload
        // stage = 'market' / 'sentiment' / ...
        setReports(prev => ({ ...prev, [stage]: content }))
        setDagState(prev => ({ ...prev, [stage]: 'done' }))
      } else if (env.event === 'task_completed') {
        const m = env.payload.result_ref?.match(/analysis_history:(\d+)/)
        if (m) {
          window.history.replaceState(null, '', `/analysis/${m[1]}`)
          // 切换到完成态视图
          setMode('completed'); setAnalysisId(parseInt(m[1]))
        }
      }
    }
  })
  return () => sub.destroy()
}, [taskId])
```

F. 移动端 ≤575.98px 重排：
   - K 线高度降到 240px
   - 三侧卡变垂直堆叠
   - DAG 改为纵向流（一条竖线 + 节点）
   - 7 tabs 套 tabs-scrollable 横滑

**验收**：
- 点 [开始分析] 立即跳 `/analysis/<task_id>` 页面**有完整内容**（K线 + 新闻 + 基本面 + DAG + 7-tab 占位）
- 不再"任务已提交"白屏
- 第 0 秒：K线/新闻/基本面已渲染（数据 < 1s 拉到）
- 第 N 秒：DAG 节点逐个变绿，对应 tab 内容流入
- 完成后：URL 切到 `/analysis/<analysis_id>`，视图变为完成态详情视图
- 移动端三侧卡垂直堆叠，DAG 纵向流

**复用**：
- `<TVChart>` 来自 R-5.3
- `<PipelineDAG>` 来自 R-5.1（移到运行中态）
- 新闻/基本面 quick card 来自 R-5.2

A-P0-8 实质上把 R-5.1 / R-5.2 / R-5.3 / R-5.4 合并成一个完整的"运行中 dashboard"页，工作量已包含在前面那些子任务里，这里只补**布局组合 + 三个独立数据 fetch + DAG 事件 → tab 填充的桥接逻辑**（~3h）。

#### v1.10 新增（生产实测仍未真修，~3h）：

##### R-fix-1 · 净值曲线 backend days=30 硬编码（~15min）

[app.py:762](../../stock_trading_system/web/app.py)：
```python
history = pm.get_history(days=30)  # ← 硬编码
```
**未根据 v1.8 改动。** 前端 ChipRow 切换"全部"也只能拿 30 天数据。

修法：
- 改为 `history = pm.get_history(days=request.args.get('history_days', 'all'))`
- `get_history(days)` 兼容 `days='all'` / `days=None` → 返全量；否则按整数过滤
- 前端 [DashboardPage.tsx](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 默认请求 `?history_days=all`

验证：用户从 2026-04-14 起的 daily_snapshot → 1Y 视图应连续显示所有可用日期。

##### R-fix-2 · Dashboard 持仓 top 3 加绝对值列（~30min）

[DashboardPage.tsx](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 持仓概览部分（v1.8 P-FEAT-1 漏改）：
- 找到 holdings.slice(0, 3) 渲染处
- 每行加一个 `+$1,235.40 / -$890.50` 绝对值字段（与 PortfolioPage 一致）
- 颜色规则同 portfolio：>0 绿 / <0 红 / =0 灰
- 移动端 m-card 同步

##### R-fix-3 · Screener V3 结果 ID 不匹配（~30min）

**根因**：
- [ScreenerV3Page.tsx:228] 前端 `apiGet('/api/screen/v3/results/${resultId}')` 中 `resultId` 是 URL ?result= 的 task_id（UUID）
- 后端 [app.py:2147] `@app.route("/api/screen/v3/results/<result_id>")` 期望整数 `screen_results_v2.id`

修法（择一）：
- 方案 A（推荐）：后端路由接受 `task_id`：先 lookup `tasks.result_ref` 解析 `screen_results_v2:<id>` 得真实 result_id 再查
- 方案 B：前端 task_completed 事件时取 `result_ref.id` 整数，URL 用整数（不用 task_id）

方案 A 实现：
```python
@app.route("/api/screen/v3/results/<task_or_result_id>")
def api_screen_v3_result(task_or_result_id):
    # 优先按 task_id (UUID) 查
    task = task_store.get(task_or_result_id)
    if task and task.result_ref:
        m = re.match(r"screen_results_v2:(\d+)", task.result_ref)
        if m: return _fetch_result(int(m.group(1)))
    # 兼容旧整数 ID
    if task_or_result_id.isdigit():
        return _fetch_result(int(task_or_result_id))
    return jsonify({"error": "result_not_found"}), 404
```

##### R-fix-4 · Paper-trade ErrorBoundary 内部 throw（~30min）

ErrorBoundary 已加并触发，需查 [PaperTradeContent](../../stock_trading_system/web/frontend/src/islands/paper-trade/PaperTradePage.tsx) 内部具体抛错点。

排查清单：
1. ticker 解析后 `apiGet('/api/paper/tickers/${ticker}')` 失败时 setState `error` 是否安全
2. `data.session.metrics` 等深字段在 data.session=null 时是否 null-safe
3. `data.events.map()` 时 events 是否可能 undefined
4. ORDER_LABELS / STATUS_ICONS lookup 是否有未知 key 触发 React 警告或 crash
5. plan 数据缺关键字段（fingerprint / orders）时图表是否能渲染

修法：在 PaperTradeContent 中所有 `.map()` / 字段访问加 `?.` / `|| []` 兜底；保持 ErrorBoundary 不变作最后防线。

实测：调浏览器 DevTools console 看抛错堆栈，逐个修。

#### v1.12 新增（数据回填 + 调度器修复，~3h）：

##### R-fix-6 · 净值曲线真·自动回溯（v1.11 没修对的本质）

**实测数据**（生产 2026-04-30）：
- daily_snapshots: 3 行（2026-04-14, 04-15, 04-16, 04-19）
- transactions: 25 行，最早 2026-04-12
- 距今 18 天的可回溯期，**缺 11 天 snapshot**
- task_scheduler.py:105 已写 `self._portfolio_manager.take_snapshot()` 但没真起作用

v1.11 修了"返全量"的后端代码，但**忘了真正的设计意图：从最早 transaction 起每个交易日都要有 snapshot**。

##### R-fix-6a · 历史回填脚本（~1h）

新建 [stock_trading_system/migrations/backfill_daily_snapshots.py]：

```python
"""
回填从最早 transaction 到今天的所有交易日 daily_snapshot。
算法：
  for date in 交易日(earliest_txn_date, today):
    positions_at_date = 重放 transactions 至 date 末
    closing_prices = yfinance 拉每只 ticker 在 date 当日 close（缓存）
    total_value = sum(shares * close_price)
    total_cost = sum(shares * avg_cost)
    pnl = total_value - total_cost
    upsert daily_snapshots(user_id, date, total_value, ...)
幂等：若 (user_id, date) 已存在则 SKIP（保留已有数据，避免覆盖手动快照）

Usage:
  python -m stock_trading_system.migrations.backfill_daily_snapshots --dry-run
  python -m stock_trading_system.migrations.backfill_daily_snapshots --user-id=1
  python -m stock_trading_system.migrations.backfill_daily_snapshots --all-users
"""
```

实施细节：
- 交易日列表用 yfinance/exchange_calendars 取（跳过周末/假日）；fallback 用所有自然日
- 历史价格走 yfinance.Ticker.history(start, end)，批量拉减少 API 调用
- 进度打印 `[2026-04-15] 5 positions, total=$200,123.45 ✓`
- 统计输出回填行数 / 跳过行数 / 失败行数

##### R-fix-6b · 修复每日调度器（~1h）

排查 [task_scheduler.py:105](../../stock_trading_system/scheduler/task_scheduler.py) 为什么没跑：
1. APScheduler 是否启动？grep `scheduler.start()` / `BackgroundScheduler` 启动调用点
2. cron 表达式是否正确？应在美股 close 后（北京时间次日 04:30 或 05:00）
3. 进程是否长期运行？Railway 部署可能 restart 时丢调度器状态
4. 单租户 vs 多租户：scheduler.take_snapshot() 是否对每个 user_id 都跑？

修法：
- 启动检查：app 启动时打印 `[scheduler] running, next snapshot at <time>`
- 改 APScheduler 为 cron 触发：每日 美东 16:30（=北京次日 04:30）
- 多用户：迭代所有 active users，对每个 user_id 调 take_snapshot(user_id)
- 失败重试 + 错误日志

##### R-fix-6c · UI 触发入口 + status（~30min）

[DashboardPage.tsx] 净值曲线右上角加按钮 [↻ 重新计算]，点击：
- `apiPost('/api/portfolio/snapshots/backfill', { from: 'earliest' })`
- 弹 toast："正在回填历史净值，约 1 分钟..."
- 后端异步任务（task_manager）跑 backfill 脚本
- 完成后 dashboard 自动 reload 数据

后端新端点：
```python
@app.route("/api/portfolio/snapshots/backfill", methods=["POST"])
@login_required
def api_backfill_snapshots():
    task_id = task_manager.submit("backfill_snapshots", {
        "user_id": g.user.id,
        "from": request.json.get("from", "earliest"),
    })
    return jsonify({"task_id": task_id})
```

worker 调 backfill 脚本主函数（不是子进程）。

##### R-fix-6d · Settings 页加"调度器状态"卡（~30min）

[SettingsPage.tsx] 加一卡显示：
- 调度器运行状态：✓ Running / ✗ Stopped
- 上次快照时间：2026-04-30 04:30:12
- 下次快照时间：2026-05-01 04:30:00
- [立即跑一次] 按钮（管理员）
- [重启调度器] 按钮（管理员）

后端：
- `GET /api/scheduler/status` → { running, last_run, next_run, jobs: [...] }
- `POST /api/scheduler/run-now` → 手动触发 take_snapshot

**验收**：
- 跑 `python -m stock_trading_system.migrations.backfill_daily_snapshots --dry-run` 显示需回填 ~11 天
- 跑实施后 `SELECT COUNT(*) FROM daily_snapshots` 应 ≥ 14（含原 3 行 + 回填 11 行）
- Dashboard 净值曲线 ALL 视图显示 14 个连续点（2026-04-14 → 2026-04-30）
- ChipRow 7D / 1M / 3M 切换正确缩窄
- 调度器 status 卡显示 Running + next_run 时间正确

##### R-fix-5 · K 线区域空白（~1h）

`<TVChart data={klineData}>` 组件已就位（v1.9 R-5.3 落地），但 klineData 拉不到数据。

诊断：
- [AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 哪个 useEffect / fetch 给 klineData 赋值？
- 后端是否有 `/api/quote/history` 端点？grep app.py 看
- 若没有该端点，新增：
  ```python
  @app.route("/api/quote/history")
  def api_quote_history():
      ticker = request.args.get("ticker")
      days = int(request.args.get("days", 90))
      from stock_trading_system.data.data_manager import DataManager
      dm = DataManager(load_config())
      bars = dm.get_history(ticker, days=days)  # 返 [{date, open, high, low, close, volume}]
      return jsonify({"ticker": ticker, "bars": bars})
  ```
- 前端 fetch 后 setState `klineData` 数组

验证：SOXL 详情页"K 线走势（近 3 个月）"区域应渲染交互式 TVChart。

---

#### v1.13 新增（AI 分析模块产品&技术缺口，~10h）：

##### R-fix-7 · AI 分析 7 大缺口（用户提）

实测痛点（生产 2026-04-30）：
- 详情页 K 线区域空白：[TVChart.tsx:108](../../stock_trading_system/web/frontend/src/components/shared/TVChart.tsx) `if (loading && data.length === 0) return <Skeleton/>` → 初始 `containerRef` 不渲染 → chart-init useEffect (`[height]`) 跑时 `containerRef.current=null` 直接 return → 数据到达后 div 挂载但 chart 已经"放弃" → 永远空
- 历史元数据残缺：[analysis_history](../../stock_trading_system/portfolio/database.py) schema 有 model 但缺 `created_by / provider / config_hash / task_id / duration_sec / bookmarked`；[task_store._save_analysis_result](../../stock_trading_system/tasks/task_store.py) INSERT 12 列，连 model 都不写
- 双入口未统一：[/api/analyze](../../stock_trading_system/web/app.py)（app.py:852）daemon thread + 直写 history + 硬编码 gemini config；TaskManager 走 [workers.py make_analysis_worker](../../stock_trading_system/tasks/workers.py) → TaskStore 走 generic insert。两条路对元数据写入完全不一致
- advice 与共享研究未拆分：advice_json 含 holdings_context 当前用户持仓数据，与共享研究存在同一行 → 其他用户拉 `/api/history/<id>` 时看到的 advice 来自原作者持仓
- `/analysis` 首页缺最近卡 + 深度选择 + 8 tab + 决策独立 tab + 操作按钮齐
- Markdown 无 sanitize，LLM 输出可注入 HTML
- `_record_agent_scores` [workers.py:135](../../stock_trading_system/tasks/workers.py) 为拿 analysis_id 先 `db.save_analysis({ticker, date, signal, 5 reports})` 半成品行 → 然后 worker 主路径 `_save_analysis_result` 又插一行完整数据 → 同次分析 2 行

##### R-fix-7A · 修 TVChart 初始 Skeleton 吃掉容器（~30min）

[stock_trading_system/web/frontend/src/components/shared/TVChart.tsx](../../stock_trading_system/web/frontend/src/components/shared/TVChart.tsx)：
- **删除**末尾 `if (loading && data.length === 0) return <Skeleton .../>`
- **改**为始终 `return <div ref={containerRef} style={{height, position: 'relative'}}>` + 内嵌状态层（loading / empty / error 三态 overlay 盖在 chart 之上）
- 状态层用绝对定位 `inset-0`，`pointer-events-none`，背景半透明深色 + Spinner / 提示文字 / 重试按钮
- props 加 `onRetry?: () => void` 用于 empty / error 显示重试按钮
- chart-init useEffect 依赖不变（仍 `[height]`），但 containerRef 永远存在 → init 永远跑

[AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) `AnalysisDetailView`：
- 加 `klineState: 'loading' | 'ok' | 'empty' | 'error'`，初值 `'loading'`
- 主路径 `apiGet('/api/quote/history?ticker=&days=90')` 失败或 bars=[] → fallback `/api/chart/<ticker>?period=3mo&interval=1d` 解析为 OHLCV
- 双源都失败/空 → `setKlineState('empty')`，传给 TVChart 显示"暂无 K 线数据"+ 重试按钮
- TVChart props: `<TVChart data={klineData} state={klineState} onRetry={refetchKline} height={380} />`

##### R-fix-7B · 扩 analysis_history schema + TaskStore 写元数据（~1.5h）

[stock_trading_system/portfolio/database.py](../../stock_trading_system/portfolio/database.py)：
- `CREATE TABLE` 加列：`created_by INTEGER`, `provider TEXT`, `config_hash TEXT`, `task_id TEXT`, `duration_sec REAL`, `bookmarked INTEGER DEFAULT 0`
- `_migrate_analysis_history` additions 列表追加同 6 列（idempotent ALTER TABLE ADD COLUMN）
- `save_analysis()` INSERT 列表 + VALUES 占位符各加 6 列
- `get_analysis_history(...)` 返字段不变（SELECT *）

[stock_trading_system/tasks/task_store.py](../../stock_trading_system/tasks/task_store.py)：
- `_ensure_analysis_history_table` 的 CREATE TABLE 与 PortfolioDatabase 同步（含全部新列）
- `_save_analysis_result(task_id, result)` INSERT 改写：写 model / provider / config_hash / created_by / task_id / duration_sec / bookmarked / steps_json / advice 结构化字段
- TaskManager 把 `created_by`（task.created_by）+ `provider/model/config_hash`（router 当前 active）+ `duration_sec`（completed - started）+ `task_id` 全部传给 result dict

[stock_trading_system/tasks/workers.py](../../stock_trading_system/tasks/workers.py) `make_analysis_worker`：
- worker 起点记 `t_start = time.perf_counter()`
- worker 返回 dict 加：`provider`（`router.get_active_provider()`）、`model`（`router.get_active_model()`）、`config_hash`（hash 当前 llm config block）、`duration_sec`（now - t_start）、`task_id`、`created_by`（params['__user_id__'] 由 TaskManager 注入）

[AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) `AnalysisDetailView` Header 下加 meta 行：
- `创建者: <display_name>` · `Provider: <provider>/<model>` · `耗时: <duration_sec>s` · `创建时间: <created_at>`

##### R-fix-7C · 统一分析任务入口（~1h）

[stock_trading_system/web/app.py](../../stock_trading_system/web/app.py) `/api/analyze`（line 852-947）：
- **删除** daemon thread 整段
- 改为 thin wrapper：
  ```python
  @app.route("/api/analyze", methods=["POST"])
  @login_required
  def api_analyze():
      data = request.json or {}
      task_id = task_manager.submit(
          task_type="analysis",
          params={"ticker": data["ticker"].upper(),
                  "date": data.get("date") or today_str(),
                  "depth": data.get("depth", "standard")},
          created_by=g.user.id,
      )
      return jsonify({"task_id": task_id, "status": "queued"})
  ```
- 删除 `def run_analysis():` 整个内联函数 + threading.Thread 启动
- 删除 `gemini_cfg = get_config().get("gemini", {})` 硬编码 model 读取（worker 已通过 router.get_active_model 写）

##### R-fix-7D · 拆分共享分析与个人 advice（~2h）

[stock_trading_system/portfolio/database.py](../../stock_trading_system/portfolio/database.py)：
- 新建表（迁移 idempotent）：
  ```sql
  CREATE TABLE IF NOT EXISTS user_analysis_advice (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      analysis_id INTEGER NOT NULL,
      holdings_context_snapshot TEXT,  -- JSON：当时持仓快照
      action TEXT,
      confidence TEXT,
      position_pct REAL,
      entry_low REAL,
      entry_high REAL,
      stop_loss REAL,
      take_profit REAL,
      reasoning TEXT,
      risk_warning TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(user_id, analysis_id),
      FOREIGN KEY(analysis_id) REFERENCES analysis_history(id) ON DELETE CASCADE
  );
  CREATE INDEX idx_uaa_user ON user_analysis_advice(user_id, created_at DESC);
  ```
- `analysis_history` 把 `advice_json / action / confidence / position_pct / entry_low / entry_high / stop_loss / take_profit` 标记为**已弃用**（不删，但新写不再写入；migration 把存量数据搬到 user_analysis_advice 用 created_by 当 user_id 兜底）
- 新增方法：`save_user_advice(user_id, analysis_id, advice_dict, holdings_snapshot)` / `get_user_advice(user_id, analysis_id)`

[stock_trading_system/tasks/workers.py](../../stock_trading_system/tasks/workers.py)：
- `_build_advice` 调用前 snapshot 当前用户持仓 → `holdings_snapshot_json`
- worker 返回的 dict 不再含 advice 字段（避免写入 analysis_history）
- 完成后 TaskManager 落库分两步：
  1. `task_store._save_analysis_result(...)` → analysis_id（共享研究内容）
  2. `portfolio_db.save_user_advice(user_id=created_by, analysis_id, advice_dict, holdings_snapshot)`

[stock_trading_system/web/app.py](../../stock_trading_system/web/app.py) `/api/history/<id>`：
- SELECT analysis_history → 返共享字段（不含 advice）
- LEFT JOIN user_analysis_advice WHERE user_id = g.user.id → `advice` 字段（仅当前用户的）
- 别人的 advice 永远不返

[AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)：
- "决策"tab 渲染 `detail.trade_decision`（共享）
- 新增"我的建议"tab 渲染 `detail.advice`（私有，仅 current user 有的才显示）

##### R-fix-7E · `/analysis` 产品闭环（~3h）

[AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 表单页（else 分支）：
- 表单上方加"最近分析"卡 grid（5 卡，`apiGet('/api/history?limit=5')`，整卡可点 → /analysis/<id>，显示 ticker / signal Badge / created_by display_name / created_at）
- 表单加 RadioGroup 字段「分析深度」：
  - `quick`（仅技术面+基本面，~30s，~$0.05）
  - `standard`（默认，全 7 agent，~2min，~$0.20）
  - `deep`（含辩论 + 风险 + 反思迭代，~5min，~$0.80）
- depth 写入 task params，worker 根据 depth 选择跳过或加载 agent

`AnalysisDetailView` REPORT_TABS 改为 8 项（新增"决策"独立 tab）：
```typescript
const REPORT_TABS = [
  { key: "summary", label: "概览" },
  { key: "Market", label: "市场/技术面" },
  { key: "Sentiment", label: "情绪面" },
  { key: "News", label: "新闻" },
  { key: "Fundamentals", label: "基本面" },
  { key: "Investment Debate", label: "多空辩论" },
  { key: "Risk Assessment", label: "风险评估" },
  { key: "Decision", label: "决策" },  // ← 新增独立 tab
] as const
```
"决策"tab 渲染 `detail.trade_decision`（不再混 summary）。

详情页 Header 区右侧加操作按钮组：
- `[再次分析]` → `apiPost('/api/tasks/submit', {type:'analysis', params:{ticker, date:today, depth:'standard'}})` → toast + 跳新 task
- `[加入持仓追踪]` → `apiPost('/api/portfolio/track', {ticker, analysis_id})`
- `[导出 PDF]` `[导出 Markdown]` → `apiGet('/api/history/<id>/export?format=pdf|md')` 触发下载
- `[分享链接]` → 复制 `https://<host>/analysis/<id>` 到剪贴板 + toast
- `[★ 收藏]` toggle → `apiPost('/api/history/<id>/bookmark', {bookmarked: true|false})` → analysis_history.bookmarked

后端新增 endpoints（[app.py](../../stock_trading_system/web/app.py)）：
- `GET /api/history/<id>/export?format=pdf|md`：md 直接 join reports + decision 返 `text/markdown`；pdf 用 `weasyprint` 或 `markdown-pdf`
- `POST /api/history/<id>/bookmark` body `{bookmarked: bool}`：UPDATE analysis_history.bookmarked WHERE id=? — 注意 bookmarked 是 per-user 还是 global？**实施按 per-user**：bookmark 移到 user_analysis_advice 或新增 `analysis_bookmarks(user_id, analysis_id)` 简单关联表
- `POST /api/portfolio/track` body `{ticker, analysis_id}`：写 analysis_tracked 表（已存在于 paper-trade）

##### R-fix-7F · Markdown sanitize（~30min）

[stock_trading_system/web/frontend/package.json](../../stock_trading_system/web/frontend/package.json) 加依赖：
```bash
npm install rehype-sanitize
```

[AnalysisPage.tsx](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)：
- `import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'`
- 自定义 schema 加白名单允许 `table / thead / tbody / tr / th / td / code / pre` 标签 + `class / className` 属性（GFM 表格 + Tailwind prose 样式需要）
- `<Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSanitize, schema]]}>`
- 应用到所有 8 tab 的 markdown 渲染

##### R-fix-7G · 修 `_record_agent_scores` 双重记录（~1h）

[stock_trading_system/tasks/workers.py](../../stock_trading_system/tasks/workers.py) `make_analysis_worker`：
- 当前流程（错）：
  1. analyzer.analyze() → result, final_state
  2. **`_record_agent_scores` 调 `db.save_analysis(半成品)` → analysis_id_1**
  3. AgentScorer.record_analysis(analysis_id_1, ...)
  4. worker return → TaskManager → TaskStore._save_analysis_result(完整) → analysis_id_2 ❌ 重复
- 改为：
  1. analyzer.analyze() → result, final_state
  2. **暂存 final_state 在 worker scope**（不立即 save 半成品）
  3. worker return 完整 dict（含 final_state 序列化或 ref）
  4. TaskManager → TaskStore._save_analysis_result → analysis_id（唯一）
  5. **TaskManager 在 _save_analysis_result 之后调 `_record_agent_scores(analysis_id, final_state, ...)`** —— 用真 analysis_id
- 实施：
  - `make_analysis_worker` 不再调 `_record_agent_scores`
  - 在 worker 返回 dict 加 `_final_state_ref`（写到 task_events 或临时 dict 缓存，key=task_id）
  - TaskManager 完成 `_save_analysis_result` 取到 analysis_id 后调 `_record_agent_scores(analysis_id, final_state)`
  - 或更简：worker 返回时把 final_state 也 `json.dumps` 到 result['steps_json']（已存在），_record_agent_scores 用 analysis_id 反查
- 验收：跑一次 analysis，`SELECT COUNT(*) FROM analysis_history WHERE ticker='AAPL' AND created_at > 'NOW-5min'` 应 = 1（不再 = 2）

##### 强约束

- ❌ 不许改已通过的 R-fix-1~6（净值曲线 / 持仓 PnL / SV3 / paper-trade ErrorBoundary / quote/history / scheduler）
- ❌ 不许动 [PortfolioDatabase.get_snapshots()](../../stock_trading_system/portfolio/database.py) / [PortfolioManager.get_history()](../../stock_trading_system/portfolio/manager.py)
- ❌ 不许动 [DashboardPage.tsx](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 的净值曲线 ChipRow / range switcher
- ❌ 不许在 `/api/analyze` 保留 daemon thread 走另一条路（必须只是 wrapper）
- ❌ 不许把 `bookmarked` 做成 global（必须 per-user）
- ❌ 不许吞异常 `try/except: pass`
- ✅ 允许新建：1 张表 `user_analysis_advice` + 1 张表 `analysis_bookmarks`(可选) + 6 列 ALTER TABLE
- ✅ 允许新增 endpoints：`GET /api/history/<id>/export`、`POST /api/history/<id>/bookmark`、`POST /api/portfolio/track`

**总验收（一次性跑通）**：
1. 详情页 K 线 90 天日 K 渲染（loading/empty/error 三态 overlay 显示且不吃容器）
2. 提交分析后 `SELECT created_by, provider, model, config_hash, task_id, duration_sec FROM analysis_history ORDER BY id DESC LIMIT 1` 全部非空
3. `curl /api/analyze -X POST` 返 `{task_id, status: queued}`，没起 daemon thread（grep `threading.Thread` in api_analyze 应空）
4. 用户 A 创建分析，用户 B 拉 `/api/history/<id>` → response 不含 advice / holdings_context
5. `/analysis` 首页 5 条最近卡可见可点；深度 RadioGroup 三选项；详情页 8 tab + 5 操作按钮全
6. Markdown 测 `<script>alert(1)</script>` 输入 → 渲染时被 strip
7. 跑一次完整 analysis → `SELECT COUNT(*) FROM analysis_history WHERE ticker='X' AND date='Y'` = 1（不重复）
8. `npm run build && pytest tests/web/test_analysis.py tests/portfolio/test_database.py tests/tasks/test_workers.py` 全绿
9. 之前通过的 R-fix-1~6 不能挂

---

### 6.2 R-1.x 完成后

P0 闸门全绿，可签字进入 R-6 / R-7 已完成部分的回归 + 真实数据跑一遍。最终 sign-off：

```bash
python -m stock_trading_system.validation.sign_off \
  --report validation/runs/<date>/regression-final.json \
  --signer admin@local \
  --note "P0 全 22 项 + R-1.x 收尾全绿"
```

## 7. 验证

每 Phase 结束跑：

1. **视觉对比**：在 375 / 768 / 1440 三断点 + 桌面 1920 截图，与 [old index.html](../../stock_trading_system/web/templates/index.html) 老 Jinja 截图对照清单（截图归档 `validation/regression/<page>/`）
2. **功能 checklist**：本文档每页 `[CODE-Pn-x]` 用例标号都打勾
3. **Playwright E2E**：补到 [test-cases](../test-cases/ui-react-island-regression.md)（伴生文档），覆盖 P0 8 项 CRITICAL
4. **跑一次 [validation](./ui-migration-validation.md) L0 + L4 不变量**确保数据没动到

最终全绿后才 sign-off。

## 8. 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md)：

- **L0 项目内**：[mobile-optimization](./mobile-optimization.md) 7 通用组件 + 3 断点；[ui-react-island-pages](./ui-react-island-pages.md) 已设计的 EChartsPanel；当前 React shadcn 组件库 14 个
- **L1 库**：ECharts（已装）+ react-markdown + tanstack-table 全部已装
- **L2 思路**：直接 copy 老 Jinja 的图表 ECharts 配置（option 对象可直接搬）
- **L4 自写**：估算 ~1500 LOC（图表配置 ~600 + 表单 ~400 + 共享组件 ~300 + 移动端规范化 ~200）

## 9. 风险与边界

| 风险 | 缓解 |
|---|---|
| 修复时不小心改了已工作的功能 | 每 Phase 单独 commit + diff 强约束（仅 add，不 modify 已有 React 组件 export 的 props） |
| 老 Jinja 的某些控件 API 已不存在（接口名变了） | 修复前先 grep 老 app.js 找出 `/api/*` 调用名，必要时新增后端兼容路由 |
| 7 个图表性能（dashboard 同屏多图）| ChartPanel 组件做 IntersectionObserver lazy-init，可见才 render |
| 移动端断点 sm（640）vs 设计标准 576px 不一致 | 统一改用 CSS `@media ≤575.98px` 自定义断点；Tailwind sm 仅用于桌面正向断点 |
| 老 hash 路由（`#data-page=paper`）的存量书签 | Flask 加 redirect middleware：`/?page=<x>` / `/#<x>` → 对应 React 路径 |

## 10. 与其他文档的关系

| 文档 | 关系 |
|---|---|
| [ui-react-island.md](./ui-react-island.md) | 本文档是 v1.0 + v2.0 实施后的**回归 backlog**，不取代主方案 |
| [ui-react-island-pages.md](./ui-react-island-pages.md) | pages 文档是"理想终态"，本文档是"对照实施现状的差距" |
| [mobile-optimization.md](./mobile-optimization.md) | 本文档明确 React 实施时未应用的规范，此次修复全面对齐 |
| [paper-trade.md](./paper-trade.md) | v1.3 F4 图表配置直接 copy 给 paper-trade 权益曲线 |
| [ui-migration-validation.md](./ui-migration-validation.md) | 本回归项作为 L2 功能矩阵的补充用例 |

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-25 | 初版：合并功能回归 59 项 + 移动端适配 15 项 = 74 项 backlog；按 11 页 × P0/P1/P2 拆解；R-1~R-7 七 Phase 实施计划 ~42h；横切组件升级（Stat / ChartPanel / form-row-mobile / tabs-scrollable / 表格→卡片）；明确"只补不改"约束 |
| v1.1 | 2026-04-25 | 补充：(1) 升级 paper-trade 列表页（PT-P0-2）从 P1 → P0 CRITICAL，因实测发现 `/paper-trade` 路由不存在，整个入口缺失；(2) 新增 §4.12 菜单重组方案，6 大组（概览/分析/选股/持仓/纸面交易/系统）+ 11 叶子，含 Sidebar 分组组件 + MobileTabbar 5+更多 sheet 设计；(3) 总工时 ~42h → ~49h |
| v1.2 | 2026-04-25 | 补充：升级 Tasks 4 项从 P1/P2 → P0 CRITICAL（T-P0-1~5）：(1) 历史无分页 → 无限滚动 + offset；(2) 无类型过滤 → 新增类型 chip-row（AI 分析/批量/选股 V3/回测/报告/纸面交易/其他）；(3) 无 scope 过滤 → 加 我的/全部 tab；(4) 无跳转结果落地页 → 新建 `lib/tasks.ts::getTaskResultUrl(task)` 9 类 task → URL 映射表，整卡可点 + 显式 [查看结果 →] 按钮；(5) 详情页操作齐全（删除/重试/取消/查看结果）。总工时 ~49h → ~53h；Tasks CRITICAL 0 → 5 |
| v1.3 | 2026-04-25 | 补充实测发现的 4 个新 P0：(1) PT-P0-3 paper-trade `<ticker>` 详情空白 bug（pathname.split 末尾斜杠 → 空），(2) T-P0-6 任务中心空白 bug（后端返回 `items` 字段，前端期望 `tasks`，schema 不匹配）；(3) SE-P0-1 设置页缺 GEMINI_API_KEY + QWEN_API_KEY 字段（硬编码列表遗漏）；(4) MS-P0-1~4 整个 Model-Switch UI 缺失（后端 100% 已就绪，前端 0 组件）—— 新增 §4.13 LLMSwitcher 详细规格，挂 NavTopbar 桌面 + 移动 sheet。新增 R-5b Phase（Settings keys 1h）+ R-1 包含 LLMSwitcher（新增 ~3h）；总工时 ~53h → ~57h；CRITICAL 14 → 22 |
| v1.4 | 2026-04-25 | 实施进度审计：R-1~R-7 commits 落地后实测 22 P0 中 18 项 ✅ DONE / 6 项 ❌ MISSING（MS-P0-1~4 LLMSwitcher 全套未建 + SE-P0-1 Settings 仍缺 Gemini+Qwen key + A-P0-3 Pipeline DAG 未实装）+ 1 项 ⚠ PARTIAL（T-P0-6 前端 fallback 加但后端 schema 待验证）。新增 §0 实施进度章节 + §6.1 R-1.x 收尾批次合并指令（共 ~5h，含 LLMSwitcher 3h + Settings keys 10min + Pipeline DAG 2h + Tasks schema 验证 5min）。完成 R-1.x 后 P0 才闸门绿 |
| v1.4.1 | 2026-04-25 | 修订：T-P0-6 实测确认前后端均已对齐（app.py:1713-1719 返回双字段 + TasksPage.tsx:70 fallback 已含 items），实际状态由 ⚠ PARTIAL 升级 ✅ DONE，DONE 总数 18 → 19；§6.1.4 R-3b.1 标 NO-OP，余下排查只需查 DB 数据/过滤态/scope 默认值（运行时问题，不在修复 backlog 内） |
| v1.5 | 2026-04-25 | 实测发现 R-1~R-7 还有 6 项 P0 缺失：(1) HE-P0-1 History → analysis 详情 URL 损坏（int vs string id 不匹配 → 404）；(2) SV3-P0-1 Screener V3 结果页**完全没建**（ScreenerV3Page 仅表单）；(3) A-P0-3a Pipeline DAG 位置错误（仅表单视图，详情视图无）；(4) A-P0-4 K线应用 TradingView widget 而非 ECharts；(5) A-P0-5 缺新闻+基本面 side cards；(6) B-P0-1 Backtest 结果详情页未建；(7) D-P0-5 dashboard /backtest-v2 死链。R-6 实际未做的 HIGH 项：HE-P1-1/2 对比+timeline / AL-P1-2 阈值建议 / SE-P1-1/2 调度器+数据源 / R-P2-12 导出（暂不阻塞 P0）。新增 §6.1 v1.5 收尾任务 ~7h；总剩余工作 5h → 12h |
| v1.6 | 2026-04-25 | 性能问题：实测 Dashboard / Portfolio 加载慢（~3s），根因后端 `get_pnl/get_holdings/get_allocation` 嵌套调用 → **单次访问拉 2 次全量实时价格**。新增 R-perf（PERF-P0-1，~1.5h）：Layer A request-scoped memoize（PortfolioManager.get_holdings 加 Flask g 缓存，~30min，砍半）+ Layer B 价格层 30s TTL LocalCache（~1h，复访 < 200ms）。总剩余工作 12h → 13.5h。同时 doc-first 工作流约定固化：以后所有修复必须先写 doc + changelog 再出 Code 指令 |
| v1.7 | 2026-04-25 | 实测两个 P0：(1) **PT-P0-4** Paper-trade ticker 详情完全空白（实测发现 PaperTradePage.tsx:68 `pathname.split("/").pop()` 仍是老代码，v1.3 PT-P0-3 标 DONE 是 audit 误判，需真修：用 regex 或 filter(Boolean) + 加 React ErrorBoundary 兜底）；(2) **A-P0-7** AI 分析提交后跳 `/tasks/<id>` 不是 `/analysis/<id>`（用户看不到 Pipeline DAG 实时 + 7-tab 流入），需配合 R-5.1 一起实现"提交→跳 /analysis/<task_id>→显示 DAG→完成后切 7-tab"完整流程。新增 R-3.1（30min）+ R-5.4（1h）；总剩余 13.5h → 15h |
| v1.7 | 2026-04-25 | 实测两个 P0：(1) PT-P0-4 paper-trade ticker 详情完全空白（PaperTradePage.tsx:68 pathname.split 仍老代码）；(2) A-P0-7 AI 分析提交后跳 /tasks/<id> 应跳 /analysis/<task_id> 配合 Pipeline DAG。新增 R-3.1（30min）+ R-5.4（1h）；剩余 13.5h → 15h |
| v1.8 | 2026-04-26 | 功能补强 2 项（用户实测后提的非 bug 改进）：(1) D-FEAT-1 仪表盘净值曲线自动回溯（从最早 daily_snapshot 起到今天，不再固定 30 天，加 range switcher chip 全部/1Y/6M/3M/1M/7D + dataZoom；后端 get_history(days=None) 返全量）；(2) P-FEAT-1 持仓表加"盈亏 $"绝对值列（后端 get_holdings 已计算 pnl 字段，前端补显示，dashboard 持仓概览同步加），移动端 m-card 同步加。剩余 15h → 17h | — |
| v1.9 | 2026-04-26 | 实测 A-P0-8：点[开始分析]后页面完全空白。新增完整运行中态布局（强化 v1.7 A-P0-7 + R-5.1 DAG + R-5.2 侧卡 + R-5.3 K线，合并成一个 dashboard）：Header / 主图 K 线 / Pipeline DAG / 三列侧卡（新闻+基本面+多空比） / 7-tab 占位 skeleton 逐个填充。提交后立即跳 /analysis/<task_id>，K线和新闻/基本面独立拉（< 1s 显示），DAG 订阅 task_events 实时进度，agent_stage_done 事件 → 对应 tab 填充。完成后 history.replaceState 切到 /analysis/<analysis_id>。新增 ~3h（含在 R-5.x 内）；剩余 17h → 20h | — |
| v1.10 | 2026-04-26 | 生产环境实测发现 5 项前序号称 DONE 的项实际仍未真修：(1) D-FEAT-1 净值曲线后端 `pm.get_history(days=30)` 硬编码（v1.8 后端改动漏做，前端 ChipRow 无效）；(2) P-FEAT-1 Dashboard 持仓 top3 没加绝对值列（v1.8 仅 PortfolioPage 加了，dashboard 漏）；(3) SV3-P0-1 V3 结果"加载失败"（前端用 task_id (UUID) 拉 `/api/screen/v3/results/<id>`，后端期望整数 result_id）；(4) PT-P0-4 Paper-trade ErrorBoundary 真触发（内部 PaperTradeContent 有 throw，需 null check）；(5) R-5.3 K线区域空白（TVChart 已挂但 klineData 空，需新建/修 `/api/quote/history` 端点）。新增 R-fix-1~5（~3h）；剩余 20h → 23h | — |
| v1.12 | 2026-04-30 | v1.11 修了代码但没修数据：实测 daily_snapshots 仅 3 行（2026-04-14/15/16/19），距今缺 11 天。`task_scheduler.py:105` 已写 take_snapshot 但调度器没真跑。设计原意"自动回溯"指从最早 transaction(2026-04-12) 起每个交易日都要有 snapshot。新增 R-fix-6 共 4 子项（~3h）：(a) 历史回填脚本 backfill_daily_snapshots.py（按交易日重放 transactions + yfinance 收盘价 → upsert 幂等）；(b) 修 APScheduler 启动 + cron 美东 16:30（=北京次日 04:30）+ 多用户迭代；(c) Dashboard "↻ 重新计算"按钮触发异步 backfill task；(d) Settings 页加"调度器状态"卡（运行态/上次快照/下次快照/手动触发）。验收：DB ≥ 14 行 snapshot，dashboard ALL 视图 14 连续点 | — |
| v1.13 | 2026-04-30 | AI 分析模块 7 大产品&技术缺口（用户 2026-04-30 提）：(A) `<TVChart>` 初始 `loading + data=[]` 早 return Skeleton 导致 chart 容器永不挂载，改为始终渲染容器 + overlay 三态（loading/empty/error）+ onRetry，详情页 K 线主路径 `/api/quote/history?days=90`、回退 `/api/chart/<ticker>?period=3mo`；(B) `analysis_history` schema 加 `created_by/provider/config_hash/task_id/duration_sec/bookmarked` 6 列 + idempotent ALTER TABLE，TaskStore `_save_analysis_result` INSERT 同步写，worker 注入 `provider/model/config_hash/duration_sec/created_by/task_id`；(C) 废 `/api/analyze` daemon thread + 直写 history + 硬编码 `gemini.deep_think_model`，改为 thin wrapper 转 TaskManager；(D) 新建 `user_analysis_advice` 私有表（user_id+analysis_id+持仓 snapshot+action+entry/stop/take），`analysis_history` 仅共享研究，`/api/history/<id>` LEFT JOIN advice WHERE user_id=current；(E) `/analysis` 首页 5 条最近卡 + 深度 RadioGroup（quick/standard/deep）+ 详情 8 tab（决策独立）+ 操作按钮 5 个（再次/追踪/导出 PDF/MD/分享/收藏 per-user）；(F) `react-markdown` 加 `rehype-sanitize` + 白名单 schema（table/code/pre）防 LLM 注入；(G) 修 `_record_agent_scores` 半成品 + 完整两次 INSERT 的双重记录（改为 TaskManager 落库后用真 analysis_id 调 scorer.record_analysis）。新增 R-fix-7A~G 共 ~10h；剩余 ~13h | — |
