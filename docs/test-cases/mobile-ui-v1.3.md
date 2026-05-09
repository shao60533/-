# 测试用例：移动端信息架构与 UI 实装 v1.3

| 项 | 值 |
|---|---|
| Feature | `mobile-ui-v1.3` |
| 版本 | v1.3 |
| 日期 | 2026-05-09 |
| 关联 PRD | [../prd/mobile-ui-v1.3.md](../prd/mobile-ui-v1.3.md) |
| 关联设计 | [../design/mobile-ui-v1.3.md](../design/mobile-ui-v1.3.md) |
| Demo 契约 | [../../demo_mobile_full_v1.html](../../demo_mobile_full_v1.html) |

## 汇总

| 分类 | 用例数 |
|---|---:|
| P0 导航与 More | 8 |
| P0 首页 + 持仓合并 | 10 |
| P0 Analysis | 9 |
| P0 Screener V3 | 8 |
| P0 Paper trade | 9 |
| 反向断言：不应出现 | 10 |
| 断点与可访问性 | 8 |
| 回归 smoke | 8 |
| **总计** | **70** |

工具建议：

- Playwright：主 UI / 移动断点 / 反向断言。
- `npm run build`：类型和构建回归。
- 后端 smoke：现有 API 不变性验证。

## 1. P0 导航与 More（8）

### TC-MUI-N1：底部 tab 顺序

视口 390px，打开首页。

验收：

- 底部 tab 文案依次为：首页、分析、发现、纸面、更多。
- 不存在底部一级 `持仓`。

### TC-MUI-N2：纸面 tab 进入列表页

点击底部 `纸面`。

验收：

- header/subtitle 为纸面交易语义。
- 页面存在 `纸面交易` section。
- 页面顶部不存在 `返回更多`。

### TC-MUI-N3：More 入口列表

点击底部 `更多`。

验收：

- 存在：报告中心、策略回测、交易记录、预警中心、任务中心、系统设置、账号。
- 不存在：调度器快捷入口。
- 不存在：纸面交易重复入口。

### TC-MUI-N4：More 无运营状态卡

验收：

- 不存在 `复盘与运营`。
- 不存在 `任务失败` 状态卡。
- 不存在 `报告生成 今日 14:20` 状态卡。

### TC-MUI-N5：系统设置副标题

验收：

- 系统设置副标题为 `模型与通知` 或生产等价文案。
- 不包含 `调度器`。

### TC-MUI-N6：非主页面高亮规则

从 More 进入报告/回测/任务。

验收：

- 底部 More 保持 active。
- 不错误高亮纸面或首页。

### TC-MUI-N7：纸面一级入口不经过 More

验收：

- 点击纸面 tab 后，不打开 More sheet。
- 不需要额外返回按钮即可浏览纸面列表。

### TC-MUI-N8：底部 tab 不遮挡内容

滚动每个主页面到底。

验收：

- 最后一块内容不被 tabbar 遮挡。

## 2. P0 首页 + 持仓合并（10）

### TC-MUI-D1：首页账户总览保留

验收：

- 显示账户总值。
- 显示今日 PnL。
- 显示总盈亏、收益率、活跃预警。
- 显示净值曲线。

### TC-MUI-D2：持仓明细在首页

验收：

- 首页存在 `持仓明细`。
- 存在搜索股票输入。
- 存在买入按钮。

### TC-MUI-D3：默认显示 5 张持仓

验收：

- 默认可见 ticker：NVDA、TSLA、AAPL、MSFT、AVGO。
- 默认不可见：LLY、META、AMD、TSM。

### TC-MUI-D4：全部 9 切换

点击 `全部 9`。

验收：

- 9 个 ticker 全部可见。
- `全部 9` 为 active。

### TC-MUI-D5：显示 5 切换

先点击 `全部 9`，再点击 `显示 5`。

验收：

- 恢复只显示前 5 张。
- `显示 5` 为 active。

### TC-MUI-D6：持仓卡字段完整

抽查 NVDA / TSLA / AVGO。

验收：

- 成本、现价、盈亏、市值、仓位/状态可见。
- PnL 正负颜色正确。

### TC-MUI-D7：每张持仓有看分析入口

对默认 5 张和展开后的 4 张逐项检查。

验收：

- 每张持仓卡都有 `看分析`。
- 点击后进入现有分析入口/详情，不创建新 ticker page。

### TC-MUI-D8：关键操作保留

验收：

- NVDA / TSLA 卡存在卖出、修正成本、移除。
- 点击操作打开现有 modal 或触发现有逻辑。

### TC-MUI-D9：批量分析持仓仍是产品缺口

验收：

