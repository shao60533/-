# PRD: 新手引导（Onboarding）v1.0

| 项 | 值 |
|---|---|
| Feature | `onboarding` |
| 版本 | v1.0 |
| 日期 | 2026-05-15 |
| Demo 契约 | [`demo_onboarding_v1.html`](../../demo_onboarding_v1.html) |
| 关联设计 | [../design/onboarding.md](../design/onboarding.md) |
| 范围 | 注册后自动触发的新手引导（仅移动端） |
| 硬约束 | 不强制走完、不阻挡任何主流程、不引入 SaaS 锁定、不动多租户红线 |

---

## 1. 背景

[OAuth quick-signin v1.0](./oauth-quick-signin.md) 落地后，新用户从注册到首页的摩擦已大幅降低，但**注册成功后**用户面对的是空白账户 + 14 大师 + 8 tab 结构化分析 + 纸面交易 + 智能选股等高复杂功能集，**没有任何引导**。当前流程下用户首日的常见行为是：

1. 注册 → 首页 → 看到空持仓不知下一步
2. 点 LLM 切换器但不理解 deep / quick / preset
3. 尝试发起分析 → 等 5 分钟但不懂 8 tab 看哪个
4. 离开

竞品和 SaaS 主流做法（Notion / Linear / Stripe / Cursor / Cal.com）均提供「欢迎 modal + 常驻 checklist + 空状态 CTA + 关键点 inline hint」组合引导。本期实装该组合 v1.0，**仅覆盖移动端**（用户 2026-05-15 决策不做桌面变体）。

## 2. 目标

1. 注册后首次进首页**自动触发**欢迎 modal（不阻挡可跳）。
2. 提供常驻 4 项 Checklist（持仓 / AI 分析 / 选股 / 纸面），与底部 5 tab 前 4 个一一对应，任务完成度持续可见。
3. 用 Driver.js 6 步 Tour 介绍核心区块（顶栏 / Hero / 持仓 / 批量分析 / 底部 tab / Checklist）。
4. 空状态卡片用 CTA 形态引导首次操作（持仓为空显「+ 添加第一只持仓」）。
5. LLMSwitcher 首次点击给一次性 inline hint 解释模型切换。
6. 100% 完成或用户主动关闭后**永久静默**，仅设置页可重开。
7. 不阻塞任何已落地功能，所有引导组件**条件渲染**：未登录 / 已完成 / 已关闭则不渲染。

### 2.1 成功指标

| 指标 | 目标 |
|---|---|
| 注册后欢迎 modal 触达率 | 100%（新用户首次进首页必弹） |
| 4 项任务平均完成率 | ≥ 60%（行业主流 50-70%） |
| 引导不破坏现有 P0 流程 | Playwright 现有 48 case 不退化 |
| 桌面端视觉变化 | 0（仅移动端注入） |
| 引导关闭后再触发路径 | 设置页 [重新观看引导] 1 步可达 |
| 新增依赖 | 1 个（driver.js ~5KB gzipped） |

## 3. 范围

### 3.1 In Scope

**触发与状态**

- 注册成功后 `user_onboarding.welcome_pending = true` 标记。
- 用户首次进首页（任何 route）→ 若 `welcome_pending && !welcomed` 弹欢迎 modal。
- 用户在 modal 点 "开始导览" → 启动 Driver.js 6 步 Tour → 完成或关闭后 `tour_completed = true`。
- 用户在 modal 点 "稍后再说" → `welcomed = true`，跳过 Tour，直接显示 Checklist。
- 任意时刻可点 Checklist 右上 `×` → `checklist_dismissed = true`，永久静默。
- 设置页加 `[重新观看引导]` → 调 `/api/onboarding/reset` 清所有 flag。

**Checklist 4 任务**

| 任务 ID | 标签 | 触发完成条件（后端自动） |
|---|---|---|
| `add-holding` | 添加第一只持仓 | `POST /api/portfolio/buy` 成功 |
| `first-analysis` | 完成第一次 AI 分析 | `analysis_history` 新行写入且 `created_by = user_id` |
| `first-screen` | 完成第一次智能选股 | `tasks` 表 `type=screen_v3` 且 `status=success` 的行首次出现 |
| `first-paper-plan` | 创建第一笔纸面交易计划 | `paper_trade_plans` 新行写入且关联到 user |

**Driver.js Tour 6 步**

