# 技术方案：React Island 移动端二轮修复

| 项 | 值 |
|---|---|
| Feature | `mobile-react-island-fixes` |
| 版本 | v1.0 |
| 日期 | 2026-05-03 |
| 关联设计 | [mobile-optimization.md](./mobile-optimization.md) v1.0（首轮 11 页 Bootstrap 阶段） / [ui-react-island.md](./ui-react-island.md) v3.0（React Island 主迁移） |
| 关联 changelog | 本日条目 v1.0 |

---

## 1. 背景

首轮 [mobile-optimization.md](./mobile-optimization.md) 是在 Bootstrap 模板时代落地的，token + 7 个通用类（`form-row-mobile` / `tabs-scrollable` / `chip-row` / `collapse-row` …）已经写进了 [index.css](../../stock_trading_system/web/frontend/src/styles/index.css)。

后续做了 React Island 全量迁移（v3.0）：页面改用 React + 自有 `Tabs` / `Dialog` / `Card` / `MarkdownBody` 等组件，大量旧的 Bootstrap 类不再被消费。结果是首轮的部分组件（`tabs-scrollable`、移动 padding 兜底）只在少数页面被显式引入，其余页面退回组件默认值，移动端出现新一轮回归。

本轮（v1.0）只补齐 React Island 时代被漏掉的那些点，不重做首轮的 token / 类体系。

## 2. 复用（reuse-first）

按 `docs/engineering-principles.md` 的 L0→L4 复用阶梯：

| 层级 | 复用项 | 在本方案的作用 |
|---|---|---|
| L0 | [mobile-optimization.md](./mobile-optimization.md) v1.0 的 `--touch-min` / `--page-pad-mobile` / `clamp()` 字号 token | 直接沿用，不新增竞争 token |
| L0 | 现有 `.tabs-scrollable` 全局类（[index.css:157-167](../../stock_trading_system/web/frontend/src/styles/index.css)） | 让所有 `<TabsList>` 默认带它，省掉每页手动加 className |
| L1 | 现有 [MarkdownBody.tsx](../../stock_trading_system/web/frontend/src/components/shared/MarkdownBody.tsx) | 升级为唯一 Markdown 渲染入口；ReportsPage 直接用裸 `<Markdown>` 的写法改成走它 |
| L1 | 现有 `ChipRow` / `Chip`（[chip.tsx](../../stock_trading_system/web/frontend/src/components/ui/chip.tsx)） | DashboardPage 净值卡头部"时间筛选 + 重新计算"行复用现成 `flex-wrap`，不重发明 |
| L1 | Radix `DialogContent` | 只改全局 `dialog.tsx` 一处，所有页面自动受益（持仓买卖/纸面交易/警报新建等） |
| L2 | env(safe-area-inset-bottom) + CSS 自定义属性 | 用一个 `--mobile-tabbar-height` 同时驱动 `MobileTabbar` 高度和 `<main>` 底部留白，避免两端 magic number 漂移 |

**不新增** 的东西：
- 不再新增 token 文件
- 不新增 Markdown 自定义组件库（仅在 `MarkdownBody` 内部加 `prose` 容器规则与少量 `components` 覆写）
- 不引入 viewport 检测 hook；通过 CSS 解决

## 3. 问题清单

