# PRD: 移动端信息架构与 UI 实装 v1.3.1（增量补丁）

| 项 | 值 |
|---|---|
| Feature | `mobile-ui-v1.3.1` |
| 版本 | v1.3.1（v1.3 视觉级要求增量） |
| 日期 | 2026-05-10 |
| 父 PRD | [mobile-ui-v1.3.md](mobile-ui-v1.3.md) |
| 关联 demo | [`demo_mobile_full_v1.html`](../../demo_mobile_full_v1.html) |
| Demo 截图 | 用户 2026-05-10 实测对比截图 |
| 范围 | 仅前端视觉级补丁（顶栏 / 账户卡 hero / mini-chart 内嵌） |
| 硬约束 | 不改产品功能、不改后端、不动 R-MUI-01..18 已落地能力 |

---

## 1. 背景

v1.3 实装方按 PRD §3.1 严格执行，R-MUI-01..14 功能层面 100% 通过。但 2026-05-10 用户实测对比 demo 与实装发现 **3 处视觉级落差**：

1. **移动端无顶部品牌栏 + LLMSwitcher 不可见** —— 桌面 `Sidebar` 顶部有 LLMSwitcher，移动端 `AppShell` 仅渲染 `<Sidebar>`(hidden md:flex) + `<MobileTabbar>` + `<main>`，**没有移动端顶栏**。结果是用户在移动端**完全没有切换 LLM 模型的入口**，与 PRD §9.1 验收条款"现有模型切换两段式 UI 可用"冲突。
2. **账户卡缺 hero 内嵌 mini-chart** —— demo 账户卡作为 hero 卡内嵌迷你净值曲线（[`demo_mobile_full_v1.html`](../../demo_mobile_full_v1.html) `data-view="dashboard"` 顶部），实装把净值曲线推到下方 `lg:grid-cols-3` 桌面网格，移动端首屏看不到趋势。
3. **账户卡视觉权重不足** —— 实装用普通 `<Card>` 容器，与下方持仓卡视觉权重相同；demo 是深色 hero 卡，明显高于持仓。

**根因**：v1.3 PRD §3.1 仅描述功能性能力（"首页顶部保留账户总览：账户总值、今日 PnL……"），未约束视觉层级和容器 hero 化，也未显式要求"保留顶部品牌栏 + 移动端 LLMSwitcher 入口"。本期增量补 3 条视觉级 R-MUI-19/20/21，使 PRD §9.1 / §9.2 验收能真实关闭。

## 2. 目标

1. 移动端必须能切换 LLM provider / preset（与桌面行为等价），不依赖跳设置页。
2. 移动端首页首屏可见净值趋势，无需滚动到第二屏。
3. 账户卡作为首页 hero 视觉中心，权重高于持仓卡。

### 2.1 成功指标

| 指标 | 目标 |
|---|---|
| 移动端 LLMSwitcher 可见且可点 | 任意页面顶部右侧均可一键切换 |
| 首屏（375px viewport）可见区 | 含账户总值 + 今日 PnL + mini sparkline + 三栏 metric |
| 账户卡视觉层级 | 高于持仓卡（背景深度 / 圆角 / 内边距三选其一）|
| PRD §9.1 验收 | 移动端 + 桌面端 LLMSwitcher 均可用 |

## 3. 范围

### 3.1 In Scope

**移动端顶栏（R-MUI-19）**

- 新增 `<MobileTopbar>` sticky 顶部组件（仅移动端，`md:hidden`）。
- 顶栏左侧：品牌名 `StockAI Terminal` + 当前页副标（如"首页 · 资产与持仓"/"分析 · Inbox 与命令"）。
- 顶栏右侧：复用现有 [`<LLMSwitcher>`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) 组件（已实装两段式）。
- 副标来源：每个 island 通过 prop 传给 `<AppShell pageTitle="...">`，或用 `usePageTitle()` context。
- 顶栏 backdrop blur，z-index 高于内容低于全屏 modal。

**账户卡 hero 化（R-MUI-20）**

- `<AccountOverviewCard>` 一卡内自上而下三段：
  1. 第 1 段：账户总值（左大字）+ 今日 PnL（右上 inline）—— 与现状一致。
  2. **新增第 2 段**：mini sparkline 净值曲线（90D 压缩，无坐标轴 / 无 tooltip / 仅趋势线）。
  3. 第 3 段：三栏 metric `总盈亏 / 收益率 / 活跃预警` —— 与现状一致。
