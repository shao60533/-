# 技术方案：移动端统一优化（11 页 × 3 断点）

| 项 | 值 |
|---|---|
| Feature | `mobile-optimization` |
| 版本 | v1.0 |
| 日期 | 2026-04-18 |
| 关联测试用例 | [../test-cases/mobile-optimization.md](../test-cases/mobile-optimization.md) |
| 关联设计 | [ui-ux-redesign.md](./ui-ux-redesign.md) v1.0（初版整体 UI） |

## 1. 背景与范围

### 1.1 起因

用户反馈智能选股 V2 页面在 iPhone（375px）下：

- NL 输入 placeholder 被截断
- 投资大师 2 列卡片每张占 200px 高 → 一屏只看得到 2 张
- 顶部时间戳、辅助提示 label 冗余占高

进一步审计全部 11 页后，问题是系统性的，不是 screener 独有。

### 1.2 诊断汇总

11 页共 22+ 问题，归纳成 **8 类共性病根**：

| # | 类别 | 影响页 |
|---|---|---|
| 1 | Bootstrap `col-6 col-md-X` 在 375px 下依然 2 栏，控件宽度不到 180px | analysis / portfolio / alerts / reports / history |
| 2 | 触摸目标 <44px（btn-sm、紧凑按钮组） | settings / tasks / history |
| 3 | 大号数字溢出（`.signal-value 40px`、`.stat-value 20px` 遇长值换行） | dashboard / analysis |
| 4 | 表格无移动卡片 fallback（paper 10 列表格直接塞 375px） | paper |
| 5 | 图表在手机高度未降（min-height 420px 占满屏） | dashboard / analysis |
| 6 | Tab 组不滚动不塌陷（analysis 7 个 tab 装不下） | analysis |
| 7 | 按钮组不换行（`btn-group` 挤一排） | settings / tasks |
| 8 | 多列卡片在手机占满高度（guru 2 列 / fund 2 列） | screener / analysis |

### 1.3 范围

**In Scope**：
- 11 个页面 [index.html](../../stock_trading_system/web/templates/index.html) 的布局、断点、控件规格调整
- 通用组件 CSS（加到 [style.css](../../stock_trading_system/web/static/css/style.css)）
- 最小必要的 HTML 结构调整（加容器类、补断点类、重排栅格）
- 视觉回归 + 交互验收用例

**Out of Scope**：
- 不改后端 API、不改数据结构
- 不重设计视觉风格（颜色/字体/暗色主题保持）
- 不改桌面端（≥768px）任何已工作良好的布局
- 不引入新的 UI 框架（继续 Bootstrap 5 + 自定义 CSS）

### 1.4 目标

| 指标 | 目标 |
|---|---|
| 所有触摸目标 ≥ 44×44px | 100% |
| 375px 下无横向滚动（body 层） | 100% 页 |
| 第一屏关键 CTA 无遮挡 | 100% 页 |
| 长数值（8+ 字符）不截断、不溢出容器 | 100% 覆盖 |
| 表格在 ≤576px 有卡片降级视图 | paper 页先做，其他页沿用模式 |
| Lighthouse Mobile Accessibility | ≥ 95 |

## 2. 设计 tokens

统一沉淀到 `:root` CSS 变量，替代散落的硬编码值。

### 2.1 断点

```css
:root {
  --bp-xs: 375px;   /* iPhone SE / mini 最小 */
  --bp-sm: 576px;   /* 小手机横屏 / phablet */
  --bp-md: 768px;   /* iPad 竖屏 / 平板临界 */
  --bp-lg: 992px;   /* 桌面 */
}
```

CSS 媒体查询语义对齐 Bootstrap 5 断点：`≤575.98px` = xs、`≤767.98px` = sm、`≥768px` = md+。

### 2.2 触摸目标

```css
:root {
  --touch-min: 44px;          /* iOS HIG 最小 */
  --touch-pad-x: 14px;
  --touch-gap: 8px;
}
```

规则：任何可点元素 `min-height: var(--touch-min)`，在 `≤767.98px` 范围强制生效。

### 2.3 字号阶梯（响应式）