| 编号 | 严重度 | 现状 | 影响 |
|---|---|---|---|
| M-1 | P1 | [AppShell.tsx:7](../../stock_trading_system/web/frontend/src/components/shared/AppShell.tsx) 主内容只 `pb-16`（64px），但 [Sidebar.tsx:158-160](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx) 的 `MobileTabbar` 额外加了 `paddingBottom: env(safe-area-inset-bottom)`。iPhone 安全区让导航实际超过 64px。 | 列表末尾、表单提交按钮在 iPhone 全面屏下被遮挡 |
| M-2 | P1 | [dialog.tsx:34](../../stock_trading_system/web/frontend/src/components/ui/dialog.tsx) `DialogContent` 是 `fixed + w-full + max-w-lg + p-6`，无 `max-height` / `overflow-y-auto` / 移动端边距。 | 持仓买入/卖出/修正成本、警报新建等弹窗在小屏或横屏 footer 被推到屏外 |
| M-3 | P2 | [ReportsPage.tsx:277](../../stock_trading_system/web/frontend/src/islands/reports/ReportsPage.tsx) 直接用 `<Markdown remarkPlugins={[remarkGfm]}>` 而不是统一的 `MarkdownBody`，且 `prose` 容器没有为表格/代码块/长链接设横向滚动或断行；[AnalysisPage.tsx:1304](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx) 的原始模型输出区也只有 `overflow-y-auto`。 | 模型生成的宽表、长 fenced code、长 URL 在 375px 撑破容器、出现整页横向滚动 |
| M-4 | P2 | 共享 [tabs.tsx:14](../../stock_trading_system/web/frontend/src/components/ui/tabs.tsx) 默认 `inline-flex`，无横向滚动。AnalysisPage 单独显式加了 `tabs-scrollable`（[AnalysisPage.tsx:1236](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)），PortfolioPage / AlertsPage 没用。 | 计数变大后小屏溢出（如"持仓 (12) / 交易记录 (88)"） |
| M-5 | P2 | DashboardPage 净值卡头部 [DashboardPage.tsx:347](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 把 `CardTitle` + `ChipRow`（6 个时间档）+ `重新计算` Button 塞同一行；当前持仓行 [DashboardPage.tsx:424](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 是左右两组 flex，长 ticker / 大金额会挤压。 | 移动端布局挤压、按钮文字截断 |
| M-6 | P3 | [index.css:17-23](../../stock_trading_system/web/frontend/src/styles/index.css) 全局字号 token 用 `clamp(... vw ...)`。 | 文字随视口宽度连续变化，在 360–430 区间出现按钮/表格/卡片的临界宽度抖动；交易系统密集数字尤其敏感 |

## 4. 方案

### 4.1 M-1：底部安全区单一变量驱动

新增 CSS 变量 `--mobile-tabbar-height`，同时驱动两端：

```css
:root {
  --mobile-tabbar-height: calc(64px + env(safe-area-inset-bottom, 0px));
}
@media (min-width: 768px) {
  :root { --mobile-tabbar-height: 0px; }
}
```

[AppShell.tsx](../../stock_trading_system/web/frontend/src/components/shared/AppShell.tsx) 主内容用变量：

```tsx
<main
  className="flex-1 min-w-0"
  style={{ paddingBottom: "var(--mobile-tabbar-height)" }}
>
```

[Sidebar.tsx](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx) `MobileTabbar` 也读同一个变量（高度 = 64 + safe-area，内容 padding-bottom = safe-area）。

**为什么这样而不是单纯 `pb-20`**：64 是设计常量，安全区是设备常量；两者必须由设备驱动而非 magic number。

### 4.2 M-2：DialogContent 移动端约束

[dialog.tsx:34](../../stock_trading_system/web/frontend/src/components/ui/dialog.tsx) 的 className 改为：

```text
fixed left-1/2 top-1/2 z-50 grid -translate-x-1/2 -translate-y-1/2 gap-4
w-[calc(100vw-24px)] max-w-lg
max-h-[calc(100dvh-24px)] overflow-y-auto overscroll-contain
rounded-[var(--radius-lg)] border border-[var(--color-border)]
bg-[var(--color-bg-card)] p-4 sm:p-6
shadow-[0_24px_60px_-20px_rgba(0,0,0,0.7)] duration-200
data-[state=open]:animate-in data-[state=closed]:animate-out
data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0
data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95
```

要点：
- `100dvh` 而非 `100vh`：iOS Safari 地址栏收起时高度变化，`dvh` 跟随
- `overflow-y-auto` 让 footer 永远可达
- `overscroll-contain` 阻止弹窗滚到底拽出底层页面
- `p-4 sm:p-6` 移动端窄一点
- `w-[calc(100vw-24px)]` 与 `max-w-lg` 共存：小屏全宽、桌面回到 `max-w-lg`

### 4.3 M-3：MarkdownBody 升级为唯一入口

`MarkdownBody.tsx`：
1. 外层包 `div` 加 `mdx-body` 类（局部 scope）
2. 通过 `components` 覆写 `pre` / `table` / `a`：
   - `pre` 包一层 `<div class="overflow-x-auto rounded border border-border/40">`
   - `table` 同样包横向滚动容器
   - `a` 加 `break-all`，链接太长不撑破

同时在 `index.css` 加局部规则：

```css
.mdx-body :where(p, li) { overflow-wrap: anywhere; }
.mdx-body :where(code):not(pre code) { word-break: break-word; }
.mdx-body :where(img) { max-width: 100%; height: auto; }
```

[ReportsPage.tsx](../../stock_trading_system/web/frontend/src/islands/reports/ReportsPage.tsx) 把 `<Markdown remarkPlugins={[remarkGfm]}>{result.content}</Markdown>` 改成 `<Suspense …><MarkdownBody>{result.content}</MarkdownBody></Suspense>`，删除直接 import 的 `react-markdown` / `remark-gfm`（节省 bundle 重复）。

### 4.4 M-4：TabsList 默认横向滚动

[tabs.tsx:14](../../stock_trading_system/web/frontend/src/components/ui/tabs.tsx) `TabsList` 默认 className 追加：

```text
max-w-full overflow-x-auto scrollbar-none
```

并把 `inline-flex` 改成 `flex` —— 横向滚动需要明确的容器宽度。

`scrollbar-none` 沿用 `tabs-scrollable` 的隐藏 scrollbar 规则，在 `index.css` 补一个等价 utility（如果 Tailwind v4 没自带）：

```css
.scrollbar-none { scrollbar-width: none; }
.scrollbar-none::-webkit-scrollbar { display: none; }
```

副作用：原本显式加了 `tabs-scrollable` 的地方（AnalysisPage）冗余但无害，后续清理。

### 4.5 M-5：密集 flex 行加 wrap + min-w-0 + truncate

只针对 DashboardPage 两处：

[DashboardPage.tsx:347](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 净值卡头部：
- 外层 `flex items-center justify-between gap-2` → 加 `flex-wrap`
- `CardTitle` 加 `min-w-0 shrink-0`
- 右侧组合 `flex items-center gap-2` 加 `flex-wrap justify-end`

[DashboardPage.tsx:424](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 持仓行：
- 外层 `flex items-center justify-between` → 加 `flex-wrap gap-y-1`
- 左组 `flex items-center gap-3` 加 `min-w-0`，ticker `truncate`
- 右组 `flex items-center gap-4` 加 `ml-auto`，金额 `tabular-nums`（已有）

### 4.6 M-6：字号 token 去 vw 化

[index.css:17-23](../../stock_trading_system/web/frontend/src/styles/index.css) 改：

```css
--text-xs:   12px;
--text-sm:   13px;
--text-base: 14px;
--text-md:   15px;
--text-lg:   17px;
--text-xl:   20px;
--text-2xl:  24px;
```

底部 `--fs-stat` / `--fs-hero`（mobile-optimization.md token）保留 `clamp()`，因为它们专门给"大数字单卡"用，可控范围有限，撑破风险低。

**取舍**：交易系统重交互、轻散文，字号稳定 > 视觉自适应。所需排版差异由布局断点（grid / flex-wrap）承担，不由字号承担。

## 5. 验收

### 5.1 设备矩阵

DevTools 模拟 + 真机抽测：

| 设备 | 视口 | 必测页面 |
|---|---|---|
| iPhone SE 2 | 375 × 667 | `/` `/analysis` `/portfolio` `/alerts` `/reports` |
| iPhone 14 | 390 × 844 | 同上 + `/screener-v3` 结果页 |
| iPhone 14 Pro Max | 430 × 932 | `/portfolio` 弹窗（买入/卖出/修正成本） |
| iPhone SE 横屏 | 667 × 375 | 弹窗 footer 仍可达 |
| Pixel 7 | 412 × 915 | `/reports` Markdown 长表 |

### 5.2 检查点

- [ ] iPhone 全面屏底部 home indicator 不遮挡任何按钮
- [ ] 任意持仓 / 警报弹窗：滚动到 footer 后所有按钮可达
- [ ] `/reports` 渲染含宽表 / fenced code / 长 URL 的报告，无横向 body 滚动
- [ ] `/portfolio` 与 `/alerts` 标签计数变大后 TabsList 自动横滑
- [ ] 净值卡 6 档时间 chip + 重新计算按钮在 375px 自动换行
- [ ] 当前持仓行长 ticker（如 BRK.B）+ 大金额（>$10,000）不挤出容器
- [ ] 360 → 430 视口拖动时按钮文字字号不再连续抖动

### 5.3 回归

- 桌面（≥768px）AppShell / Tabs / Dialog 视觉 0 变化
- `npm test` 全绿
- `npm run build` ✓

## 6. 风险

| 风险 | 概率 | 缓解 |
|---|---|---|
| `100dvh` 在老 iOS Safari 不支持 | 低 | 项目最低 iOS 16，全支持；若担心可加 `100vh` fallback |
| TabsList 默认横滑后，某些页面原本期望"塞不下就换行"的视觉被改 | 中 | 现有所有 TabsList 调用点（grep `<TabsList`）：AnalysisPage / PortfolioPage / AlertsPage / 设置页等，均接受横滑；无依赖换行的场景 |
| MarkdownBody 改 `components` 后，桌面端 `prose` 表格视觉差异 | 低 | 横向滚动容器只在内容溢出时显示 scrollbar，正常宽表无视觉变化 |
| 字号去 vw 化后桌面端字号略小 | 低 | 桌面端原本就是 `clamp()` 上限值（11/13/14/16/18/22）；新值（12/13/14/15/17/20/24）相近，差距 ≤2px，不构成回归 |

## 7. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-03 | 初版：6 个 React Island 时代漏点（底部安全区 / Dialog 滚动 / MarkdownBody 唯一入口 / TabsList 默认横滑 / Dashboard 密集行 wrap / 字号 token 去 vw） |