- mini-chart 数据来源：复用现有 [`/api/portfolio/equity-history`](../../stock_trading_system/web/app.py)（DashboardPage 已在调用，无需新接口）。
- 数据不足（≤1 个快照）时 mini-chart 隐藏，账户卡退化为现状两段；不显示空状态占位。
- 桌面端 `lg:grid-cols-3` 的独立净值曲线 Card **保留**（提供完整 range chips + 重新计算 + 仓位分布对照），不删除。

**账户卡 hero 视觉容器（R-MUI-21）**

- 账户卡使用 hero variant：背景比常规 Card 深一档（如 `bg-card/95 ring-1 ring-primary/10`），圆角 12px，内边距 16-20px。
- 不使用第二种 Card 组件，仅在现有 `<Card>` 上加 `className` 区分。
- 与下方持仓卡 / gap-note 卡视觉权重明显不同（一眼能看出 hero）。

### 3.2 Out of Scope

| 不做 | 原因 |
|---|---|
| 改 `<LLMSwitcher>` 组件本身 | 已实装两段式，移动端只是把它放到顶栏即可 |
| 把桌面 `Sidebar` 顶部 LLMSwitcher 移到顶栏 | 桌面侧栏视觉不动，仅移动端新增 |
| 新增 `equity-history` API 或字段 | 复用现有数据源 |
| 移动端 mini-chart 加 tooltip / 缩放 | 仅展示趋势，详细交互在桌面 grid Card |
| 改其他页面（分析/发现/纸面/更多）顶栏外的视觉 | v1.3 已落地，本期不重做 |
| 改桌面端账户卡布局 | 桌面 `lg:grid-cols-3` 独立净值曲线已是 hero 体验，不动 |

## 4. 需求矩阵

### 4.1 P0 必须完成

| ID | 需求 | 目标文件 | 验收 |
|---|---|---|---|
| R-MUI-19 | `<MobileTopbar>` sticky 顶栏 + 品牌 + 页副标 + LLMSwitcher | `components/shared/MobileTopbar.tsx`（新建）+ `AppShell.tsx` 集成 | 移动端任意页面顶部可见品牌 + 副标 + 模型 chip，点 chip 触发切换菜单 |
| R-MUI-19a | 页面副标传递机制 | 各 island main entry / `AppShell` props | 5 个一级页面 + 子页面均能定制副标 |
| R-MUI-20 | 账户卡内嵌 mini sparkline | `DashboardPage.tsx` `<AccountOverviewCard>` | 375px viewport 首屏可见 sparkline |
| R-MUI-20a | mini-chart 数据不足降级 | 同上 | ≤1 个快照时 sparkline 不渲染，卡退化两段不破布局 |
| R-MUI-21 | 账户卡 hero 视觉容器 | `<AccountOverviewCard>` className | 视觉与下方持仓卡明显不同（背景 / 圆角 / 内边距任一维度）|

### 4.2 P0 布局顺序（用户 2026-05-11 二次反馈）