```css
:root {
  --fs-xs:   clamp(10px, 2.4vw, 11px);
  --fs-sm:   clamp(12px, 3.2vw, 13px);
  --fs-base: clamp(13px, 3.6vw, 14px);
  --fs-md:   clamp(14px, 4vw, 16px);
  --fs-lg:   clamp(16px, 4.8vw, 18px);
  --fs-xl:   clamp(18px, 5.6vw, 22px);
  --fs-h2:   clamp(18px, 5vw, 24px);
  --fs-hero: clamp(22px, 7vw, 40px);   /* signal-value */
  --fs-stat: clamp(16px, 4.6vw, 22px); /* stat-value */
}
```

用 `clamp()` 避免写三份 media query。桌面值（最大）保持现状，375px 以下自动缩到小值。

### 2.4 间距

```css
:root {
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 24px;
  --sp-6: 32px;
  --page-pad-mobile: 12px;
  --page-pad-tablet: 16px;
  --page-pad-desktop: 24px;
}
```

## 3. 通用组件规范

加到 [style.css](../../stock_trading_system/web/static/css/style.css)，11 页共用。

### 3.1 `.form-row-mobile` —— 表单行

**问题**：现有 `<div class="row"><div class="col-6 col-md-4">…</div>…</div>` 在 375px 下挤成 180px 宽。

**规范**：

```css
/* 默认保持桌面行为（Bootstrap row + col-md-* 分栏） */
/* ≤576 强制垂直 */
@media (max-width: 575.98px) {
  .form-row-mobile > [class*="col-"] {
    flex: 0 0 100%;
    max-width: 100%;
    margin-bottom: var(--sp-3);
  }
  .form-row-mobile > [class*="col-"]:last-child {
    margin-bottom: 0;
  }
  .form-row-mobile .btn,
  .form-row-mobile .form-control,
  .form-row-mobile .form-select {
    width: 100%;
    min-height: var(--touch-min);
  }
}
```

**用法**：把受影响的 `.row` 加上 `form-row-mobile` 类即可。不动既有 `col-md-*` 桌面断点。

**适用页**：analysis / portfolio / alerts / reports / history。

### 3.2 `.num-responsive` —— 响应式数字

**问题**：`.signal-value: 40px` 遇到 "OVERWEIGHT" 或长数字在 375px 换行/溢出。

**规范**：

```css
.num-responsive {
  font-size: var(--fs-hero);
  line-height: 1.15;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  word-break: normal;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.num-responsive.num-stat { font-size: var(--fs-stat); }
.num-responsive.num-inline { font-size: var(--fs-md); white-space: nowrap; }
```

**用法**：把 `.signal-value`、`.stat-value`、`.quote-price` 的字号改引用 token，并加 `.num-responsive` 类。

### 3.3 `.table-to-cards` —— 表格卡片降级

**问题**：paper 页 10 列表格在 375px 只能横滑，用户看不到全貌。

**规范**：两种视图共存，通过媒体查询切换。

```html
<!-- 桌面：保留表格 -->
<table class="ptv-daily-table table-to-cards">
  <thead><tr><th>日期</th><th>收盘</th>…</tr></thead>
  <tbody>
    <tr data-card='{"日期":"2026-04-18","收盘":"$210.5",…}'>
      <td>2026-04-18</td><td>$210.5</td>…
    </tr>
  </tbody>
</table>
<!-- 移动：JS 根据 data-card 渲染 .m-card 列表 -->
<div class="table-cards-mobile d-none"></div>
```

```css
@media (max-width: 575.98px) {
  .table-to-cards { display: none; }
  .table-cards-mobile { display: block !important; }
}
```

**卡片模板**（复用已有 `.m-card`）：

```html
<div class="m-card">
  <div class="m-card-head">
    <span class="m-card-ticker">2026-04-18</span>
    <span class="m-card-sub">BUY</span>
  </div>
  <div class="m-card-row"><span>收盘</span><span>$210.5</span></div>
  <div class="m-card-row"><span>总值</span><span>$10,520</span></div>
  <div class="m-card-row"><span>累计</span><span>+5.2%</span></div>
  <!-- 低优先级列默认折叠，展开按钮点开 -->
</div>
```

