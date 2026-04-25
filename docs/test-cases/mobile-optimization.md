# 测试用例：移动端统一优化（11 页 × 3 断点）

| 项 | 值 |
|---|---|
| Feature | `mobile-optimization` |
| 版本 | v1.0 |
| 日期 | 2026-04-18 |
| 关联设计 | [../design/mobile-optimization.md](../design/mobile-optimization.md) |

## 汇总

| 分类 | 用例数 |
|---|---|
| 通用组件单元 | 12 |
| 断点矩阵（11 页 × 3 断点） | 33 |
| 触摸目标 & 可达性 | 8 |
| 表格→卡片降级（paper） | 5 |
| 横滑行为（tabs / chips） | 4 |
| 折叠行（collapse-row） | 5 |
| 性能 & Lighthouse | 4 |
| 回归（桌面 ≥768） | 6 |
| 真机（iOS / Android） | 5 |
| **总计** | **82** |

**测试工具**：
- 视觉/交互：Playwright（`tests/frontend/test_mobile_*.spec.js`）
- 静态 CSS：简单 jsdom + PostCSS 解析（可选）
- 真机：BrowserStack 或本地 Safari/Chrome DevTools + 实机

---

## 1. 通用组件单元（12）

### 1.1 `form-row-mobile` (3)

**TC-MO-C1**：≤575px，`.form-row-mobile > .col-6` 实际宽度 == 100%

```js
test('form-row-mobile collapses to single column at 375px', async ({page}) => {
  await page.setViewportSize({width: 375, height: 667});
  await page.goto('/#analysis');
  const col = page.locator('#page-analysis .form-row-mobile > .col-6').first();
  const box = await col.boundingBox();
  const parent = await col.locator('..').boundingBox();
  expect(box.width).toBeCloseTo(parent.width, 0);
});
```

**TC-MO-C2**：≥576px，`.form-row-mobile > .col-md-4` 恢复 33.33% 宽

**TC-MO-C3**：`.form-row-mobile .btn` 在 ≤575px `min-height >= 44`

### 1.2 `num-responsive` (2)

**TC-MO-C4**：`.signal-value.num-responsive` 长文本 "OVERWEIGHT" 在 375px 不换行不溢出

**TC-MO-C5**：`.stat-value.num-responsive` 显示 "¥1,234,567.89" 在 375px 不溢出容器

### 1.3 `tabs-scrollable` (2)

**TC-MO-C6**：analysis 7 个 tab 在 375px 超出容器宽度时可横向滚动

**TC-MO-C7**：最后一个 tab 可通过触摸/滚动到达并被点击

### 1.4 `collapse-row` (2)

**TC-MO-C8**：点击 head 切换 `data-expanded` 属性

**TC-MO-C9**：点击 head 内 toggle checkbox **不触发**展开（stopPropagation）

### 1.5 `btn-group-wrap` (1)

**TC-MO-C10**：3 按钮在 375px 换行为 2+1（两行）且每个 ≥44 高

### 1.6 `chip-row` (1)

**TC-MO-C11**：6 个 chip 在 375px 可横滑，不出现纵向滚动

### 1.7 `table-to-cards` (1)

**TC-MO-C12**：≤575px 原 table `display:none`，`.table-cards-mobile` 可见；≥576px 反之

---

## 2. 断点矩阵（11 页 × 3 断点 = 33）

每页在 375 / 414 / 768 px 下各 1 条。断点 768 是桌面回归锚点。

| # | 页 | 375px 验收 | 414px 验收 | 768px 验收 |
|---|---|---|---|---|
| TC-MO-M1 | dashboard | stat-value 不换行；图表高 ≤280px；无横滑 | 同 375 | 恢复 420px 图表；stat 4 列 |
| TC-MO-M2 | analysis | 表单行单列；signal-value 不溢出；tab 横滑可达末位 | 同 375 | 表单 col-md-*；tab 全可见 |
| TC-MO-M3 | history | 搜索框 + 按钮单列全宽 | 同 375 | 按 col-md-* 并排 |
| TC-MO-M4 | screener | guru 4 行单屏可见；NL textarea 2 行不截断；chip-row 可滑；无顶部时间戳 | 同 375 | guru 2 列；chip 改 dropdown 或保留 |
| TC-MO-M5 | portfolio | 买/卖表单单列；m-card 列表不横滑 | 同 375 | 表单 col-md-*；恢复原布局 |
| TC-MO-M6 | alerts | 4 字段表单单列；select 标签不截断 | 同 375 | 恢复 col-md-* |
| TC-MO-M7 | reports | 报告生成表单单列 | 同 375 | 恢复 col-md-* |
| TC-MO-M8 | backtest | 5 字段参数单列；日期 picker 聚焦后字段可见 | 同 375 | 2-3 栏参数 |
| TC-MO-M9 | paper | 日表显示为卡片列表；P0 列（日/信号/总值/累计）可见 | 同 375 | 10 列表格显示 |
| TC-MO-M10 | settings | btn-group 换行 2+1；settings-row value 不截断 | 同 375 | btn-group 一排 |
| TC-MO-M11 | tasks | filter 按钮横滑，不纵向挤 | 同 375 | 按钮正常排列 |

每行实际扩展为 3 个独立 test case，共 33。

### 断点 375px 公共断言

