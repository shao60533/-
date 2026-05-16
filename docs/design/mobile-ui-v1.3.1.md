# 设计方案：移动端顶栏 + 账户卡 hero 化（v1.3.1 增量）

| 项 | 值 |
|---|---|
| Feature | `mobile-ui-v1.3.1` |
| 版本 | v1.3.1 |
| 日期 | 2026-05-10 |
| 关联 PRD | [../prd/mobile-ui-v1.3.1.md](../prd/mobile-ui-v1.3.1.md) |
| 父设计 | [mobile-ui-v1.3.md](mobile-ui-v1.3.md) |

---

## 1. 现状审计（实测 2026-05-10）

### 1.1 AppShell 移动端结构

[`components/shared/AppShell.tsx`](../../stock_trading_system/web/frontend/src/components/shared/AppShell.tsx) 当前完整实现：

```tsx
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />                        {/* hidden md:flex 桌面侧栏 */}
      <main className="flex-1 min-w-0 pb-16 md:pb-0">{children}</main>
      <MobileTabbar />                   {/* md:hidden 底部 tab */}
    </div>
  )
}
```

**移动端结构**：仅有底部 tabbar + 主内容，**没有顶栏**。

### 1.2 LLMSwitcher 现状

[`components/shared/LLMSwitcher.tsx`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) 是完整两段式 dropdown（provider + role preset，[OpenRouter v1.0 §9.1](llm-openrouter.md) 落地）。当前调用点：
- [`Sidebar.tsx:88`](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx) `<Sidebar>` 桌面侧栏顶部 logo 下方

**移动端无消费点**。

### 1.3 DashboardPage 账户卡