**列优先级**（paper 表）：
- P0 默认展示：日期、信号、总值、累计
- P1 折叠后可见：收盘、持仓、市值、现金、当日盈亏
- P2 二级详情页：回撤

### 3.4 `.tabs-scrollable` —— 横滑 Tab

**问题**：analysis 页 7 个报告 tab 在 375px 装不下。

**规范**：

```css
.tabs-scrollable {
  display: flex;
  gap: var(--sp-1);
  overflow-x: auto;
  overflow-y: hidden;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
  padding: 0 var(--page-pad-mobile);
  margin: 0 calc(-1 * var(--page-pad-mobile));
}
.tabs-scrollable::-webkit-scrollbar { display: none; }
.tabs-scrollable > .nav-item,
.tabs-scrollable > .nav-link {
  flex: 0 0 auto;
  scroll-snap-align: start;
  min-height: var(--touch-min);
  white-space: nowrap;
}
/* 可选：右侧淡出指示有更多 */
.tabs-scrollable-wrap {
  position: relative;
}
.tabs-scrollable-wrap::after {
  content: ""; position: absolute; top: 0; right: 0; bottom: 0; width: 24px;
  background: linear-gradient(to right, transparent, var(--bg-primary));
  pointer-events: none;
}
```

**用法**：原 `.nav .report-tabs` 包在 `<div class="tabs-scrollable-wrap"><div class="tabs-scrollable">…</div></div>`。

### 3.5 `.collapse-row` —— 折叠行（替代大卡片）

**问题**：screener 的 guru 2 列卡片每张 200px 高，4 张占 400px × 2 列 = 8 行。

**规范**：默认单行 56px，点击展开到 140px。

```html
<div class="collapse-row" data-expanded="false">
  <div class="collapse-row-head">
    <span class="avatar avatar-sm">WB</span>
    <div class="collapse-row-title">
      <strong>Warren Buffett</strong>
      <span class="muted">价值投资 / 护城河</span>
    </div>
    <label class="toggle">
      <input type="checkbox" checked>
      <span class="toggle-track"></span>
    </label>
    <i class="bi bi-chevron-down collapse-row-caret"></i>
  </div>
  <div class="collapse-row-body">
    <div class="chip-row">
      <span class="chip">经济护城河</span>
      <span class="chip">ROE &gt; 15%</span>
      <span class="chip">低负债</span>
      <span class="chip">长期自由现金流</span>
    </div>
    <blockquote>在别人贪婪时恐惧，在别人恐惧时贪婪</blockquote>
  </div>
</div>
```

```css
.collapse-row {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: var(--sp-2);
  overflow: hidden;
  transition: border-color 0.15s;
}
.collapse-row-head {
  display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  min-height: var(--touch-min);
  cursor: pointer;
}
.collapse-row-title { flex: 1; min-width: 0; }
.collapse-row-title strong { display: block; font-size: var(--fs-base); }
.collapse-row-title .muted { font-size: var(--fs-xs); color: var(--text-secondary); }
.collapse-row-body {
  display: none;
  padding: 0 var(--sp-4) var(--sp-3);
  border-top: 1px solid var(--border);
}
.collapse-row[data-expanded="true"] .collapse-row-body { display: block; }
.collapse-row[data-expanded="true"] .collapse-row-caret { transform: rotate(180deg); }
.collapse-row-caret { transition: transform 0.2s; }
```

**JS**：点击 head 切换 `data-expanded`（toggle 按钮阻止冒泡，不触发展开）。

**适用页**：screener（guru 4 行）、settings（provider 信息行可复用）。

### 3.6 `.btn-group-wrap` —— 按钮组换行

**问题**：settings 的"启动/停止/刷新"btn-group 在 375px 挤成一排。

**规范**：

```css
@media (max-width: 575.98px) {
  .btn-group-wrap {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .btn-group-wrap .btn {
    flex: 1 1 calc(50% - var(--sp-2));
    min-height: var(--touch-min);
    min-width: 0;
  }
  .btn-group-wrap .btn:only-child { flex-basis: 100%; }
}
```

**用法**：把 `.btn-group` 替换为 `.btn-group-wrap`（需 JS 事件逻辑同样工作，只改样式）。

### 3.7 `.chip-row` —— 横滑 chip（辅助筛选器）