| # | 锚点 | 标题 | 描述 |
|---|---|---|---|
| 1 | `#topbar` | 顶栏 · 品牌与模型切换 | 蓝色 chip 切换 AI 模型（OpenRouter / Qwen / Gemini）+ deep/quick 双挡 |
| 2 | `#account-hero` | 账户 Hero · 总览与趋势 | 账户总值 + 今日 PnL + 90D sparkline + 三栏 metric |
| 3 | `#holdings-section` | 持仓明细 · 决策中枢 | 搜索 / 买入 / 5 ↔ 全部 / 每只卡看分析/卖出/修正成本/移除 |
| 4 | `#batch-analyze-card` | 批量分析持仓 | 一键复核所有持仓，跳过 4h 内已分析，逐只顺序执行 |
| 5 | `[data-mobile-tabbar]` | 底部导航 · 5 个一级入口 | 首页 / 分析 / 发现 / 纸面 / 更多 |
| 6 | `#onboarding-checklist` | 4 项上手任务 | 完成 4 项即解锁全部核心功能，可随时折叠 |

**空状态 CTA（4 处）**

| 位置 | 空态文案 | CTA |
|---|---|---|
| 首页持仓为空 | 暂无持仓 — 添加第一只即可开始追踪 | `+ 添加第一只持仓` → 弹买入 dialog |
| 分析 Inbox 为空 | 暂无分析记录，下方提交一个开始 | `↓ 发起第一次分析`（指向 form 锚点） |
| 选股最近为空 | 暂无选股历史，下方表单提交即可 | `↓ 开始第一次选股` |
| 纸面列表为空 | 暂无纸面追踪，从分析详情或选股结果发起 | `→ 看 AI 分析` 跳 `/analysis` |

**LLMSwitcher Inline Hint**

- 首次点 LLMSwitcher chip 后弹一次性 tooltip 解释「这里切换 deep/quick 模型」。
- 关闭后 `localStorage.onboarding_hint_llm_dismissed = true`，不再显示。
- 不依赖后端状态（移动端 hint 不需要跨设备同步）。

**设置页入口**

- 设置页加新 section "新手引导" → `[重新观看引导]` 按钮 → 调 `/api/onboarding/reset` → toast → 提示用户回首页查看。

### 3.2 Out of Scope

| 不做 | 原因 |
|---|---|
| 桌面端引导 | 用户 2026-05-15 决策仅移动端 |
| 角色选择（Student/Investor/...） | 复杂度高，统一一套引导 v1.0 够用 |
| A/B 测试不同引导变体 | 数据量太小不值得 |
| 引导完成度统计/分析后台 | 等数据积累后 v1.1 评估 |
| Push 通知召回未完成用户 | 与 onboarding 正交，单独 PRD |
| 视频/动画引导 | 增加首屏加载，不必要 |
| 第三方 SaaS 平台（Userpilot / Pendo / Appcues） | 月费 + GFW 风险 + 数据出境 |
| 跨 device 同步 inline hint dismiss 状态 | 移动端 localStorage 足够 |
| 修改 OAuth / 邀请码 / 多租户逻辑 | 严格红线，[multi-tenant.md](multi-tenant.md) 不动 |

## 4. 需求矩阵

### 4.1 P0 必须完成

| ID | 需求 | 目标文件 | 验收 |
|---|---|---|---|
| R-OB-01 | `user_onboarding` 表（idempotent migration） | `migrations/add_user_onboarding.py` | `pytest tests/auth/test_onboarding_repository.py` 全绿 |
| R-OB-02 | `OnboardingRepository`（CRUD + 多租户隔离） | `auth/onboarding_repository.py`, tests | 6 单测覆盖 get/init/mark_step/reset/list_completed/cross-user |
| R-OB-03 | `POST /api/onboarding/state` GET + `POST /api/onboarding/complete-step` + `POST /api/onboarding/reset` | `web/app.py`, tests | 4 端点 + 多租户隔离 + 401 未登录 |
| R-OB-04 | 注册成功后写 `welcome_pending=true` | `web/app.py` register handler | 单测：alice 注册后 `/api/onboarding/state` 返回 `welcome_pending: true` |
| R-OB-05 | 4 项任务自动完成钩子（在已有 4 个 handler 内调 `_mark_onboarding_step`） | `web/app.py` 持仓/分析/选股/纸面 handler | 单测：4 个动作各自触发对应步骤标记 |
| R-OB-06 | `<WelcomeModal>` 注册后自动弹 + Tour/Skip 双按钮 + 风险提示 | `components/shared/onboarding/WelcomeModal.tsx` | 视觉对齐 demo，移动端 320-430px 不溢出 |
| R-OB-07 | `<OnboardingChecklist>` 常驻底部悬浮卡 + 4 任务进度 + 折叠 × | `components/shared/onboarding/OnboardingChecklist.tsx` | 视觉对齐 demo，100% 自动隐藏 + 庆祝 toast |
| R-OB-08 | `useOnboardingTour` hook + Driver.js 6 步集成 | `hooks/useOnboardingTour.ts` | Tour 6 步顺序执行、关闭后写 `tour_completed=true` |
| R-OB-09 | Driver.js CSS dark 主题覆写 | `styles/onboarding.css` | popover 与现有 shadcn dark 主题一致 |
| R-OB-10 | 4 处空状态 CTA 锚点 + 文案 | Dashboard / Analysis / Screener / Paper list pages | 数据为空时显示，有数据时隐藏 |
| R-OB-11 | LLMSwitcher 首次点击 inline hint | `components/shared/LLMSwitcher.tsx` | localStorage 控制，关闭后永久静默 |
| R-OB-12 | 设置页 "新手引导" section + 重新观看按钮 | `islands/settings/SettingsPage.tsx` | 点击 → POST reset → toast + Checklist 重显 |
| R-OB-13 | 6 锚点 ID 注入既有页面（`#topbar` / `#account-hero` / `#holdings-section` / `#batch-analyze-card` / `[data-mobile-tabbar]` / `#onboarding-checklist`） | MobileTopbar / AccountOverviewCard / HoldingsSection / Sidebar | 锚点存在且 Driver.js 能定位 |
| R-OB-14 | 桌面端 `md:hidden` 隔离 | 所有 onboarding 组件 | 桌面 ≥md 引导组件 0 渲染、0 视觉变化 |