[`DashboardPage.tsx:494-549 <AccountOverviewCard>`](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 当前结构：
```
<Card>
  <CardContent>
    [账户总值] [今日 PnL]
    ─── border-t ───
    [总盈亏] [收益率] [活跃预警]   (grid-cols-3)
  </CardContent>
</Card>
```

**缺**：mini sparkline / hero 容器。

净值曲线在 [line 368-417](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 独立 Card 中（带完整 6 个 range chips + 重新计算按钮），位于 `lg:grid-cols-3` 桌面网格——移动端被推到首屏外。

### 1.4 数据流（不需新增）

- `<DashboardPage>` 调 [`/api/portfolio`](../../stock_trading_system/web/app.py) 拿 `data.history[]`（净值快照数组，每条 `{date, total_value, total_pnl, ...}`）
- `filteredHistory` 已按 range 过滤
- mini-chart 复用同一份数据，不需新接口

---

## 2. 模块结构

```
stock_trading_system/web/frontend/src/components/shared/
├── AppShell.tsx              ← 修改：插入 <MobileTopbar pageTitle={...}>
├── Sidebar.tsx               ← 不动(LLMSwitcher 仍在桌面侧栏)
├── LLMSwitcher.tsx           ← 不动(消费方+1)
├── MobileTopbar.tsx          ← 新建
└── Sparkline.tsx             ← 新建(纯 SVG mini-chart,~50 LOC)

stock_trading_system/web/frontend/src/islands/
├── dashboard/main.tsx        ← 修改:<AppShell pageTitle="首页 · 资产与持仓">
├── dashboard/DashboardPage.tsx ← 修改:<AccountOverviewCard> 加 sparkline + hero className
├── analysis/main.tsx         ← 修改:<AppShell pageTitle="分析 · Inbox 与命令">
├── screener-v3/main.tsx      ← 修改:<AppShell pageTitle="发现 · 智能选股 V3">
├── paper-trade-list/main.tsx ← 修改:<AppShell pageTitle="纸面交易">
├── ... (其余 island main.tsx 同步加 pageTitle prop)
```

---

## 3. `<MobileTopbar>` 设计

### 3.1 Props

```tsx
interface MobileTopbarProps {
  pageTitle?: string;   // 副标,如 "首页 · 资产与持仓"
}
```

### 3.2 渲染结构

```tsx
export function MobileTopbar({ pageTitle }: MobileTopbarProps) {
  return (
    <header className="md:hidden sticky top-0 z-40 bg-background/95 backdrop-blur border-b border-border">
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 min-w-0">
        <div className="min-w-0 flex flex-col">
          <span className="text-sm font-bold text-primary truncate">⚡ StockAI Terminal</span>
          {pageTitle && (
            <span className="text-[11px] text-muted-foreground truncate max-w-[200px]">
              {pageTitle}
            </span>
          )}
        </div>
        <div className="shrink-0">
          <LLMSwitcher />
        </div>
      </div>
    </header>
  )
}
```

**关键属性**：
- `md:hidden` —— 仅移动端
- `sticky top-0 z-40` —— 滚动跟随，z 高于内容低于 modal/sheet（modal 通常 z-50+）
- `bg-background/95 backdrop-blur` —— 半透明 + 模糊，避免内容透出
- `pb-16` 已在 `<main>`，不冲突
- LLMSwitcher 用 `shrink-0` 保证窄屏不被压缩

### 3.3 AppShell 集成

```tsx
export function AppShell({ children, pageTitle }: {
  children: React.ReactNode;
  pageTitle?: string;
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <MobileTopbar pageTitle={pageTitle} />
        <main className="flex-1 min-w-0 pb-16 md:pb-0">{children}</main>
      </div>
      <MobileTabbar />
    </div>
  )
}
```

每个 island main entry 显式传 `pageTitle`：
```tsx
// dashboard/main.tsx
<AppShell pageTitle="首页 · 资产与持仓">
  <DashboardPage />
</AppShell>
```

### 3.4 副标文案统一表

| Island | pageTitle |
|---|---|
| dashboard | `首页 · 资产与持仓` |
| analysis | `分析 · Inbox 与命令` |
| screener-v3 | `发现 · 智能选股 V3` |
| paper-trade-list / paper-trade-detail | `纸面交易` |
| portfolio（桌面侧栏可达，移动端经持仓详情来）| `持仓 · 管理` |
| transactions | `持仓 · 交易记录` |
| reports | `报告中心` |
| backtest | `策略回测` |
| alerts | `预警中心` |
| tasks | `任务中心` |
| settings | `系统设置` |
| login / register | （这两页通常无 AppShell 框架，不动）|

副标文案与 [demo `viewNames`](../../demo_mobile_full_v1.html) 完全对齐。

---

## 4. `<Sparkline>` 设计

### 4.1 选型

不引入新图表库。两选择：
- **A.** 复用 [`<ChartPanel>`](../../stock_trading_system/web/frontend/src/components/shared/ChartPanel.tsx)（ECharts），option 极简化（无坐标轴、无 tooltip）
- **B.** 纯 SVG sparkline（~50 LOC，0 依赖）

**推荐 B**——sparkline 只画一条 path，ECharts 配置 + 异步加载 chunk 反而是 overkill。

### 4.2 实现（[`components/shared/Sparkline.tsx`](../../stock_trading_system/web/frontend/src/components/shared/Sparkline.tsx)）

```tsx
import { useMemo } from "react"

interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  positive?: boolean       // true=green, false=red, undefined=auto from first vs last
  className?: string
}

export function Sparkline({
  values, width = 320, height = 40, positive, className,
}: SparklineProps) {
  const path = useMemo(() => {
    if (values.length < 2) return null
    const min = Math.min(...values)
    const max = Math.max(...values)
    const range = max - min || 1
    const stepX = width / (values.length - 1)
    return values.map((v, i) => {
      const x = i * stepX
      const y = height - ((v - min) / range) * height
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
    }).join(" ")
  }, [values, width, height])

  if (!path) return null

  const isUp = positive ?? (values[values.length - 1] >= values[0])
  const stroke = isUp ? "var(--color-accent-green)" : "var(--color-accent-red)"
  const fill = isUp
    ? "color-mix(in srgb, var(--color-accent-green) 16%, transparent)"
    : "color-mix(in srgb, var(--color-accent-red) 16%, transparent)"

  // close the path back to baseline so we can fill under it
  const lastX = width
  const fillPath = `${path} L${lastX},${height} L0,${height} Z`

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      preserveAspectRatio="none"
      style={{ width: "100%", height }}
      aria-hidden="true"
    >
      <path d={fillPath} fill={fill} />
      <path d={path} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}
```

**关键属性**：
- `preserveAspectRatio="none"` —— 让 svg 跟随容器宽度自适应
- `width:100%` —— 充满父级
- 数据点 < 2 直接返回 null（数据不足降级）
- `aria-hidden="true"` —— 装饰性不进入屏幕阅读器

---

## 5. `<AccountOverviewCard>` 升级

### 5.1 Hero 容器

```tsx
<Card className="bg-card/95 ring-1 ring-primary/10 shadow-sm">
  <CardContent className="pt-5 pb-4 px-4 space-y-3">
    {/* 第 1 段:账户总值 + 今日 PnL —— 现状不动 */}
    <div className="flex items-start justify-between gap-3 min-w-0">
      ...
    </div>

    {/* 第 2 段:mini sparkline(新增,数据不足时不渲染)*/}
    {sparklineValues.length >= 5 && (
      <div className="-mx-2">
        <Sparkline values={sparklineValues} height={44} />
      </div>
    )}

    {/* 第 3 段:三栏 metric —— 现状不动 */}
    <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border/40">
      <Metric .../>
      <Metric .../>
      <Metric .../>
    </div>
  </CardContent>
</Card>
```

**视觉差异化**（hero）：
- `bg-card/95` —— 比常规 Card `bg-card` 略深或同色（具体看 token，关键是要有差异）
- `ring-1 ring-primary/10` —— 微亮边框（hero 区分）
- `shadow-sm` —— 增加视觉抬升

### 5.2 Sparkline 数据传递

`<DashboardPage>` 已有 `data.history[]`（净值快照），传入：

```tsx
const sparklineValues = useMemo(
  () => (data?.history ?? []).map(h => h.total_value).filter(v => Number.isFinite(v)),
  [data?.history],
)

<AccountOverviewCard
  pnl={pnl}
  summary={summary}
  alertsCount={data?.alerts_count ?? 0}
  sparklineValues={sparklineValues}
/>
```

`<AccountOverviewCard>` props 加 `sparklineValues: number[]`。

### 5.3 数据不足降级（R-MUI-20a）

```tsx
{sparklineValues.length >= 5 && (
  <div className="-mx-2">
    <Sparkline values={sparklineValues} height={44} />
  </div>
)}
```

- 数据点 < 5 → 不渲染（避免拉伸怪异）
- 不显示空状态占位（直接退化两段布局）

阈值 5 是经验值：少于 5 个点的 sparkline 信息密度太低，不如不画。

### 5.4 Sparkline 颜色与 PnL 一致

```tsx
const isUp = pnl.total_pnl >= 0
<Sparkline values={sparklineValues} positive={isUp} height={44} />
```

让 sparkline 颜色（绿/红）与账户 PnL 方向对齐，视觉一致。

---

## 6. 测试

### 6.1 Vitest

`__tests__/MobileTopbar.test.tsx`（4 case）：
1. 渲染品牌 `⚡ StockAI Terminal`
2. 传 `pageTitle="首页"` → 副标可见
3. 不传 pageTitle → 副标不渲染
4. LLMSwitcher 子组件被挂载（mock 检查）

`__tests__/Sparkline.test.tsx`（5 case）：
1. values < 2 → 返回 null
2. values 5 个 → 渲染 svg + 2 个 path（fill + stroke）
3. positive=true → stroke 含 `--color-accent-green`
4. positive=false → stroke 含 `--color-accent-red`
5. positive 不传 → 自动从首尾推断方向

`__tests__/AccountOverviewCard.test.tsx`（3 case，扩展现有）：
1. sparklineValues >= 5 → Sparkline 渲染
2. sparklineValues < 5 → Sparkline 不渲染（卡退化两段）
3. hero 容器有 `ring-1 ring-primary/10` className

### 6.2 Playwright（与 v1.3 同套）

12 页面 × 4 viewport 回归保留；额外加：
- 移动端任意页面顶栏可见 `StockAI Terminal` + LLMSwitcher
- 点 LLMSwitcher chip 弹出菜单（与桌面行为对齐）
- 375px viewport 首屏可见 sparkline（DOM 测试 `getByLabelText` 或类名定位）

### 6.3 手动回归

- iPhone SE 2 / 14 / 14 Pro Max / Pixel 7 五机型
- 切换 5 个一级 tab 顶栏副标实时变化
- 切换 LLM provider/preset 在移动端可用
- 数据稀疏（新用户首日）账户卡退化两段不破布局
- 桌面端 ≥md 顶栏不显示，无视觉变化

---

## 6.5 布局顺序调整（R-MUI-22 / R-MUI-23）

### 6.5.1 现状

**Analysis 页**（[`AnalysisPage.tsx:486+`](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)）当前顺序：
```
<AnalysisHomeInbox>
  <Card>分析记录 Inbox</Card>      ← 在上(line 486)
  <Card>发起分析</Card>             ← 在下(line 541)
```

**Screener-v3 页**（[`ScreenerV3Page.tsx:69-73`](../../stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx)）当前顺序：
```tsx
function ScreenerHomeView({ prefillId }) {
  return (
    <RecentScreensCard />          ← 在上(line 72)
    <ScreenerForm ... />           ← 在下(line 73)
  )
}
```

### 6.5.2 修法（仅 JSX 顺序交换）

**Analysis 页**：在 `<AnalysisHomeInbox>` 内把两个 `<Card>` 顺序对调——`发起分析` 卡放第一个、`分析记录 Inbox` 卡放第二个。section title 顺序同步对调。

**Screener-v3 页**：在 `ScreenerHomeView` JSX return 里把 `<RecentScreensCard />` 与 `<ScreenerForm prefillTaskId={prefillId} />` 顺序对调——`<ScreenerForm>` 在前、`<RecentScreensCard>` 在后。

### 6.5.3 不动

- `<RunningRow>` / `<CompletedRow>` 内部渲染
- `<RecentScreenCard>` 内部渲染
- 表单字段、提交逻辑、prefill 流程
- Tasks 列表（不在本期范围）
- 桌面端布局也跟着改（保持桌面与移动同序）

### 6.5.4 测试

`tests/frontend/analysis/AnalysisPage.layout.test.tsx`（2 case）：
- DOM 顺序断言 `getByText("发起分析")` 在 `getByText("分析记录")` 前
- 提交分析后乐观插入仍在 Inbox 顶部（行为不变）

`tests/frontend/screener-v3/ScreenerV3Page.layout.test.tsx`（2 case）：
- DOM 顺序断言 `<ScreenerForm>` 在 `<RecentScreensCard>` 前
- prefill 模式 banner 在 form 内（位置随 form 上移）

---

## 6.6 系统设置 admin 门 + 独立账号页（R-MUI-26..30）

### 6.6.1 Sidebar 改造（[`Sidebar.tsx`](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx)）

**桌面 NAV_GROUPS**（line 25）—— "系统" 组内 "设置" 项加 `adminOnly: true` flag，渲染时 `getCurrentUser()?.role !== "admin"` 过滤掉：

```tsx
interface NavItem {
  label: string
  href: string
  icon: React.ReactNode
  adminOnly?: boolean          // ← 新增
}

// 在 NAV_GROUPS 内:
{ label: "设置", href: "/settings", icon: <Settings className="w-4 h-4" />, adminOnly: true },

// 桌面 <Sidebar> 渲染处:
{group.items
  .filter(item => !item.adminOnly || isAdminUser)
  .map(item => <SidebarLink key={item.href} item={item} active={isActive(item.href)} />)}
```

`isAdminUser` 由组件顶部 `const isAdminUser = getCurrentUser()?.role === "admin"` 计算。

**移动 MOBILE_MORE**（line 152-160）同样加 `adminOnly`：
```tsx
const MOBILE_MORE: MoreEntry[] = [
  ...,
  { label: "系统设置", description: "模型与通知", href: "/settings", icon: <Settings />, adminOnly: true },
  { label: "账号",     description: "当前用户 / 退出登录", href: "/account", icon: <UserCircle /> }, // ← href 改 /account
]

// MoreSheet 渲染处过滤:
{MOBILE_MORE.filter(e => !e.adminOnly || isAdminUser).map(...)}
```

### 6.6.2 新建独立 `/account` 路由

**Flask 视图**（[`web/app.py`](../../stock_trading_system/web/app.py)）：
```python
@app.route("/account")
@login_required
def account_page():
    return render_template(
        "islands/account.html",
        vite_assets=vite_assets,
    )
```

**Jinja 模板** [`web/templates/islands/account.html`](../../stock_trading_system/web/templates/islands/account.html)（仿现有 island 模板）:
```jinja
{% extends "layout.html" %}
{% block title %}账号 · StockAI Terminal{% endblock %}
{% block content %}
<div id="account-root"></div>
{% endblock %}
{% block scripts %}
{{ vite_assets("src/islands/account/main.tsx") | safe }}
{% endblock %}
```

**Vite entry** [`src/islands/account/main.tsx`](../../stock_trading_system/web/frontend/src/islands/account/main.tsx)：
```tsx
import { createRoot } from "react-dom/client"
import { AppShell } from "@/components/shared/AppShell"
import { AccountPage } from "./AccountPage"
import "@/styles/index.css"

createRoot(document.getElementById("account-root")!).render(
  <AppShell pageTitle="账号">
    <AccountPage />
  </AppShell>
)
```

**Vite config** (`vite.config.ts`) 加入新 input。

### 6.6.3 `<AccountPage>` 组件

[`src/islands/account/AccountPage.tsx`](../../stock_trading_system/web/frontend/src/islands/account/AccountPage.tsx)：

```tsx
import { useState } from "react"
import { LogOut, UserCircle, Mail, Shield } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { toast } from "@/components/ui/toaster"
import { apiPost } from "@/lib/api"
import { getCurrentUser } from "@/lib/auth"

export function AccountPage() {
  const user = getCurrentUser()
  const [busy, setBusy] = useState(false)

  async function onLogout() {
    if (!confirm("确认退出登录?")) return
    setBusy(true)
    try {
      await apiPost("/api/auth/logout", {})
      window.location.href = "/login"
    } catch {
      toast.error("退出失败,请重试")
      setBusy(false)
    }
  }

  if (!user) {
    return (
      <div className="p-4 md:p-6 max-w-md mx-auto">
        <p className="text-center text-muted-foreground py-8">未登录</p>
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-md mx-auto space-y-4">
      <Card>
        <CardContent className="pt-5 space-y-3">
          <div className="flex items-center gap-3 pb-3 border-b border-border">
            <div className="w-12 h-12 rounded-full bg-primary/10 grid place-items-center shrink-0">
              <UserCircle className="w-7 h-7 text-primary" />
            </div>
            <div className="min-w-0">
              <div className="font-semibold truncate">{user.displayName}</div>
              <Badge variant={user.role === "admin" ? "default" : "secondary"}
                     className="mt-0.5 text-[10px]">
                {user.role === "admin" ? "管理员" : "用户"}
              </Badge>
            </div>
          </div>

          <Row icon={<Mail className="w-4 h-4" />} label="账号 ID" value={`#${user.id}`} />
          <Row icon={<Shield className="w-4 h-4" />} label="角色" value={user.role} />
          <Row icon={<UserCircle className="w-4 h-4" />} label="显示名" value={user.displayName} />
        </CardContent>
      </Card>

      <Button
        variant="destructive"
        className="w-full"
        onClick={onLogout}
        disabled={busy}
      >
        <LogOut className="w-4 h-4 mr-2" />
        {busy ? "退出中..." : "退出登录"}
      </Button>
    </div>
  )
}