**问题**：screener "辅助提示：美股 / 市场偏好：(无)" 两个下拉 + label 在 375px 挤爆。

**规范**：

```css
.chip-row {
  display: flex;
  gap: var(--sp-2);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  padding-bottom: 2px;  /* 为 scrollbar 预留 */
  margin: 0 calc(-1 * var(--page-pad-mobile));
  padding-left: var(--page-pad-mobile);
  padding-right: var(--page-pad-mobile);
}
.chip-row::-webkit-scrollbar { display: none; }
.chip {
  flex: 0 0 auto;
  display: inline-flex; align-items: center; gap: 4px;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--fs-sm);
  white-space: nowrap;
  cursor: pointer;
  min-height: 32px;        /* chip 允许小于 44，但要整行点击面足够 */
}
.chip[aria-pressed="true"], .chip.active {
  background: rgba(56, 130, 255, 0.12);
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}
```

**用法**：screener 用 chip 取代"辅助提示 / 市场偏好"那一行 label + dropdown。

## 4. 每页改动清单

下文每页按"问题 → 改法 → 预计 diff 行数"列出。多数 diff < 30 行。

### 4.1 dashboard ([page-dashboard](../../stock_trading_system/web/templates/index.html#L168))

| 问题 | 改法 | Diff |
|---|---|---|
| 统计卡字号在 375 易溢出 | `.stat-value` 引用 `--fs-stat`，加 `.num-responsive` | 2 行 CSS |
| 图表 min-height 420px 占满屏 | `@media (max-width:575.98px) { .tv-widget { min-height: 280px; } }` | 3 行 CSS |
| 顶部日期时间悬浮冗余（与 screener 同款） | `.top-bar #clock` 在 ≤575 隐藏或缩成右下角 | 2 行 CSS |

### 4.2 analysis ([page-analysis](../../stock_trading_system/web/templates/index.html#L263))

| 问题 | 改法 | Diff |
|---|---|---|
| L266-276 表单行 `col-7/col-5` 比例怪异 | 行外层加 `form-row-mobile`；桌面仍按原 col-md-* | 3 处 class |
| L377-389 signal-value 40px 在 375 溢出 | 改用 `.num-responsive`，字号由 token 控制 | 5 行 CSS + 1 行 HTML |
| L400-407 7 个 report tab 装不下 | 外包 `.tabs-scrollable-wrap` + `.tabs-scrollable` | 4 行结构 + 3 行 CSS |
| 分析结果报告最大高 360px → 小屏下 55vh 更合理（已有） | 保留现状 | — |

### 4.3 history ([page-history](../../stock_trading_system/web/templates/index.html#L438))

| 问题 | 改法 | Diff |
|---|---|---|
| L441-445 搜索框 `col-8`/按钮 `col-4`→ 按钮 <44 宽 | 加 `form-row-mobile` | 1 行 class |
| history-item 点击区缺 ≥44 高 | `.history-item { min-height: 44px; }`（已 padding 14px 差不多） | 1 行 CSS |

### 4.4 screener ([page-screener](../../stock_trading_system/web/templates/index.html#L464))

对应用户最初诊断，合并 v1.2：

| 问题 | 改法 | Diff |
|---|---|---|
| 顶部时间戳多余 | `#clock` 在 ≤575 `display:none` | 1 行 CSS |
| NL textarea 单行截断 placeholder | 改 `<textarea rows="2">`，宽度 100% | 1 行 HTML |
| "AI 筛选"按钮与 textarea 不同行 | 按钮放 textarea 下方、全宽、主 CTA 色 | 结构调整 ~15 行 |
| 辅助提示 label + 双 dropdown 挤 | 换成 `.chip-row`（美股/A股/港股 + 市场偏好 popover） | 新增 ~20 行 HTML |
| guru 2 列大卡片 | 换成 `.collapse-row` × 4 单列 | 重写 ~50 行 HTML + 1 组件 CSS |
| 页底无结果锚 | 追加"上次结果 N 只"占位 div，已有 data 直接渲染 | ~10 行 HTML + JS |

### 4.5 portfolio ([page-portfolio](../../stock_trading_system/web/templates/index.html#L562))

