# 测试用例：UI React Island 迁移回归修复

| 项 | 值 |
|---|---|
| Feature | `ui-react-island-regression` |
| 版本 | v1.0 |
| 日期 | 2026-04-25 |
| 关联设计 | [../design/ui-react-island-regression.md](../design/ui-react-island-regression.md) |

## 汇总

| 分类 | 用例数 |
|---|---|
| P0 CRITICAL（8 + 移动溢出 1 + paper-trade 列表 1 + 菜单重组 3 + Tasks 6 + 实测 P0 4 = 23） | 23 |
| P1 HIGH（功能恢复 18 项 + 移动表单/grid 6 项 - Tasks 升级 2） | 24 |
| P2 MEDIUM/LOW + 视觉对比 | 24 |
| 横切：Stat / ChartPanel / form-row-mobile | 8 |
| Playwright E2E（关键流程） | 12 |
| 视觉回归（4 断点 × 11 页 = 44，每页 1 条计） | 11 |
| **总计** | **102** |

---

## 1. P0 CRITICAL（9 条，必跑）

### 1.1 Portfolio 卖出 + 修正成本 modal（2）

- **TC-RG-P0-1**：访问 `/portfolio` → 持仓行下方有 "卖出" 按钮 / Dialog；提交 `POST /api/portfolio/sell` 4 字段（ticker / shares / price / notes）成功后持仓更新
- **TC-RG-P0-2**：点击持仓行 → 修正成本价 modal 弹出；提交后持仓 avg_cost 字段更新

### 1.2 Paper-trade 权益曲线 + 列表页（2）

- **TC-RG-P0-3**：访问 `/paper-trade/<ticker>` → "日度数据" tab → ECharts 净值曲线 + drawdown 阴影渲染；横屏切换 ResizeObserver 触发 resize

- **TC-RG-P0-3b**：访问 `/paper-trade`（无 ticker）→ 列表页正常渲染：
  - 顶部默认 session ★ 突出卡（含 Sharpe / 总值 / 持仓天数）
  - 工具栏：[+ 新建 session] / 搜索框 / [我的 / 全部] tab / [刷新所有日度数据]
  - 会话卡 grid 桌面 3 列 / 平板 2 / 移动 1
  - 整卡点击跳 `/paper-trade/<ticker>`
  - 右上 ⋯ 菜单（重命名 / 删除 / 导出）
  - 移动端 ≤575.98px 单列 + stat clamp 不溢出

### 1.3 Dashboard 图表（2）

- **TC-RG-P0-4**：访问 `/` → 净值曲线图 ECharts 渲染（line + area），数据来自 `/api/dashboard.equity_curve`
- **TC-RG-P0-5**：访问 `/` → 仓位分布饼图 ECharts 渲染

### 1.4 Analysis 三大缺失（3）

- **TC-RG-P0-6**：触发分析 `/analysis` → 详情页 K 线图（TradingView widget 或 ECharts）渲染
- **TC-RG-P0-7**：分析详情 7 tab：技术面 / 基本面 / 情绪 / 新闻 / 多空辩论 / 风险 / 最终决策 全部存在；点击切换 markdown 内容渲染
- **TC-RG-P0-8**：分析进行中 → Pipeline DAG 显示 + 每阶段 `agent_stage_done` 事件更新进度

### 1.5 Dashboard stat-value 移动溢出（1）

- **TC-RG-P0-9**：375px 视口下，`$200,466.40` 这种大数字在 stat 卡内不溢出（`overflow-hidden` + `text-overflow:ellipsis` 生效）；同时 `<= 575.98px` stat grid 单列塌陷

### 1.6 菜单重组（3）

- **TC-RG-P0-10**：桌面 Sidebar 渲染 6 大组（概览 / 分析 / 选股 / 持仓 / 纸面交易 / 系统），每组顶部有 label + Separator
- **TC-RG-P0-11**：当前路径对应的 group + item 都激活高亮（左侧 2px 竖条 + 背景色）
- **TC-RG-P0-12**：移动 Tabbar 5 主项（仪表盘 / 分析 / 选股 / 持仓 / 更多）；点"更多"打开 sheet 显示其他 6 项 4×2 grid

### 1.7 任务中心 6 项（6）

