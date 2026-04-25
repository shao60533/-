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
| **Paper-trade** | **1** 🚨 权益曲线图缺失 | 2 日度 tab + ticker grid | 3 | 0 | LOW |
| Settings | 0 | 2 调度器 + 数据源卡 | 1 | 0 | MEDIUM provider grid 窄 |
| Tasks | 0 | 1 modal→页面 | 2 | 0 | LOW |
| **总计** | **8** | **20** | **23** | **1** | 6 项移动端独立问题 |

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
| **P0 紧急修复** | 8 CRITICAL + Dashboard stat 移动端溢出 | 上线前必完 | ~12h |
| **P1 高优先恢复** | 20 HIGH + 移动端 form/grid 标准化（6 处） | 第 1 周内 | ~16h |
| **P2 完善** | 23 MEDIUM + 1 LOW + 测试覆盖 | 第 2-3 周 | ~14h |

总修复工时 ~42h。

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

### 4.9 Paper-trade 🚨

**P0**：
- [PT-P0-1] 🚨 **权益曲线图（盈利趋势 chart-ptv-equity）完全缺失** → 补"日度数据"tab 内的 ECharts area chart，对应 v1.3 F4 已设计的双 grid + drawdown markArea 配置（见 [paper-trade.md §27.2 F4](./paper-trade.md)）

**P1**：
- [PT-P1-1] 日度数据 tab 整个缺失 → 补 stat cards + 权益图 + 日度明细表（9 列）
- [PT-P1-2] Ticker Grid（所有 session 列表）缺失（如果用户访问 `/paper-trade` 没参数时应该显示列表）

**P2**：
- 日度指标卡数字
- 日度明细表移动端卡片视图

### 4.10 Settings

**P1**：
- [SE-P1-1] 定时调度器卡完全缺失 → 补 `<SchedulerStatusCard />`（启动 / 停止 / 刷新 + 状态 + 任务列表）
- [SE-P1-2] 数据源状态卡缺失 → 补 `<DataSourceStatusCard />`

**P2**：
- 通用配置编辑器：列举原 settings-config 区域的所有字段并恢复（需 grep `/api/settings` 响应结构对照）
- footer 敏感字段说明
- 移动端 provider grid 单列塌陷

### 4.11 Tasks

**P1**：
- [T-P1-1] 任务详情 modal 改为独立页面跳转 → 评估是否回退为 modal（更顺滑），或保留页面+加返回按钮 + 历史记录
- [T-P1-2] 列表分页 `loadMoreTasks` 缺失 → 补无限滚动或加载更多按钮
- [T-P1-3] 详情页操作按钮缺失：删除 / 重试 / 取消 / 查看结果 → 全部补回

**P2**：
- 跨页面导航兼容：`/#paper` 老书签 redirect 到 `/paper-trade`

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
| **R-1** | 共享：升级 Stat 组件应用 `--fs-stat` clamp + 新建 ChartPanel 组件 + form-row-mobile 工具类 | 3h |
| **R-2** | Portfolio CRITICAL：卖出表单 + 修正成本 modal | 2h |
| **R-3** | Paper-trade CRITICAL：权益曲线 + 日度 tab | 3h |
| **R-4** | Dashboard CRITICAL：净值图 + 分布饼图 + 移动塌陷 | 2h |
| **R-5** | Analysis CRITICAL：K 线 + 7-tab 报告 + Pipeline DAG | 5h |
| **R-6** | HIGH 批次（约 20 项）：history 对比 / portfolio 交易表 / alerts 模板 / backtest 结果 / settings 调度器+数据源 | 16h |
| **R-7** | MEDIUM + 移动端兜底：所有页 grid `≤575.98px` 单列规范化 + form-row-mobile 套接 + tabs-scrollable + 表格卡片降级 | 11h |

P0 = R-1 ~ R-5（共 ~15h），P1 = R-6（~16h），P2 = R-7（~11h）。

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