| 问题 | 改法 | Diff |
|---|---|---|
| L569-582 / L590-603 买入/卖出表单 4 列挤 | 加 `form-row-mobile` | 2 处 class |
| 持仓列表（若为 table）缺移动卡片 | 若已是 `.m-card`（第 891 行样式已存在）则保留；若仍 table 加 `.table-to-cards` | 视 HTML 而定 |

### 4.6 alerts ([page-alerts](../../stock_trading_system/web/templates/index.html#L679))

| 问题 | 改法 | Diff |
|---|---|---|
| L687-706 4 字段表单行 | 加 `form-row-mobile` | 1 处 class |
| "价格高于" select 标签在 180px 宽 select 里截断 | form-row-mobile 后 select 全宽 → 不截断 | 同上 |

### 4.7 reports ([page-reports](../../stock_trading_system/web/templates/index.html#L759))

| 问题 | 改法 | Diff |
|---|---|---|
| L765-780 表单行 | 加 `form-row-mobile` | 1 处 class |

### 4.8 backtest ([page-backtest](../../stock_trading_system/web/templates/index.html#L796))

| 问题 | 改法 | Diff |
|---|---|---|
| L802-821 5 字段 `col-6` 参数行 | 加 `form-row-mobile`；日期/数字/select 全部 100% 宽 | 1 处 class |
| 日期 picker 键盘遮挡 | 输入聚焦后 `scrollIntoView({block:'center'})` | 5 行 JS |

### 4.9 paper ([page-paper](../../stock_trading_system/web/templates/index.html#L866))

| 问题 | 改法 | Diff |
|---|---|---|
| L886 `.paper-ticker-grid` minmax 260px 在 375 偏挤 | 改 minmax(200px, 1fr) + `@media ≤575 { 1fr }` | 3 行 CSS |
| L990 10 列日表无移动卡片视图 | 应用 `.table-to-cards` + JS 渲染 `.m-card` 列表，P0/P1/P2 列优先级见 §3.3 | ~40 行（JS 20 + HTML 骨架 10 + CSS 10） |

### 4.10 settings ([page-settings](../../stock_trading_system/web/templates/index.html#L1019))

| 问题 | 改法 | Diff |
|---|---|---|
| L1023-1029 启动/停止/刷新 btn-group 挤 | 改 `.btn-group-wrap` | 1 处 class |
| settings-row 在 375 下 label + value 一行可能挤 | `.settings-row { flex-wrap: wrap; }` + value 换行 | 2 行 CSS |

### 4.11 tasks ([page-tasks](../../stock_trading_system/web/templates/index.html#L1059))

| 问题 | 改法 | Diff |
|---|---|---|
| L1065-1076 6 filter btn + 刷新挤 | 外包 `.chip-row`（filter 本质是 chip 组） | 5 行 HTML |
| ms-auto 刷新按钮在挤状态失效 | 独立一行 或放进 chip-row 尾部 fixed | — |

## 5. 实施计划

按三阶段，每阶段独立 commit、可独立 review。

### Phase 0 —— CSS tokens + 通用组件（~2h）

1. 把 §2 tokens 写进 `:root`；
2. 把 §3 7 个通用组件 CSS 追加到 [style.css](../../stock_trading_system/web/static/css/style.css) 底部（不动已有规则，只加新类）；
3. 视觉回归：打开每页确保**无变化**（因为未绑定新类）。

**验收**：`diff style.css` 只有 additions，没有 deletions（除 token 迁移）。

### Phase 1 —— 高频 3 页（~3h）

`dashboard / analysis / screener`。

按 §4.1 / §4.2 / §4.4 的清单逐项改。screener 改动最大（含 collapse-row 组件 JS），放最后。

**验收**：
- 在 Chrome DevTools 375/414/768 三个视口检查每页
- Playwright 截图 baseline 更新

### Phase 2 —— 其余 8 页（~3h）

`history / portfolio / alerts / reports / backtest / paper / settings / tasks`。

多数页面只是加 `form-row-mobile` / `btn-group-wrap` 类，改动很小。
paper 页的 table-to-cards 需要 JS，放最后。

### Phase 3 —— 抛光 + 验收（~1.5h）