- **TC-RG-P0-13**：列表加载更多 / 无限滚动正常工作；连续滚动到底加载第 2/3/4 批数据；底部显示 "已加载 N / 共 M"
- **TC-RG-P0-14**：类型 chip-row 渲染 8 个 chip（全部 / AI 分析 / 批量分析 / 选股 V3 / 回测 / 报告 / 纸面交易 / 其他）；多选生效（选 AI 分析 + 选股 V3 → 同时显示两类）
- **TC-RG-P0-15**：scope tab "我的 / 全部" 切换 → 重新 fetch（multi-tenant 后端已就绪）
- **TC-RG-P0-16**：每行尾部 [查看结果] 按钮（success 时显示）；按 task type 跳到对应落地页：
  - analysis → `/analysis/<analysis_id>`
  - screen_v3 → `/screener-v3?result=<task_id>`
  - backtest → `/backtest/<result_id>`
  - report → `/reports?id=<id>`
  - paper_trade → `/paper-trade/<ticker>`
  - paper_backfill → `/paper-trade`
  - qwen_fundamentals / qwen_news → `/analysis?ticker=<x>`
  - 其他 → `/tasks/<id>` 兜底
- **TC-RG-P0-17**：任务详情页操作按钮齐全：删除 / 重试（failed/cancelled）/ 取消（running/pending）/ 查看结果（success）；各按钮调用对应 API 成功

- **TC-RG-P0-18**：任务中心**空白 bug 修复**：`/tasks` 真实显示历史任务（不为空白）；后端 `{items}` schema 与前端对齐 → 渲染 ≥1 行任务

### 1.8 实测追加 P0（4 项）

- **TC-RG-P0-19**：Paper-trade 详情**空白 bug 修复**：访问 `/paper-trade/AAPL` 和 `/paper-trade/AAPL/`（带末尾斜杠）都正确解析 ticker 并渲染数据
- **TC-RG-P0-20**：Settings 页面包含 **GEMINI_API_KEY** 和 **QWEN_API_KEY (DashScope)** 两个字段；Save 后从 GET `/api/settings` 读回 masked 值正确
- **TC-RG-P0-21**：NavTopbar 含 `<LLMSwitcher>` 组件：渲染当前 active provider；下拉两选项（Qwen / Gemini），active 标 ✓
- **TC-RG-P0-22**：LLMSwitcher 4 状态：
  - 缺 key 选项灰显禁用 + tooltip "未配置 API key"
  - locked_by_env=true → 整下拉禁用 + 🔒 + tooltip "由环境变量锁定"
  - 切换中 loading state
  - 切换失败回滚 + toast.error

---

## 2. P1 HIGH（26 条）

### 2.1 Portfolio（5）

- **TC-RG-P1-1**：交易记录 Tab 渲染（tab + DataTable 6 列：时间 / 操作 / 股票 / 数量 / 价格 / 备注）
- **TC-RG-P1-2**：交易记录移动端卡片视图（≤575.98px）
- **TC-RG-P1-3**：持仓表新增"市场"列（US/CN/HK badge）
- **TC-RG-P1-4**：持仓表新增"市值"列（计算 = shares × price）
- **TC-RG-P1-5**：快照按钮 + 一键分析全部按钮恢复

### 2.2 Dashboard（3）

- **TC-RG-P1-6**：4 个快捷按钮（生成报告 / 分析全部持仓 / 预警中心 / 策略回测）跳转正确
- **TC-RG-P1-7**：当前持仓表 4 列恢复（market / cost / current_price / pnl_pct）
- **TC-RG-P1-8**：净值曲线图 range switcher（7D / 1M / 3M / 1Y）

### 2.3 Analysis（2）

- **TC-RG-P1-9**：基本面指标 card 渲染（ROE / D/E / FCF / margin 等字段）
- **TC-RG-P1-10**：最近新闻 card 渲染（近 5 条 + source + time）

### 2.4 History（2）

- **TC-RG-P1-11**：对比模式：列表行有 checkbox，多选后 [对比] 按钮 enable，点击打开 CompareModal
- **TC-RG-P1-12**：演变 timeline modal 打开 + 数据渲染

### 2.5 Alerts（3）

- **TC-RG-P1-13**：NewAlertDialog 顶部 5 个快速模板 chips（向上突破 +5% / 向下跌破 -5% / 止损 -10% / 止盈 +20% / 日内涨跌 ±3%），点击自动填充 condition + threshold
- **TC-RG-P1-14**：阈值建议：输入 ticker 后调 `/api/quote/<ticker>` 显示 "当前价 X，±5% 为 Y~Z"
- **TC-RG-P1-15**：alert row 5 元素移动端 ≤575.98px `flex-wrap` 不挤压