### 4.2 P1 可并行

| ID | 需求 | 验收 |
|---|---|---|
| R-OB-15 | Tour 跳过追踪（计入 state） | `tour_skipped_at_step` 字段记录跳出位置 |
| R-OB-16 | Checklist 一项任务跳转后是否回到 dashboard | 完成后路由回 / 是否合适，看用户体验决定 |
| R-OB-17 | `/api/onboarding/state` 缓存策略（避免每次 page load 都 fetch） | SWR / 5min stale-while-revalidate |

## 5. 用户故事与验收

### US-OB-1：新用户注册后 30 秒了解能力

> 作为刚通过邀请码注册的新用户，我希望首次进首页就能 30 秒了解 StockAI 能干什么，而不是面对空白账户不知所措。

**验收**：
- 注册成功并自动登录后 → 跳首页 → 自动弹欢迎 modal。
- modal 含 3 大能力介绍（AI 分析 / 智能选股 / 纸面交易）+ 风险提示 + 双 CTA。
- 跳过 → 不再自动弹（除非 reset）。
- 风险提示位于 modal 底部黄底小字"输出非投资建议、纸面交易不触发真实下单"。

### US-OB-2：通过 Tour 认识核心区块

> 作为想快速上手的用户，我希望 1 分钟内被引导走完核心功能位置。

**验收**：
- modal 点"开始导览" → Driver.js 启动 6 步。
- 每步聚焦目标元素 + 蓝边 popover + "下一步 →" / "← 上一步" / "完成 ✓" 按钮。
- 任意步可点 × 退出。
- 完成或退出后 Checklist 自动显示。

### US-OB-3：常驻 Checklist 看进度

> 作为完成欢迎引导但还没完全上手的用户，我希望首页有个 4 项任务的进度卡。

**验收**：
- Checklist 浮于底部 tabbar 上方（z-index 6，不挡主内容）。
- 每项点击 → 跳对应页面 + 用户实际完成动作后**后端自动**标记任务。
- 进度条平滑过渡。
- 100% 完成 → 600ms 后自动隐藏 + 顶部 toast "🎉 全部任务完成"。
- 右上 × 可主动关闭，永久静默直至 settings reset。

### US-OB-4：4 个空状态引导首次操作

> 作为新用户访问任何空列表，我希望立即看到下一步该做什么。

**验收**：
- 持仓为空 → 大号 "+ 添加第一只持仓" CTA。
- 分析 Inbox 为空 → "↓ 发起第一次分析" 文案 + 箭头指向 form。
- 选股最近为空 → "↓ 开始第一次选股"。
- 纸面列表为空 → "→ 看 AI 分析" 跳 `/analysis`。
- 有数据时空状态自动消失，不干扰常规使用。

### US-OB-5：LLM 切换器首次点击解释

> 作为不懂 LLM provider 概念的用户，我希望首次点切换器时有简单解释。

**验收**：
- 首次点 LLMSwitcher chip → 弹一次性 tooltip "这里切换 AI 模型（OpenRouter / Qwen / Gemini）"。
- 关闭后 localStorage 标记，不再显示。
- 不影响 LLMSwitcher 本身功能（仍正常弹两段式菜单）。