- 显示 `建议补齐入口：批量分析持仓`。
- 标记为产品缺口/gap。
- 不出现“已实装”或真实提交成功文案。

### TC-MUI-D10：首页无待办聚合

验收：

- 不存在 `跨页面待办聚合`。
- 不存在 `今日决策队列`。
- 不存在 `不是现有独立功能`。

## 3. P0 Analysis（9）

### TC-MUI-A1：分析表单保留

验收：

- 存在 ticker 输入。
- 存在分析按钮。
- 存在标准 / 深度切换。

### TC-MUI-A2：Inbox 保留

验收：

- 存在分析记录 Inbox。
- 至少渲染运行中行和已完成行。

### TC-MUI-A3：Inbox 工具删除

验收：

- 不存在 `Inbox 工具`。
- 不存在刷新/筛选/看任务三按钮组。

### TC-MUI-A4：分析详情首屏结构化核心

进入 NVDA 分析详情。

验收：

- 第一个业务 section 为 `结构化分析核心`。
- 不先展示重复结论大卡。

### TC-MUI-A5：结构化核心严格 8 tabs

验收 tabs：

- 概览。
- 市场。
- 情绪。
- 新闻。
- 基本面。
- 辩论。
- 风险。
- 决策。

反向验收：

- 不存在结构化 tab `原文`。

### TC-MUI-A6：Quick Info 删除

验收：

- 不存在 `Quick Info`。
- 不存在 `AI 订单扩张 / ROE 64% / Bull 72% / 近 3 个月` 四卡摘要。

### TC-MUI-A7：K 线保留

验收：

- 结构化核心后存在 `K 线走势`。
- 图表容器非空。

### TC-MUI-A8：记录与操作下移

验收：

- `记录与操作` 位于 K 线之后。
- 包含日期、风险、深度。
- 包含再次分析、加入观察、纸面交易。

### TC-MUI-A9：原始报告 fallback 保留

验收：

- 存在 `原始报告`。
- chips 包含 Markdown / 市场原文 / 新闻原文 / 风险原文。

## 4. P0 Screener V3（8）

### TC-MUI-S1：发现表单保留

验收：

- 自然语言描述输入可见。
- 美股/A股/港股 chips 可见。
- 高级配置 details 可见。

### TC-MUI-S2：取消按钮删除

验收：

- 表单底部只保留 `开始筛选` 主按钮。
- 不存在和 `开始筛选` 并排的 `取消`。

### TC-MUI-S3：高级配置内容保留

验收：

- 可见 14 大师列表。
- 可见全选/推荐/全不选。
- 可见经典阈值 / Agent 深度 / 圆桌辩论。
- 可见 LLM 调用、时长、成本。

### TC-MUI-S4：最近选股保留

验收：

- AI 质量成长历史行可见。
- 宏观防守历史行可见。
- running 行产品缺口提示可见。

### TC-MUI-S5：结果页无透明度链路

进入选股结果。

验收：

- 不存在透明度链路。
- 不存在候选生成链路。
- 不存在 dynamic_llm / off-theme / cache hit。

### TC-MUI-S6：候选排名保留

验收：

- 存在 AVGO 排名卡。
- 存在综合分、投票条、现价/PE/共识。

### TC-MUI-S7：大师评分默认收起

验收：

- 14 位大师 details 默认 closed。
- 首屏只显示 summary。

### TC-MUI-S8：大师 summary 信息完整

验收 summary 文案包含：

- 共识 64%。
- 看多 9。
- 看空 2。
- 中性 3。

展开后验收：

- 14 位大师逐项结论可见。

## 5. P0 Paper Trade（9）

### TC-MUI-P1：纸面列表无返回更多

点击底部纸面。

验收：

- 不存在 `返回更多`。
- 页面直接展示 `纸面交易` 标题。

### TC-MUI-P2：纸面列表搜索和刷新保留

验收：

- 存在搜索代码输入。
- 存在刷新按钮。

### TC-MUI-P3：纸面列表模式 chips 保留

验收：

- 存在前向追踪。
- 存在历史回放。

### TC-MUI-P4：进入纸面详情

点击 NVDA 卡。

验收：

- 进入 NVDA 纸面交易详情。
- 存在 `返回纸面交易`。

### TC-MUI-P5：详情顶部无策略/日度 tabs

验收：

- 不存在顶部 `策略` / `日度数据` 两个页内 tab。
- 标题副文案为 `详情` 或等价。

### TC-MUI-P6：当前策略保留

验收：

- 存在当前策略。
- 存在初始建仓、加仓档、硬性止损。

### TC-MUI-P7：日度数据按钮去重

验收：