### 2.6 Backtest（3）

- **TC-RG-P1-16**：完成回测后结果页面在 `/backtest` 内显示（不必跳 tasks）
- **TC-RG-P1-17**：净值曲线 ECharts + drawdown 阴影
- **TC-RG-P1-18**：交易明细 DataTable

### 2.7 Settings（2）

- **TC-RG-P1-19**：定时调度器卡（启动 / 停止 / 刷新 + status 显示）
- **TC-RG-P1-20**：数据源状态卡（列表 + 各源状态徽章）

### 2.8 Tasks（已升级到 P0，本组只剩 1 项）

- **TC-RG-P1-23**：详情页有"返回列表"按钮（其余 P1-21/22 已升级到 P0-13/17）

### 2.9 横切移动端（3）

- **TC-RG-P1-24**：所有页面 `<= 575.98px` 视口下，`grid-cols-2/3/4` 全部塌陷为 1 列（含 dashboard / portfolio / settings / cost-estimate-grid）
- **TC-RG-P1-25**：所有 form 多字段 row 套 `.form-row-mobile` 工具类
- **TC-RG-P1-26**：Analysis 详情 7 tabs 在 375px 横滑可达末位 tab

---

## 3. P2 MEDIUM/LOW（24 条）

### 3.1 视觉对齐（11）—— 11 页 × 1 条

每页 1 条 Playwright 截图 pixel-match：

- **TC-RG-P2-1**：Dashboard 桌面 1440px pixel-match baseline
- **TC-RG-P2-2** ～ **TC-RG-P2-11**：其他 10 页同上

### 3.2 控件细节（13）

- **TC-RG-P2-12**：Reports 内容支持 markdown 渲染
- **TC-RG-P2-13**：Backtest 动态参数区（不同策略不同 schema）
- **TC-RG-P2-14**：Backtest 日期 picker focus 时 scrollIntoView 防键盘遮挡
- **TC-RG-P2-15**：Settings 通用配置编辑器（恢复 old 全字段）
- **TC-RG-P2-16**：Settings footer 敏感字段说明文案
- **TC-RG-P2-17**：Alerts 测试规则按钮
- **TC-RG-P2-18**：Alerts 规则预览实时更新
- **TC-RG-P2-19**：Alerts 立即检查所有按钮
- **TC-RG-P2-20**：Screener 首次使用 tip
- **TC-RG-P2-21**：Screener 大师评分 + 理由完整展示
- **TC-RG-P2-22**：Paper-trade ticker grid 列表（无参数访问 `/paper-trade`）
- **TC-RG-P2-23**：Paper-trade 日度明细表 9 列
- **TC-RG-P2-24**：Tasks 老 hash 路由 redirect（`/#paper` → `/paper-trade`）

---

## 4. 横切共享组件（8 条）

### 4.1 Stat 组件（3）

- **TC-RG-S-1**：Stat 内 `--fs-stat` clamp 生效（375px ~16px / 1440px ~22px）
- **TC-RG-S-2**：8+ 字符数字 `text-overflow:ellipsis` 不溢出容器
- **TC-RG-S-3**：tabular-nums 对齐多行数字

### 4.2 ChartPanel 组件（3）

- **TC-RG-S-4**：ResizeObserver 监听 container 尺寸变化触发 chart.resize()
- **TC-RG-S-5**：unmount 时 echarts.dispose() 释放资源
- **TC-RG-S-6**：loading 状态显示 skeleton 而非空白

### 4.3 form-row-mobile（2）

- **TC-RG-S-7**：≤575.98px 强制 col-12 单列
- **TC-RG-S-8**：≥576px 恢复原 grid 布局

---

## 5. Playwright E2E（12 条，跨流程）