### US-OB-6：设置页可重开引导

> 作为已完成或已关闭引导的用户，我希望能在设置里重新打开它。

**验收**：
- `/settings` 加 "新手引导" section + `[重新观看引导]` 按钮。
- 点击 → POST `/api/onboarding/reset` → toast "已重置" → 引导用户回首页查看。
- 回首页后 welcome modal 重新弹出。

## 6. 实装约束

1. 不修改 `users` 表 schema。
2. 不引入第三方 SaaS 引导平台（Userpilot / Pendo / Appcues 均不引入）。
3. 不修改 OAuth / 邀请码 / 多租户隔离逻辑。
4. 4 项任务完成钩子**复用现有 API 路径**，不新建独立 task type 或 worker。
5. Driver.js 必须从 npm 装本地依赖（不走 CDN）以保证国内访问与离线开发。
6. 所有 onboarding 组件 `md:hidden` 隔离桌面端，桌面用户 0 视觉变化。
7. 移动端首屏新增 ≤ 8KB JS（driver.js gzipped ~5KB + 组件 ~3KB）。
8. 状态来源单一：后端 `user_onboarding` 表（除 LLM hint 用 localStorage）。
9. 不动 v1.3.1 已落地的 R-MUI-19/20/21/22/23 / batch_analyze 等组件实现，仅添加锚点 ID。
10. 风险提示文案"输出非投资建议、纸面交易不触发真实下单"必须保留（合规要求）。

## 7. 验收清单

### 7.1 功能

- 注册后欢迎 modal 触发 100%。
- 4 项任务用户真实完成对应动作后自动标记。
- Checklist 任意时刻可关，关后永久静默直至 reset。
- 设置页重置后下次进首页 modal 重新弹出。
- 跨用户隔离：alice 完成的任务不出现在 bob 的状态中。
- 桌面端 0 视觉变化（≥md viewport）。

### 7.2 性能

- 首屏增量 ≤ 8KB gzipped JS。
- Driver.js Tour 启动 ≤ 200ms。
- Checklist 渲染不引发 layout shift（CLS = 0）。

### 7.3 视觉

- 移动端 320 / 375 / 390 / 430 / 768px 不破布局。
- Welcome modal 在 320px 下不溢出，内容可完整阅读。
- Checklist 浮在 tabbar 之上、不挡主内容核心区。
- Driver.js popover 与现有 shadcn dark 主题一致（不出现默认白底）。

### 7.4 多租户与安全

- `/api/onboarding/*` 所有端点未登录返 401。
- `user_onboarding` 行 `created_by` 索引，跨用户隔离 SQL 严格。
- 任务完成钩子从 `g.user.id` 取用户，禁止从 request body 信任 user_id。

## 8. 风险与处理

| 风险 | 影响 | 处理 |
|---|---|---|
| 引导组件被加载到已登录老用户首页（错误触发）| 老用户突然看到欢迎 modal 觉得困扰 | 后端 register handler 才写 `welcome_pending=true`；老用户 `user_onboarding` 行不存在 → state API 返默认空 + 不弹 modal |
| Driver.js 锚点元素被动态卸载（如懒加载）| Tour 中途黑屏或卡死 | 6 个锚点全部位于 dashboard 首屏 + 永久 mount 组件；Driver.js `allowClose: true` 提供逃生路径 |
| 4 任务完成钩子忘记调 `_mark_onboarding_step` | 用户做了动作但 checklist 不更新 | 在 PR review checklist 加一条 + 单测覆盖每个 hook 调用点 |
| 移动端 localStorage hint 状态丢失（清缓存）| hint 重弹 | 可接受（用户主动清缓存重置一切）|
| Onboarding 状态写失败（DB 异常）| 用户看到永久弹窗 | 后端 fail-soft：写失败 → log warn + 不阻塞 register；前端容错 fetch 失败 → 不弹 modal |
| Driver.js z-index 冲突（与 MobileTopbar / tabbar / modal）| 视觉错乱 | Driver.js overlay z-index = 999；MobileTopbar = 40；tabbar = 5；Welcome modal = 100；Checklist = 6 —— 已明确分层 |
| 风险提示被合规要求改写 | 文案变动 | 文案集中在 `<WelcomeModal>` 一处常量，改一行即可 |

## 9. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-15 | 初版：基于 [`demo_onboarding_v1.html`](../../demo_onboarding_v1.html)；4 项 Checklist（持仓/分析/选股/纸面）+ Driver.js 6 步 Tour + 4 空状态 CTA + LLMSwitcher inline hint + 设置页重开入口；仅移动端 |