- 日度数据区只存在 `刷新日度数据` 一个按钮。
- 不存在重复 `日度数据` 按钮。

### TC-MUI-P8：AI 决策结构化

验收：

- 存在 `AI 决策核心 / 执行记录`。
- 决策内容为结构化卡，含评分、BUY、置信度、风险等级、执行方式、证据列表。
- 不存在英文 `FINAL TRANSACTION PROPOSAL` raw text。

### TC-MUI-P9：Plan/Event 双视图保留

验收：

- 存在 `按 Plan`。
- 存在 `按 Event`。
- 存在 Plan #28 当前和 Event analysis #146 记录。

## 6. 反向断言：不应出现（10）

这些用例用于防止已删内容回流。

| ID | 页面 | 不应出现 |
|---|---|---|
| TC-MUI-X1 | 首页 | 跨页面待办聚合 |
| TC-MUI-X2 | 首页 | 今日决策队列 |
| TC-MUI-X3 | 分析详情 | Quick Info |
| TC-MUI-X4 | 分析详情 | 结构化 tabs 中的原文 |
| TC-MUI-X5 | 发现结果 | 透明度链路 / 审计信息 |
| TC-MUI-X6 | 发现表单 | 取消按钮 |
| TC-MUI-X7 | 纸面列表 | 返回更多 |
| TC-MUI-X8 | 纸面详情 | 策略 / 日度数据页内 tab |
| TC-MUI-X9 | More | 复盘与运营 |
| TC-MUI-X10 | More | 调度器快捷入口 |

## 7. 断点与可访问性（8）

### TC-MUI-R1：375px 无横向溢出

主页面：首页、分析、发现、纸面、更多。

验收：

```js
expect(document.body.scrollWidth).toBeLessThanOrEqual(window.innerWidth + 1)
```

### TC-MUI-R2：390px 无横向溢出

同 TC-MUI-R1。

### TC-MUI-R3：430px 无横向溢出

同 TC-MUI-R1。

### TC-MUI-R4：768px 无横向溢出

同 TC-MUI-R1。

### TC-MUI-R5：主按钮触控区 >= 44px

检查底部 tab、主 CTA、chips、持仓操作按钮。

### TC-MUI-R6：chips 可横滑但不撑破 body

检查 Analysis tabs、Dashboard 持仓 chips、Screener chips、Paper chips。

### TC-MUI-R7：底部 tab 文案不换行

验收：

- 首页 / 分析 / 发现 / 纸面 / 更多均单行展示。

### TC-MUI-R8：内容底部不被 tabbar 遮挡

每个主页面滚到底，最后一个可见元素不被 tabbar 覆盖。

## 8. 回归 smoke（8）

### TC-MUI-G1：分析提交仍可进入运行态

### TC-MUI-G2：分析详情仍可打开结构化报告

### TC-MUI-G3：选股开始筛选仍进入 running 状态

### TC-MUI-G4：选股结果仍可打开

### TC-MUI-G5：纸面详情仍可刷新日度数据

### TC-MUI-G6：交易记录入口仍可打开

### TC-MUI-G7：报告/回测/预警/任务/设置入口仍可打开

### TC-MUI-G8：模型切换器仍可打开，provider/preset 两段式不回退

## 9. Playwright 示例

```ts
test('mobile nav matches v1.3 demo', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const labels = await page.locator('[data-mobile-tab] span').allTextContents()
  expect(labels).toEqual(['首页', '分析', '发现', '纸面', '更多'])
})

test('dashboard holdings show 5 then 9', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByText('NVDA')).toBeVisible()
  await expect(page.getByText('TSM')).toBeHidden()
  await page.getByRole('button', { name: '全部 9' }).click()
  await expect(page.getByText('TSM')).toBeVisible()
})

test('analysis structured tabs are exactly 8', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/analysis')
  await page.getByText('NVDA').click()
  const tabs = await page.locator('[data-analysis-structured-tabs] button').allTextContents()
  expect(tabs).toEqual(['概览', '市场', '情绪', '新闻', '基本面', '辩论', '风险', '决策'])
})
```

选择器名称可按实际组件调整，但断言语义不能变。

## 10. P0 放行标准

必须同时满足：

1. `npm run build` 通过。
2. P0 导航/首页/Analysis/Screener/Paper 用例全绿。
3. 反向断言全绿。
4. 375/390/430/768 无横向溢出。
5. 现有核心功能 smoke 全绿。
6. 没有新增后端 endpoint、migration、task type。

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.3 | 2026-05-09 | 基于 demo v1.3 的移动端 IA/UI 验收用例，70 条，覆盖正向功能、反向删除断言、断点和回归 smoke |