- **TC-RG-E2E-1**：Portfolio 完整流程：买入 → 卖出 → 修正成本 → 看交易记录
- **TC-RG-E2E-2**：Analysis 完整流程：触发 → Pipeline DAG → 7 tab 切换 → bookmark
- **TC-RG-E2E-3**：Paper-trade 完整流程：访问 ticker → 日度数据 tab → 权益图渲染
- **TC-RG-E2E-4**：Dashboard 完整：4 stat → 净值图 → 分布图 → 4 快捷按钮跳转
- **TC-RG-E2E-5**：Alerts 流程：模板 chip → 阈值建议 → 测试 → 保存 → 触发历史
- **TC-RG-E2E-6**：Backtest 流程：参数 → 运行 → 结果显示 stat + 净值 + 明细
- **TC-RG-E2E-7**：History 流程：搜索 → 对比 → 演变 timeline
- **TC-RG-E2E-8**：Tasks 流程：列表 → 加载更多 → 详情 → 取消任务 → 删除
- **TC-RG-E2E-9**：Settings 流程：调度器启停 → 数据源状态 → LLM 切换 → 保存
- **TC-RG-E2E-10**：移动端 375px 完整 dashboard 浏览不溢出
- **TC-RG-E2E-11**：移动端 375px paper-trade 详情完整浏览
- **TC-RG-E2E-12**：移动端 375px portfolio 买入 + 卖出 dialog 操作

---

## 6. 视觉回归（11 条，4 断点）

每页 1 条，Playwright snapshot 对比：

```ts
test.describe.parallel('visual regression', () => {
  for (const path of ['/', '/analysis', '/history', '/screener-v3', '/portfolio',
                       '/alerts', '/reports', '/backtest', '/paper-trade',
                       '/settings', '/tasks']) {
    for (const viewport of [{w:375,h:667}, {w:768,h:1024}, {w:1440,h:900}]) {
      test(`${path} @ ${viewport.w}`, async ({ page }) => {
        await page.setViewportSize(viewport)
        await page.goto(path)
        await expect(page).toHaveScreenshot()
      })
    }
  }
})
```

---

## 7. 执行规则

### 7.1 P0 闸门

P0 任一条 fail → **不允许 deploy**。

### 7.2 修复→回归循环

每 Phase R-1 ~ R-7 完成后：
1. 跑该 Phase 对应用例
2. 对应 Playwright snapshot 更新 baseline
3. 跑全量 P0 + 当前 Phase 的 P1
4. commit + push

### 7.3 Old Jinja 截图归档

P0 开始前必须先把老 Jinja UI 在 `/app` 路径下的截图归档作为对比基线：

```bash
# 截图脚本
npx playwright test tests/visual/legacy-snapshot.spec.ts --update-snapshots
# 输出到 validation/regression/legacy-baseline/
```

每页桌面 + 移动 2 张，共 22 张作 reference。

---

## 8. 覆盖要求

| 模块 | 目标 |
|---|---|
| P0 CRITICAL | 100% pass |
| P1 HIGH | ≥ 95% pass（≤ 1 条 waive 需备注） |
| 共享组件 | 100% |
| Playwright E2E | 12 条全过 |
| 视觉回归 | 桌面 100% / 移动 ≥ 90%（允许字号 ±2px 差异） |

### 运行命令

```bash
# P0 闸门
npx playwright test tests/regression/p0/ -v

# 全量回归
npx playwright test tests/regression/ -v

# 只跑视觉
npx playwright test tests/regression/visual/

# 老 baseline 截图
npx playwright test tests/regression/legacy/ --update-snapshots
```

## 9. 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-25 | 90 | 初版：P0 9 + P1 26 + P2 24 + 共享组件 8 + E2E 12 + 视觉 11；P0 闸门强约束 |
| v1.1 | 2026-04-25 | 94 | 补充：P0 新增 paper-trade 列表页用例（TC-RG-P0-3b）+ 菜单重组 3 条（TC-RG-P0-10~12，含 Sidebar 6 组渲染 / active 高亮 / Mobile Tabbar 5+更多 sheet） |
| v1.2 | 2026-04-25 | 97 | 补充：P0 新增 Tasks 5 项（TC-RG-P0-13 分页 / P0-14 类型 chip / P0-15 scope tab / P0-16 跳转结果落地页 9 类映射 / P0-17 详情操作齐全）；P1 Tasks 由 3 → 1（其他 2 升级 P0） |
| v1.3 | 2026-04-25 | 102 | 补充实测 P0 5 项：TC-RG-P0-18 Tasks 空白 bug（API schema 不匹配）/ P0-19 Paper-trade ticker 详情空白 bug（pathname 末尾斜杠）/ P0-20 Settings 缺 Gemini+Qwen API key 字段 / P0-21~22 LLMSwitcher 4 状态完整（active/缺 key/env 锁定/loading） |