function Row({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">{icon}</span>
      <span className="text-muted-foreground">{label}</span>
      <span className="ml-auto font-mono text-xs">{value}</span>
    </div>
  )
}
```

**关键约束**：
- **只渲染** 用户信息卡 + 退出按钮，**无其他链接 / 入口**（用户明确要求"只有退出登录的功能"）。
- 显示名 / 角色 / ID 来自 `getCurrentUser()`（meta 标签，server-rendered，无额外请求）。
- email 字段 v1.0 不显示（getCurrentUser 当前只返 id/displayName/role，加 email 需改 [`layout.html`](../../stock_trading_system/web/templates/layout.html) 注入 `<meta name="user-email">`+ auth.ts —— 可在 v1.3.3 加，不是 P0）。

### 6.6.4 后端 `/settings` admin 门

[`/settings`](../../stock_trading_system/web/app.py) 视图加 admin 守卫：

```python
@app.route("/settings")
@login_required
def settings_page():
    if g.user is None or g.user.role != "admin":
        # 非 admin 重定向到 /account(用户期望的"账号"页)
        return redirect("/account")
    return render_template("islands/settings.html", vite_assets=vite_assets)
```

同时 `/api/settings`（GET/POST）端点也要加 admin 门——目前 `/api/settings` 在 [`web/app.py:2177`](../../stock_trading_system/web/app.py) 暴露 LLM API key 配置等管理面板数据，对非 admin 必须 403：

```python
@app.route("/api/settings")
def api_settings():
    if g.user is None:
        return jsonify({"error": "unauthorized"}), 401
    if g.user.role != "admin":
        return jsonify({"error": "forbidden", "reason": "admin_only"}), 403
    # ... 现有逻辑
