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