实测当前 [`AnalysisPage.tsx:486+`](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 是 `分析记录 Inbox` 在上 / `发起分析` 在下；[`ScreenerV3Page.tsx:69-73`](../../stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx) `<ScreenerHomeView>` 是 `<RecentScreensCard>` 在上 / `<ScreenerForm>` 在下。两处都与 demo 「主要功能在上、历史记录在下」相反。

| ID | 需求 | 目标文件 | 验收 |
|---|---|---|---|
| R-MUI-22 | AI 分析页：`发起分析` 表单卡置顶，`分析记录 Inbox` 移到下方 | `AnalysisPage.tsx` `<AnalysisHomeInbox>` | 移动端首屏首先看到表单，下方是 Inbox 列表 |
| R-MUI-23 | 智能选股 V3 页：`<ScreenerForm>` 置顶，`<RecentScreensCard>` 移到下方 | `ScreenerV3Page.tsx` `<ScreenerHomeView>` | 移动端首屏首先看到选股表单，下方是最近选股 |
| R-MUI-22a | 不改变 Inbox / RecentScreensCard 内部行为 | 同上 | 提交、刷新、点击行为完全一致 |
| R-MUI-22b | 桌面端布局同步调整（不再保留旧顺序） | 同上 | 桌面 ≥md 与移动端同序 |

### 4.3 P0 角色与隐私（用户 2026-05-15 三次反馈）

实测当前 Sidebar 把 `/settings`（含 LLM API key / OpenRouter preset / 通知 / 调度器 / 邀请码生成 / 数据库路径等管理面板）暴露给**所有登录用户**，普通租户不应看到这些；同时 MOBILE_MORE 第 7 项 "账号" 实际跳转到 `/settings#account` —— 用户**没有独立的账号页面**，导致"账号 = 设置页的一个 hash anchor"心智不一致。

| ID | 需求 | 目标文件 | 验收 |
|---|---|---|---|
| R-MUI-26 | 桌面 `<Sidebar>` NAV_GROUPS 的 "设置" 项 **仅 admin 可见** | `Sidebar.tsx` | 非 admin 登录后桌面侧栏不显示设置链接 |
| R-MUI-27 | 移动端 MOBILE_MORE 的 "系统设置" 项 **仅 admin 可见** | `Sidebar.tsx` | 非 admin 移动端 More sheet 不显示系统设置项 |
| R-MUI-28 | 移动端 MOBILE_MORE 的 "账号" 项跳转到新独立 `/account` 路由，不再 `/settings#account` | `Sidebar.tsx` + 新 island | 点击账号项进入 `/account` 而不是 `/settings` |
| R-MUI-29 | 新建 `/account` 页面 = 显示用户信息（display_name / email / 角色 badge）+ **退出登录按钮**，**无其它功能链接** | `islands/account/AccountPage.tsx` + 新 Flask 路由 | 页面只渲染一张卡含 3 行信息 + 1 个红色 logout 按钮 |
| R-MUI-30 | `/settings` 路由后端 **non-admin 返回 403**（不仅靠前端隐藏入口） | `web/app.py` `/settings` view | curl `-b alice_session` 访问 `/settings` 返 403 / redirect 到 `/account` |
| R-MUI-31 | OAuth 已绑定登录方式（LoginMethodsSection）依然展示在 `/account` 还是 `/settings`？ | — | **保持现状（在 /settings 内的"登录方式"section）** —— OAuth 绑定属于"系统配置"语义，与 admin 设置项放一处合理；用户重读时若有不同意见再 v1.3.3 调整 |

### 4.4 P1 可并行

| ID | 需求 | 验收 |
|---|---|---|
| R-MUI-24 | 顶栏副标随页面切换实时更新 | 5 个一级页面切换时副标文案与 demo 一致 |
| R-MUI-25 | 顶栏在长文页面 sticky 滚动不遮挡内容 | 滚动测试 |

## 5. 用户故事与验收

### US-MUI-6：移动端用户能切换 LLM 模型

> 作为移动端用户，我希望在任意页面顶部都能切换 LLM 模型，而不是被迫跳到设置页。

**验收**：
- 任意一级页面顶部右侧可见 `Gemini ▼` / `OpenRouter ▼` / `Qwen ▼` 之一的 chip。
- 点击 chip 弹出 LLMSwitcher 两段式（provider + role preset）。
- 切换后 toast 提示"已切换…新任务生效"。

### US-MUI-7：移动端首页首屏可见趋势

> 作为移动端用户，我打开首页就能看到账户净值的近期趋势，无需滚动。

**验收**：
- 375px viewport 下首屏（无滚动）可见：账户总值 + 今日 PnL + sparkline + 三栏 metric。
- sparkline 占账户卡内宽度 100%，高度 ~48px。
- 账户卡视觉作为 hero，与持仓卡 / gap-note 卡明显不同。

### US-MUI-9：分析页主要功能优先（form 在上、Inbox 在下）

> 作为移动端用户，我希望打开 AI 分析页第一眼看到"发起分析"表单（高频写动作），而不是先看一长串历史记录。

**验收**：
- `/analysis` 顶部第一个业务区是 `发起分析` 表单卡（含 ticker 输入 + 深度 Switch）。
- 表单卡下方才是 `分析记录 Inbox`（含运行中 + 已完成）。
- 桌面端 ≥md 同序。

### US-MUI-10：选股页主要功能优先（form 在上、最近选股在下）

> 作为移动端用户，我希望打开发现页第一眼看到"开始选股"表单，而不是先翻最近选股历史。

**验收**：
- `/screener-v3` 顶部第一个业务区是 `<ScreenerForm>`（自然语言输入 + 大师选择 + 模式 + 成本估算）。
- 表单下方才是 `<RecentScreensCard>` 最近选股 3 卡 + 查看全部链接。
- 桌面端 ≥md 同序。
- prefill 模式（`?prefill=<task_id>`）形态不变，只是 banner 提示位置随 form 上移。

### US-MUI-8：数据不足时账户卡不破布局

> 作为新用户（首日 DB 仅 1 条快照），我希望账户卡不展示空白 sparkline 或异常占位。

**验收**：
- 快照 ≤ 1 时 sparkline 不渲染，账户卡退化为账户总值 + 三栏 metric 两段。
- 今日 PnL 仍显示 "—"（[v1.3 已实装的 fallback](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx)）。

## 6. 实装约束

1. 不改 [`<LLMSwitcher>`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) 组件实现，仅消费。
2. 不新增后端 API / DB / task type。
3. 不改桌面端 `<Sidebar>` 视觉。
4. 不改桌面端 `lg:grid-cols-3` 的独立净值曲线 Card。
5. 不引入新图表库；mini-chart 复用 [`<ChartPanel>`](../../stock_trading_system/web/frontend/src/components/shared/ChartPanel.tsx) 或用纯 SVG sparkline（择优）。
6. 顶栏在 `md:hidden` 显示，桌面端 0 视觉变化。
7. 副标传递机制必须可扩展到所有现有 island，不能写死 5 个 hardcoded 文案。
8. 不动 v1.3 已落地的 R-MUI-01..18 所有改动。

## 7. 验收清单

### 7.1 功能

- 移动端 5 个一级 tab 顶部均能看到品牌 + 副标 + LLMSwitcher chip。
- 点 chip 弹两段式切换菜单可用。
- 切 provider / preset 后 toast 与桌面行为一致。
- 移动端任意页面切换或刷新后 LLMSwitcher 状态持久（与桌面同步）。

### 7.2 视觉

- 375 / 390 / 430 / 768px viewport 顶栏宽度自适应，品牌名不被压扁。
- 副标超长时 truncate 不破布局。
- 账户卡在 375px 首屏完整可见（账户总值 + 今日 PnL + sparkline + 三栏 metric）。
- 账户卡视觉权重高于持仓卡（一眼可分辨 hero）。
- 桌面端无视觉变化。

### 7.3 数据状态

- 快照 ≤ 1 时 sparkline 不渲染，不留空白容器。
- 今日 PnL 仍正确显示 "—" 兜底。
- equity-history API 失败时 sparkline 不渲染，不抛 ErrorBoundary。

## 8. 风险与处理

| 风险 | 影响 | 处理 |
|---|---|---|
| 顶栏 + 底部 tabbar 双 fixed 挤压可视区 | 内容被遮挡 | `AppShell <main>` 加 `pt-14`（顶栏高度）+ 现有 `pb-16`（tabbar）|
| LLMSwitcher 在顶栏窄屏溢出 | 视觉破 | LLMSwitcher 用 chip 形态 + 文字 truncate；副标在 chip 拥挤时自动隐藏 |
| sparkline 在数据稀疏时拉伸怪异 | 视觉差 | 数据点 < 5 时不渲染（即使快照 ≥ 2）|
| 顶栏 backdrop blur 性能 | 老移动设备卡 | 仅在滚动时启用，或退化为半透明实色 |
| 副标传递机制选错（context vs prop）影响后续维护 | 重构成本 | 选 prop（每 island 显式传），简单可追踪；context 仅当 5+ 层嵌套时再考虑 |

## 9. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.3.1 | 2026-05-10 | v1.3 视觉级增量：补 R-MUI-19/20/21 三条（移动端顶栏 + LLMSwitcher / 账户卡 mini-chart 内嵌 / 账户卡 hero 容器），关闭 v1.3 §9.1 / §9.2 验收漏洞。约 4h 实装，纯前端 |