```

同样 admin 门加到 `/api/settings/llm-provider`、`/api/settings/openrouter/active`、`/api/diagnostics/providers` 等管理类端点。

### 6.6.5 严格不动

- [`SettingsPage.tsx`](../../stock_trading_system/web/frontend/src/islands/settings/SettingsPage.tsx) 组件本身（admin 见到的内容不变）
- LoginMethodsSection（OAuth 绑定 v1.0 暂留在 settings 内，R-MUI-31 标注未来再议）
- `/api/auth/logout` 接口
- 现有 admin 用户的工作流（admin 仍能从侧栏看到设置）
- 普通用户的所有非 settings 流程（持仓 / 分析 / 选股 / 纸面 / 报告 / 回测 / 任务 / 预警 / OAuth 登录）

### 6.6.6 测试

后端 [`tests/web/test_settings_admin_gate.py`](../../tests/web/test_settings_admin_gate.py) 4 case：
1. 未登录 GET `/settings` → 302 `/login`
2. alice (user) GET `/settings` → 302 `/account`
3. admin GET `/settings` → 200 + 渲染 settings island
4. alice GET `/api/settings` → 403 reason=`admin_only`

前端 vitest [`__tests__/account.test.tsx`](stock_trading_system/web/frontend/src/islands/account/__tests__/account.test.tsx) 3 case：
1. 渲染用户信息（displayName / role / id）
2. 点退出 → confirm → POST `/api/auth/logout` → location.href = `/login`
3. confirm 取消 → 不调 API

前端 vitest [`__tests__/Sidebar.role-gate.test.tsx`](stock_trading_system/web/frontend/src/components/shared/__tests__/Sidebar.role-gate.test.tsx) 3 case：
1. user role → MOBILE_MORE 不含 "系统设置"
2. user role → 桌面 NAV_GROUPS 不含 "设置"
3. admin role → 两处都含

### 6.6.7 实施时长

约 **+1.5h 实装 ~180 LOC**：
- Sidebar adminOnly filter ~20 / 后端 admin 门 4 处 ~30 / Jinja 模板 + Vite input ~30 / AccountPage 组件 ~60 / 测试 4 文件 ~40

---

## 7. 实施顺序

| 步骤 | 工作 | 文件 | LOC |
|---|---|---|---|
| 1 | `<Sparkline>` + 单测 | `components/shared/Sparkline.tsx`, tests | ~80 |
| 2 | `<MobileTopbar>` + 单测 | `components/shared/MobileTopbar.tsx`, tests | ~80 |
| 3 | `<AppShell>` 加 `pageTitle` prop + 集成 MobileTopbar | `components/shared/AppShell.tsx` | ~15 |
| 4 | 11 个 island main entry 加 `pageTitle` | `islands/*/main.tsx` | ~30 |
| 5 | `<AccountOverviewCard>` 加 sparkline + hero className + props 扩展 + 单测 | `islands/dashboard/DashboardPage.tsx`, tests | ~40 |
| 6 | Analysis 页 `<AnalysisHomeInbox>` JSX 顺序对调（发起分析 → 分析记录） | `islands/analysis/AnalysisPage.tsx` | ~10 |
| 7 | Screener-v3 `<ScreenerHomeView>` JSX 顺序对调（form → recent） | `islands/screener-v3/ScreenerV3Page.tsx` | ~5 |
| 8 | 2 个 layout DOM 顺序单测 | tests | ~40 |
| 9 | Playwright 回归 + 手动回归 | — | — |
| **合计** | | | **~300 LOC** |

每步独立 commit。预估总工时 **~4h**。

---

## 8. 严格不动清单

- [`<LLMSwitcher>`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) 实现（仅消费）
- 桌面 `<Sidebar>` 视觉
- 桌面 `lg:grid-cols-3` 净值曲线独立 Card
- 后端 API / 数据 schema / task type
- v1.3 已落地的 R-MUI-01..18 所有改动
- shadcn UI primitives
- TradingAgents / 数据层 / LLM / business logic

---

## 9. 风险

| 风险 | 影响 | 处理 |
|---|---|---|
| 顶栏 + 底部 tabbar 双 fixed 挤压 | 内容遮挡 | `<main>` 已有 `pb-16`，顶栏 sticky 不需额外 padding（sticky 占位不像 fixed） |
| LLMSwitcher 在窄屏顶栏溢出 | 视觉破 | LLMSwitcher 已是 chip 形态 + truncate；副标超长时 max-w-[200px] truncate |
| sparkline 在数据稀疏时拉伸 | 视觉差 | 阈值 5 个点起渲染 |
| 桌面端误显示移动顶栏 | 视觉冲突 | `md:hidden` 严格隔离，桌面端 0 视觉变化 |
| 副标文案散在 11 个 island | 维护成本 | 文案集中在各 island main.tsx，与路由就近；未来如增多可改 context 集中 |
| pageTitle prop 漏传 | 副标不显示但不报错 | 设计为可选 prop，缺失时仅品牌名（不破布局）|

---

*v1.3.1 设计稿 — 等待确认后开始实施*