```js
test.describe('375px common', () => {
  test.use({viewport: {width: 375, height: 667}});
  for (const page of PAGES) {
    test(`${page} — no horizontal body scroll`, async ({page: p}) => {
      await p.goto(`/#${page}`);
      const scrollW = await p.evaluate(() => document.body.scrollWidth);
      const innerW = await p.evaluate(() => window.innerWidth);
      expect(scrollW).toBeLessThanOrEqual(innerW + 1);  // +1 容许 subpixel
    });
  }
});
```

---

## 3. 触摸目标 & 可达性（8）

### TC-MO-A1：所有可点元素 ≥44×44

```js
test('all clickable targets meet 44x44 on mobile', async ({page}) => {
  await page.setViewportSize({width: 375, height: 667});
  await page.goto('/');
  for (const sel of ['button:visible', 'a:visible', '.tabbar-item', 'input[type=checkbox]', '.chip']) {
    const targets = await page.locator(sel).all();
    for (const t of targets) {
      const box = await t.boundingBox();
      if (!box) continue;
      expect(box.width,  `${sel}`).toBeGreaterThanOrEqual(44);
      expect(box.height, `${sel}`).toBeGreaterThanOrEqual(44);
    }
  }
});
```

### TC-MO-A2：tabbar 可访问（aria-label 存在）

### TC-MO-A3：form 控件有关联 `<label>` 或 `aria-label`

### TC-MO-A4：暗色对比度 ≥ 4.5:1（axe-core 扫描）

### TC-MO-A5：tab 顺序合理（keyboard Tab 按顺序到达所有交互元素）

### TC-MO-A6：focus 环可见（outline 不被 CSS 抹掉）

### TC-MO-A7：modal 打开后 focus trap 在 modal 内

### TC-MO-A8：Skip link 或首个可聚焦元素 = 主 CTA

---

## 4. 表格→卡片降级（paper，5）

### TC-MO-T1：≤575px paper 日表以 `.m-card` 列表呈现

### TC-MO-T2：卡片默认展示 P0 列（日期 / 信号 / 总值 / 累计盈亏）

### TC-MO-T3：点击"展开"按钮显示 P1 列（收盘/持仓/市值/现金/当日盈亏）

### TC-MO-T4：≥576px 恢复表格视图，`.m-card` 隐藏

### TC-MO-T5：数据量 200 行下卡片渲染不卡（FPS ≥ 50）

---

## 5. 横滑行为（4）

### TC-MO-S1：analysis report tab 横滑到末尾可点击"风险评估"tab

### TC-MO-S2：screener chip-row 横滑到"港股"可选中并激活样式

### TC-MO-S3：tasks filter 按钮横滑后状态保持（选中 chip 不丢）

### TC-MO-S4：横滑容器无纵向溢出（`overflow-y: hidden`）

---

## 6. 折叠行（5）

### TC-MO-F1：screener 4 个 guru 折叠行首次加载均为收起状态

### TC-MO-F2：点击 head 展开，再次点击收起，`data-expanded` 正确切换

### TC-MO-F3：点击 toggle checkbox 切换启用状态，**不触发**展开

### TC-MO-F4：展开后金句、chip 标签可见

### TC-MO-F5：CSS 过渡 `transform caret` 0.2s 动画执行

---

## 7. 性能 & Lighthouse（4）

### TC-MO-P1：Lighthouse Mobile Performance ≥ 90

### TC-MO-P2：Lighthouse Mobile Accessibility ≥ 95

### TC-MO-P3：LCP @ 4G throttling ≤ 2.5s

### TC-MO-P4：INP（交互到绘制）≤ 200ms（触碰 chip / 展开 collapse-row）

---

## 8. 回归（桌面 ≥768，6）

桌面端 0 改动必须严格验证。

### TC-MO-R1：≥768px 下 11 页视觉 pixel-match baseline（Playwright 截图）

### TC-MO-R2：`.form-row-mobile` 不影响 ≥576px 下 `.row` 原行为

### TC-MO-R3：`.num-responsive` 在桌面下 font-size 与旧值相等（clamp 最大值）

### TC-MO-R4：paper 表在桌面仍显示完整 10 列

### TC-MO-R5：所有现有 Python + Node 自动化测试通过

### TC-MO-R6：已部署 Railway 实例无回归（smoke 测试）

---

## 9. 真机（5）

### TC-MO-D1：iPhone SE (375×667, Safari) —— 主流程：登录 → 分析 → 查看结果

### TC-MO-D2：iPhone 15 (393×852, Safari) —— 选股 → 筛选 → 查看详情

### TC-MO-D3：Pixel 7 (412×915, Chrome) —— 持仓 → 买入 → 查看盈亏

### TC-MO-D4：iPad mini (768×1024, Safari) —— 恢复桌面式布局验证

### TC-MO-D5：iOS 横屏（844×390）—— tabbar 位置、modal 可滚动

---

## 覆盖要求

| 模块 | 目标 |
|---|---|
| `style.css` 新增组件 | 100% 类出现在至少 1 个用例 |
| `index.html` 11 页 | 每页至少 3 条用例（断点矩阵保证） |
| 关键 JS（collapse-row / table-to-cards） | 单元覆盖 ≥ 90% |

### 运行命令

```bash
# 全部（含真机，跑前先配好 BrowserStack 凭证）
npx playwright test tests/frontend/test_mobile_*.spec.js

# 仅断点矩阵
npx playwright test --grep "@breakpoint"

# Lighthouse
npx lhci autorun --config=.lighthouserc.json
```

## 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-18 | 82 | 初版：组件单元 12 + 断点矩阵 33 + 可达性 8 + 表格卡片 5 + 横滑 4 + 折叠行 5 + 性能 4 + 回归 6 + 真机 5 |