1. 跑完整测试套件（见 [测试用例](../test-cases/mobile-optimization.md)）；
2. Lighthouse Mobile 分数 ≥ 95；
3. 在真机（iPhone SE / iPhone 15 / iPad mini）各跑 5 分钟主流程；
4. 更新 changelog + doc commit hash。

**总计 ~9.5h**。

## 6. 兼容性与回滚

### 6.1 兼容性

- 所有新类**只在 ≤767.98px 生效**，桌面（≥768px）行为 0 改动；
- 未绑定新类的页面渲染 0 变化；
- 新 CSS 变量有 fallback（`clamp()` 在 iOS 14+ / Chrome 79+ 全支持，项目最低版本高于此）。

### 6.2 回滚

按 Phase 粒度 revert：
- Phase 0 revert → 恢复无 tokens 状态（页面无变化）
- Phase 1/2 revert → 对应页回到原布局

每个 Phase 独立 commit，回滚成本最低。

## 7. 风险

| 风险 | 概率 | 缓解 |
|---|---|---|
| `form-row-mobile` 破坏已有 `.row` 自定义样式 | 中 | 新类只加 `@media ≤575.98px` 规则，不改 `.row` 本体 |
| `.collapse-row` 初次展开/收起 JS 出错导致 guru 选不了 | 低 | 独立组件，开关 checkbox 在 head 区域 `stopPropagation` |
| paper 表格 table-to-cards 的 JS 渲染延迟 | 低 | Phase 2 最后做，单页单独测试；若延迟大先降级为"表格横向滚动 + sticky 首列" |
| clamp() 在很旧的 WebView 不支持（理论风险） | 极低 | 系统最低 iOS 14 / Android Chrome 90，全支持 |
| 现有视觉回归截图 baseline 失效 | 高（必然） | Phase 1/2/3 末尾统一刷新 baseline |

## 8. 验收 Checklist

在 Phase 3 完成前必须全部通过：

### 结构
- [ ] 11 页在 375px 下**无横向滚动**
- [ ] 11 页第一屏主 CTA 可见（非被底部 tabbar 遮挡）
- [ ] 所有表单行在 ≤576px 单栏
- [ ] 所有可点元素实测命中区 ≥ 44×44
- [ ] paper 表在 ≤576px 显示卡片视图，桌面显示表格
- [ ] analysis report tab 可横滑，首/末 tab 可点击

### 视觉
- [ ] 长数字在 signal-value / stat-value 容器内不换行、不溢出
- [ ] guru 4 张在 screener 单屏可见
- [ ] settings 按钮组不遮挡页面标题
- [ ] 无 placeholder 被截断（NL 输入 / select label）

### 性能
- [ ] Lighthouse Mobile Performance ≥ 90
- [ ] Lighthouse Mobile Accessibility ≥ 95
- [ ] 首屏 LCP ≤ 2.5s（4G throttling）

### 回归
- [ ] 桌面（≥768px）11 页视觉 pixel-match baseline
- [ ] 已有自动化测试全绿（Python + Node）

## 9. 与其他 feature 的关系

| Feature | 关系 |
|---|---|
| [model-switch](./model-switch.md) v1.0 | 该 feature 会在 Nav 加下拉。本文件 §4.1/§4.4 的顶部区域调整要预留下拉位置（建议下拉组件也用 `.chip-row` 风格对齐移动端） |
| [screener-v2](./screener-v2.md) v1.1 | 本文件 §4.4 即 screener-v2 的 v1.2 移动端专项，合并在此一处管理（不再给 screener-v2 出独立 v1.2 文档） |
| [paper-trade](./paper-trade.md) v1.2 | 本文件 §4.9 的 table-to-cards 是对 paper-trade 前端的移动端补丁，不改其数据模型/API |
| [ui-ux-redesign](./ui-ux-redesign.md) v1.0 | 本文件是对 ui-ux-redesign.md §移动端适配部分的实战落地，作为独立专项推进；未来若有 v2.0 整体视觉重设计，本文件 tokens 可以被吸收 |

## 10. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-18 | 初版：8 类病根归纳 + 4 类 tokens + 7 个通用组件 + 11 页清单 + 3 阶段实施计划 |
