# 技术方案：UI React Island —— Flask + React 岛屿协作

| 项 | 值 |
|---|---|
| Feature | `ui-react-island` |
| 版本 | v1.0 |
| 日期 | 2026-04-21 |
| 关联 PRD | [../prd/ui-react-island.md](../prd/ui-react-island.md) |
| 关联测试用例 | [../test-cases/ui-react-island.md](../test-cases/ui-react-island.md) |
| POC | `/tmp/stock-ui-demo/`（已验证，4 页 + 14 组件 Gallery）|

## 1. 目标

见 [PRD §2](../prd/ui-react-island.md#2-目标)。一句话：**Flask 不改、SocketIO 不改、数据库不改，只把 4 个高价值页面的前端替换为 React + shadcn，简单页保留 Jinja**。

## 2. 选型

### 2.1 选型决策

已在 POC 中验证：

| 技术 | 版本 | 决策 |
|---|---|---|
| **React** | 19.2 | 最新稳定；服务端由 Flask 代劳，只需 CSR |
| **Vite** | 8.0 | 200ms 级构建，HMR < 500ms；原生 React 支持 |
| **TypeScript** | 6.x（现 Vite 默认）| strict mode；类型覆盖所有迁移代码 |
| **Tailwind CSS** | v4（`@tailwindcss/vite` 插件）| 原生 CSS vars + `@theme`；零配置文件 |
| **shadcn/ui 风格** | — | 组件源码进仓库，非运行时依赖 |
| **Radix UI** | 最新 | 底层 headless primitives；a11y 开箱 |
| **cmdk** | 最新 | ⌘K 命令面板 |
| **sonner** | 最新 | Toast 系统 |
| **lucide-react** | 最新 | 图标 |
| **class-variance-authority + tailwind-merge + clsx** | 最新 | 变体系统 |

### 2.2 不选的理由

- ~~Next.js / Remix~~：SSR 需 Node 服务端，和 Flask 架构冲突
- ~~MUI / Ant Design~~：运行时 CSS-in-JS，bundle 大且难深度改样式
- ~~Bulma / DaisyUI（纯 CSS）~~：无 JS 组件能力，复杂交互仍需手写
- ~~Web Components（Shoelace）~~：生态不如 React 丰富，未来扩展有限

## 3. 架构概览

```
┌─────────────── 浏览器 ───────────────┐
│                                        │
│  /login            /screener-v3        │
│  (Jinja HTML)      (Jinja + React)     │
│  简单表单            React root div     │
│  旧 style.css       + island JS bundle │
│                                        │
└─────────────────┬──────────────────────┘
                  │
                  ▼
┌─────────────── Flask :5000 ──────────────────┐
│                                              │
│  @app.route("/screener-v3")                  │
│  def screener_v3():                          │
│      return render_template(                 │
│        "islands/screener_v3.html",           │
│        manifest=load_vite_manifest(),        │
│      )                                       │
│                                              │
│  @app.route("/api/*") ...                    │
│  @socketio.on(...) ...                       │
│                                              │
└──────────────────────────────────────────────┘
                  │
                  ▼
┌─────────── Vite Build Output ──────────────┐
│                                            │
│  stock_trading_system/web/static/dist/     │
│    .vite/manifest.json  ← 入口清单          │
│    assets/screener-v3-[hash].js            │
│    assets/paper-trade-[hash].js            │
│    assets/dashboard-[hash].js              │
│    assets/tasks-[hash].js                  │
│    assets/vendor-[hash].js     ← 共享 chunk │
│    assets/ui-[hash].js         ← shadcn    │
│    assets/index-[hash].css                 │
│                                            │
└────────────────────────────────────────────┘
```

**关键设计**：
- **Flask 仍是路由总线**，每个 island 有独立 Flask 路由 + Jinja 模板壳
- Jinja 模板只负责 **注入正确的 hashed JS/CSS + meta 信息**（CSRF、user、provider）
- React 不做路由，岛屿间导航走 Flask `<a href>` 或 `window.location`
- 数据获取走 既有 `/api/*` REST + SocketIO（复用 [unified-progress](./unified-progress.md) 约束）

## 4. 目录结构

```
stock_trading_system/web/
├── templates/
│   ├── index.html                     # 旧 SPA 模板（保留，不动）
│   ├── layout.html (NEW)              # 共享 layout（nav + meta）
│   └── islands/                       # 新：每 island 的 Jinja 壳
│       ├── screener_v3.html
│       ├── paper_trade_detail.html
│       ├── dashboard.html
│       └── tasks.html
├── static/
│   ├── css/style.css                  # 保留，旧页面继续用
│   ├── js/app.js                      # 保留，旧页面继续用
│   └── dist/                          # Vite 产出（gitignored，CI 构建）
│       ├── .vite/manifest.json
│       └── assets/
└── frontend/                          # NEW：React 源码根目录
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html                     # Vite dev 入口（仅 dev 用）
    └── src/
        ├── islands/                   # 每个 island 一个 entry
        │   ├── screener-v3/
        │   │   ├── main.tsx
        │   │   └── ScreenerV3Page.tsx
        │   ├── paper-trade/
        │   │   ├── main.tsx
        │   │   └── PaperTradePage.tsx
        │   ├── dashboard/
        │   │   ├── main.tsx
        │   │   └── DashboardPage.tsx
        │   └── tasks/
        │       ├── main.tsx
        │       └── TasksPage.tsx
        ├── components/
        │   ├── ui/                    # shadcn 原子组件（从 POC 迁入）
        │   │   ├── button.tsx
        │   │   ├── card.tsx
        │   │   ├── dialog.tsx
        │   │   ├── dropdown-menu.tsx
        │   │   ├── command.tsx
        │   │   ├── ...14 个
        │   └── shared/                # 业务组件
        │       ├── ProgressStream.tsx
        │       ├── GuruSelector.tsx
        │       ├── TierList.tsx
        │       └── ...
        ├── lib/
        │   ├── api.ts                 # fetch 封装 + CSRF + 错误处理
        │   ├── socket.ts              # SocketIO 封装 + catch-up
        │   ├── auth.ts                # current_user 读取
        │   ├── utils.ts               # cn() + formatters
        │   └── types.ts               # 共享 API 类型
        ├── data/
        │   └── gurus.ts               # 14 大师静态数据
        └── styles/
            └── index.css              # Tailwind v4 + design tokens
```

**保留不动**：`templates/index.html` / `static/css/style.css` / `static/js/app.js` —— 旧页面继续工作。

**新增**：`web/frontend/` 目录完全独立。

## 5. Vite ↔ Flask 协作管道

### 5.1 Dev 模式（开发时两个进程并行）

```
Terminal 1: cd stock_trading_system/web/frontend && npm run dev
            → Vite dev server on :5173

Terminal 2: flask --app stock_trading_system run
            → Flask on :5000
```

**Flask 端如何引用 Vite dev 资源**：

```python
# stock_trading_system/web/vite_helpers.py (NEW)
import os
import json
from pathlib import Path

VITE_DEV = os.environ.get("FLASK_ENV") == "development"
VITE_DEV_URL = "http://localhost:5173"
DIST_DIR = Path(__file__).parent / "static" / "dist"
MANIFEST_PATH = DIST_DIR / ".vite" / "manifest.json"


def vite_assets(entry: str) -> dict:
    """Return {'js': [...], 'css': [...]} URLs for a given entry.

    entry examples: 'src/islands/screener-v3/main.tsx'
    """
    if VITE_DEV:
        return {
            "js": [
                f"{VITE_DEV_URL}/@vite/client",
                f"{VITE_DEV_URL}/{entry}",
            ],
            "css": [],
            "dev": True,
        }

    # Prod: read manifest
    manifest = json.loads(MANIFEST_PATH.read_text())
    item = manifest[entry]
    result = {"js": [f"/static/dist/{item['file']}"], "css": [], "dev": False}
    for css in item.get("css", []):
        result["css"].append(f"/static/dist/{css}")
    # Imports (chunk split)
    for imp in item.get("imports", []):
        if imp in manifest:
            result["js"].insert(0, f"/static/dist/{manifest[imp]['file']}")
    return result
```

**Jinja 模板壳**（共用 `layout.html`）：

```jinja
{# stock_trading_system/web/templates/layout.html #}
<!doctype html>
<html lang="zh-CN" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <meta name="user-id" content="{{ g.user.id if g.user else '' }}">
  <meta name="user-display" content="{{ g.user.display_name if g.user else '' }}">
  <title>{% block title %}StockAI Terminal{% endblock %}</title>

  {# Vite dev client or prod CSS #}
  {% set assets = vite_assets(entry) %}
  {% for css in assets.css %}
    <link rel="stylesheet" href="{{ css }}">
  {% endfor %}
</head>
<body>
  <div id="react-root"></div>

  {% for js in assets.js %}
    <script type="module" src="{{ js }}"></script>
  {% endfor %}
</body>
</html>
```

**每 island 的模板**：

```jinja
{# stock_trading_system/web/templates/islands/screener_v3.html #}
{% extends "layout.html" %}
{% set entry = "src/islands/screener-v3/main.tsx" %}
{% block title %}智能选股 V3 · StockAI Terminal{% endblock %}
```

**React entry**：

```tsx
// stock_trading_system/web/frontend/src/islands/screener-v3/main.tsx
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { ScreenerV3Page } from "./ScreenerV3Page"

document.documentElement.classList.add("dark")

createRoot(document.getElementById("react-root")!).render(
  <StrictMode>
    <ScreenerV3Page />
  </StrictMode>,
)
```

### 5.2 Vite 配置（支持多 island）

```ts
// stock_trading_system/web/frontend/vite.config.ts
import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const DIST = path.resolve(__dirname, "../static/dist")

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    strictPort: true,
    cors: true,
    origin: "http://localhost:5173",  // 让资源用绝对 URL
  },
  build: {
    outDir: DIST,
    emptyOutDir: true,
    manifest: true,                    // 产出 .vite/manifest.json
    rollupOptions: {
      input: {
        "screener-v3":  "src/islands/screener-v3/main.tsx",
        "paper-trade":  "src/islands/paper-trade/main.tsx",
        "dashboard":    "src/islands/dashboard/main.tsx",
        "tasks":        "src/islands/tasks/main.tsx",
      },
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom"],
          "radix": [
            "@radix-ui/react-dialog",
            "@radix-ui/react-dropdown-menu",
            "@radix-ui/react-popover",
            "@radix-ui/react-select",
            "@radix-ui/react-tabs",
            "@radix-ui/react-tooltip",
            // ... 其他
          ],
          "ui": [/src\/components\/ui/],
        },
      },
    },
  },
})
```

**manual chunks 策略**：
- `react-vendor`（~40KB gzipped）—— react + react-dom，几乎不变
- `radix`（~30KB）—— 所有用到的 Radix primitives
- `ui`（~15KB）—— shadcn 组件层
- 每 island（~20-50KB）—— 自己的业务代码

4 岛同时加载的极端场景也 ≤ 160KB gzipped，单页 ≤ 130KB。符合 [PRD §6.1](../prd/ui-react-island.md#61-性能) 的 180KB 预算。

### 5.3 Prod 部署（Railway）

改 `Procfile`：

```
web: bash -lc "cd stock_trading_system/web/frontend && npm install && npm run build && cd /app && gunicorn ..."
```

或用 `railway.json`（推荐，已有）增加 build command：

```json
{
  "build": {
    "builder": "nixpacks",
    "buildCommand": "cd stock_trading_system/web/frontend && npm install && npm run build"
  },
  "deploy": {
    "startCommand": "gunicorn -k gevent -w 1 --timeout 120 stock_trading_system.web.app:create_app()"
  }
}
```

**Node 层加入 Nixpacks**：
- Railway nixpacks 默认检测 python。需要在 repo 根加 `.nixpacks/environment.toml`：

```toml
[phases.setup]
nixPkgs = ["python311", "nodejs-18_x", "npm"]
```

### 5.4 部署体积

| 产物 | 预估 |
|---|---|
| `static/dist/` 总体积 | ~600KB 未压缩（~180KB gzipped） |
| 4 个 manifest entry | 每 entry ~50-150KB |
| Railway build 新增时间 | +30-60s（npm install 缓存后） |

## 6. 共享基础设施

### 6.1 `lib/api.ts` —— fetch 封装

```ts
// frontend/src/lib/api.ts

const CSRF = () =>
  document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')?.content ?? ""

export interface ApiOptions extends RequestInit {
  json?: unknown
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { json, headers, ...rest } = opts
  const init: RequestInit = {
    credentials: "same-origin",
    headers: {
      "Accept": "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(rest.method && rest.method !== "GET" ? { "X-CSRFToken": CSRF() } : {}),
      ...(headers as Record<string, string>),
    },
    ...(json !== undefined ? { body: JSON.stringify(json) } : {}),
    ...rest,
  }
  const res = await fetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body, body.message ?? res.statusText)
  }
  return res.json()
}

// 语法糖
export const apiGet  = <T>(path: string, opts?: ApiOptions) => api<T>(path, { ...opts, method: "GET" })
export const apiPost = <T>(path: string, json?: unknown, opts?: ApiOptions) => api<T>(path, { ...opts, method: "POST", json })
export const apiDel  = <T>(path: string, opts?: ApiOptions) => api<T>(path, { ...opts, method: "DELETE" })
```

### 6.2 `lib/socket.ts` —— SocketIO 封装

遵循 [unified-progress §4](./unified-progress.md#4-后端改造5-步) 的 envelope schema：

```ts
// frontend/src/lib/socket.ts
import { io, Socket } from "socket.io-client"

let socketInstance: Socket | null = null

export interface TaskEventEnvelope<P = unknown> {
  task_id: string
  user_id: number
  seq: number
  event: string
  payload: P
  emitted_at: string
}

export function getSocket(): Socket {
  if (!socketInstance) {
    socketInstance = io({ transports: ["websocket", "polling"] })
  }
  return socketInstance
}

export interface StreamOptions {
  taskIds: string[]
  onEvent: (env: TaskEventEnvelope) => void
  onStatusChange?: (s: "connecting" | "streaming" | "disconnected") => void
}

export function subscribeTaskStream(opts: StreamOptions) {
  const s = getSocket()
  const taskIds = new Set(opts.taskIds)
  const lastSeq = new Map<string, number>()

  const applyEnvelope = (env: TaskEventEnvelope) => {
    if (!taskIds.has(env.task_id)) return
    const last = lastSeq.get(env.task_id) ?? 0
    if (env.seq <= last) return
    lastSeq.set(env.task_id, env.seq)
    opts.onEvent(env)
  }

  const onConnect = async () => {
    opts.onStatusChange?.("streaming")
    // Catch-up per task (unified-progress §4.4)
    for (const tid of taskIds) {
      const since = lastSeq.get(tid) ?? 0
      const events = await fetch(`/api/tasks/events?task_id=${tid}&since=${since}`)
        .then(r => r.json()) as TaskEventEnvelope[]
      events.forEach(applyEnvelope)
    }
  }

  s.on("connect", onConnect)
  s.on("disconnect", () => opts.onStatusChange?.("disconnected"))
  s.onAny((event, env) => applyEnvelope({ ...env, event }))

  if (s.connected) onConnect()
  else opts.onStatusChange?.("connecting")

  return {
    subscribe:   (id: string) => { taskIds.add(id); onConnect() },
    unsubscribe: (id: string) => { taskIds.delete(id); lastSeq.delete(id) },
    destroy:     () => { s.off("connect", onConnect) },
  }
}
```

### 6.3 `lib/auth.ts` —— 当前用户

```ts
// frontend/src/lib/auth.ts
export interface CurrentUser {
  id: number
  displayName: string
}

export function getCurrentUser(): CurrentUser | null {
  const id = document.querySelector<HTMLMetaElement>('meta[name="user-id"]')?.content
  const displayName = document.querySelector<HTMLMetaElement>('meta[name="user-display"]')?.content
  if (!id || !displayName) return null
  return { id: parseInt(id, 10), displayName }
}
```

### 6.4 ProgressStream 组件（承接 [unified-progress](./unified-progress.md)）

```tsx
// frontend/src/components/shared/ProgressStream.tsx
import { useEffect, useState } from "react"
import { subscribeTaskStream, TaskEventEnvelope } from "@/lib/socket"
// ...

interface Props {
  taskIds: string[]
  layout: "compact" | "detail" | "inline-badge"
  onComplete?: (taskId: string) => void
}

export function ProgressStream({ taskIds, layout, onComplete }: Props) {
  const [events, setEvents] = useState<TaskEventEnvelope[]>([])
  const [status, setStatus] = useState<"connecting"|"streaming"|"disconnected">("connecting")

  useEffect(() => {
    const sub = subscribeTaskStream({
      taskIds,
      onEvent: (env) => {
        setEvents(prev => [...prev, env])
        if (env.event === "task_completed") onComplete?.(env.task_id)
      },
      onStatusChange: setStatus,
    })
    return () => sub.destroy()
  }, [taskIds.join(",")])

  // 三种布局渲染：compact | detail | inline-badge
  return <ProgressStreamView layout={layout} events={events} status={status} />
}
```

**对齐** [unified-progress §5](./unified-progress.md#5-前端改造) 的 React 实现。

## 7. 4 岛屿实施细节

### 7.1 `/screener-v3` Island

**Flask 路由**：

```python
# stock_trading_system/web/app.py
@app.route("/screener-v3")
@login_required
def screener_v3_page():
    return render_template("islands/screener_v3.html")
```

**React 组件**（移植 POC `ScreenerV3Demo.tsx`）：

```tsx
// islands/screener-v3/ScreenerV3Page.tsx
import { useEffect, useState } from "react"
import { apiGet, apiPost } from "@/lib/api"
import { GuruSelector } from "@/components/shared/GuruSelector"
// ...

export function ScreenerV3Page() {
  const [gurus, setGurus] = useState<Guru[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set(["buffett","graham","munger","lynch"]))
  const [mode, setMode] = useState<Mode>("agent")
  const [candidateN, setCandidateN] = useState(20)
  const [nl, setNl] = useState("")
  const [estimate, setEstimate] = useState<Estimate | null>(null)

  // 拉大师列表（来自 /api/screen/v3/gurus）
  useEffect(() => {
    apiGet<Guru[]>("/api/screen/v3/gurus").then(setGurus)
  }, [])

  // debounce 预估
  useEffect(() => {
    const t = setTimeout(async () => {
      if (mode === "classic") { setEstimate(null); return }
      const est = await apiPost<Estimate>("/api/screen/v3/estimate", {
        nl_query: nl, market: "US", candidate_n: candidateN,
        gurus: [...selected], mode, with_roundtable: mode === "agent_rt",
      })
      setEstimate(est)
    }, 500)
    return () => clearTimeout(t)
  }, [nl, candidateN, selected.size, mode])

  const onStart = async () => {
    const { task_id } = await apiPost<{ task_id: string }>("/api/screen/v3/trigger", {
      nl_query: nl, market: "US", candidate_n: candidateN,
      gurus: [...selected], mode, with_roundtable: mode === "agent_rt",
    })
    window.location.href = `/tasks/${task_id}`
  }

  return (
    <AppShell>
      {/* 完整 UI 照搬 POC ScreenerV3Demo 结构 */}
    </AppShell>
  )
}
```

**工作量**：复用 POC 90% 代码 + 接 API = ~6h

### 7.2 `/tasks` Island（集成 unified-progress）

**Flask 路由**：

```python
@app.route("/tasks")
@login_required
def tasks_page():
    return render_template("islands/tasks.html")

@app.route("/tasks/<task_id>")
@login_required
def task_detail_page(task_id):
    return render_template("islands/tasks.html")  # 同一 entry，内部根据 URL 判断
```

**React 组件**：

```tsx
// islands/tasks/TasksPage.tsx
import { useEffect, useState } from "react"
import { apiGet } from "@/lib/api"
import { ProgressStream } from "@/components/shared/ProgressStream"
// ...

export function TasksPage() {
  const taskId = window.location.pathname.split("/")[2] // /tasks/<id>
  const [tasks, setTasks] = useState<Task[]>([])
  const [scope, setScope] = useState<"my"|"all">("my")

  useEffect(() => {
    apiGet<Task[]>(`/api/tasks?scope=${scope}`).then(setTasks)
  }, [scope])

  if (taskId) {
    return <TaskDetail taskId={taskId} />
  }

  return (
    <AppShell>
      <Tabs value={scope} onValueChange={v => setScope(v as any)}>
        <TabsList>
          <TabsTrigger value="my">我的任务</TabsTrigger>
          <TabsTrigger value="all">全部任务</TabsTrigger>
        </TabsList>
        <TabsContent value={scope}>
          <TaskList tasks={tasks} />
        </TabsContent>
      </Tabs>
    </AppShell>
  )
}

function TaskDetail({ taskId }: { taskId: string }) {
  return (
    <AppShell>
      <ProgressStream
        taskIds={[taskId]}
        layout="detail"
        onComplete={() => { /* navigate to result */ }}
      />
    </AppShell>
  )
}
```

### 7.3 `/paper-trade/<ticker>` Island

复用 POC `PaperTradeDemo.tsx` + 接入真实 API（`GET /api/paper/tickers/<ticker>`）。移动端响应式已在 POC 修复。

### 7.4 `/dashboard` Island

复用 POC `DashboardDemo.tsx` + 接入 `/api/dashboard` 聚合接口（新增）。

## 8. 样式对齐

### 8.1 Tailwind v4 tokens

`frontend/src/styles/index.css` 已在 POC 完成（见 POC README）。

**关键一致性**：所有 `@theme` 里定义的 CSS vars 名称与 [mobile-optimization.md](./mobile-optimization.md) §2 完全一致：
- `--color-bg-primary` / `--color-bg-card`
- `--color-accent-blue` / `--color-accent-green` / `--color-accent-red`
- `--text-xs` → `--text-2xl`（clamp 响应式）
- `--radius-sm` → `--radius-xl`

旧 `style.css` 的 `:root { --color-*: ... }` 保持不变。新 Tailwind token 覆盖同名 CSS var。

### 8.2 作用域隔离

- React island 的 root 元素加 `data-ri-root` 属性（可选）
- 旧 `style.css` 的全局 reset 影响 island 内的元素 → Tailwind 的 `@tailwind base` 处理
- 测试：非迁移页视觉 pixel-match baseline（TC-UI-R1~R4）

### 8.3 Bootstrap 5 隔离

- React island **不引用** `bootstrap.min.css` / `bootstrap.bundle.min.js`
- 旧页面保留 Bootstrap（通过 index.html 的 `<link>`）
- layout.html 按需引入（islands 不 extends old index.html）

## 9. 开发工作流

```
# 一次性 setup
cd stock_trading_system/web/frontend
npm install

# 日常开发（两个 terminal）
# T1: Vite dev
cd stock_trading_system/web/frontend && npm run dev

# T2: Flask
export FLASK_ENV=development
flask --app stock_trading_system run --reload

# 访问 http://localhost:5000/screener-v3
# React 代码改动 → Vite HMR 推送 → 浏览器自动刷新
# Flask 代码改动 → Flask reloader → 浏览器手动刷新
```

## 10. 实施计划

### Phase 1 —— 构建管道（~4h）
- 建 `web/frontend/` 目录，`npm init` + Vite + React + Tailwind v4
- 配 `vite.config.ts`（多 entry + manualChunks）
- 写 `vite_helpers.py` + `layout.html` + 第一个空 island 模板
- 验证 Dev / Prod 双模式都能加载一个 Hello World island
- 更新 Procfile + nixpacks 配置

### Phase 2 —— 共享基础设施（~3h）
- 从 POC copy `src/components/ui/` 全部 14 组件
- 新建 `lib/api.ts` / `lib/socket.ts` / `lib/auth.ts` / `lib/utils.ts`
- 新建 `components/shared/ProgressStream.tsx`
- 从 POC copy `data/gurus.ts`
- 单测覆盖 `lib/*`

### Phase 3 —— Screener V3 island（~6h）
- 建 `islands/screener-v3/main.tsx` + `ScreenerV3Page.tsx`
- 复用 POC `ScreenerV3Demo` 结构
- 接 `/api/screen/v3/{gurus,estimate,trigger}` 三个现有 API
- Flask 路由 + 模板
- E2E：输入 NL → 选大师 → 预估 → 触发 → 跳 tasks
- **交付给用户：screener-v3 UI 可用（PRD §US-UI-1）**

### Phase 4 —— Tasks island（~4h）
- 建 `islands/tasks/main.tsx`
- `ProgressStream` 集成
- 列表页 + 详情页（同一 entry，路由内判）
- 与 Phase 3 联动：screener-v3 触发后跳进来

### Phase 5 —— Paper-trade detail island（~5h）
- 移植 POC `PaperTradeDemo`
- 接 `/api/paper/tickers/<ticker>`
- 解决 [paper-trade v1.3 F4 图表 + F5 tabs 合并](./paper-trade.md#二十七v13-修订2026-04-19)（React 版）
- Flask 路由 + 模板

### Phase 6 —— Dashboard island（~4h）
- 移植 POC `DashboardDemo`
- 新增 `/api/dashboard` 聚合端点（返回 stats + insights + running tasks + holdings overview）
- 旧 `/dashboard` Jinja 视图替换

### Phase 7 —— 收尾 + 验收（~2h）
- Playwright E2E 跑 PRD 6 个 US
- 桌面视觉回归（非迁移页 pixel-match）
- Lighthouse 移动端性能
- Railway 部署验证
- 更新 3 个 changelog + 主文档

**总计 ~28h**。

## 11. 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md) L0→L4：

### L0 项目内复用

- **全部既有 API**（`/api/screen/v3/*`, `/api/tasks/*`, `/api/paper/tickers/*`）—— 0 改动
- **Flask 外壳 + 路由系统** —— 保留，只加 4 个新路由
- **SocketIO 服务器** —— 复用（[unified-progress](./unified-progress.md) 约束）
- **CSRF token + session cookie** —— React fetch 继承
- **`style.css` CSS vars** —— Tailwind v4 `@theme` 复用同名变量
- **POC `/tmp/stock-ui-demo/` 的所有代码** —— 大部分可直接迁到 `web/frontend/`

### L1 依赖库

| 库 | 替代 |
|---|---|
| React 19 | 自写 vanilla render |
| Vite 8 | webpack / rollup 手搓 |
| Tailwind CSS v4 | 自写 CSS 工具类 |
| shadcn/ui 风格 | 自写组件（非运行时依赖，**代码进仓库**）|
| Radix UI 原语 | 自写 Dialog / Dropdown / Popover（a11y 复杂）|
| cmdk | 自写命令面板 |
| sonner | 自写 Toast 队列 |
| lucide-react | 自找图标 |
| class-variance-authority + tailwind-merge | 自写变体系统 |
| socket.io-client | 裸 WebSocket 自己管重连 |

### L2 思路参考

- [shadcn/ui 官方组件源码](https://ui.shadcn.com/docs/components)：**直接 copy** 样式（MIT license 允许）
- [Vite + Flask 社区方案](https://nickjanetakis.com/blog/using-vite-with-flask)：manifest.json 读取模式
- POC `/tmp/stock-ui-demo/` 自己做的 4 个 demo 页：迁移时 copy 90% 代码

### L3 Clean-room

无。

### L4 自写（业务特定）

| 模块 | 预估 LOC |
|---|---|
| Flask `vite_helpers.py` | ~40 |
| 4 个 island entry（main.tsx 各一）| ~80 |
| 4 个 island 页面组件（接 API + 状态管理）| ~800 |
| `lib/api.ts` / `lib/socket.ts` / `lib/auth.ts` | ~150 |
| 业务组件（GuruSelector 等）| ~300 |
| **总计新写** | **~1400 LOC** |
| **shadcn copy** | **~1200 LOC** |
| **POC 迁入** | **~1000 LOC** |

复用比例：**~60%**（shadcn copy + POC 迁入）。

## 12. 兼容性 & 回滚

### 12.1 向后兼容

- 任一 island 失败 → Flask 路由注释切回 `render_template("index.html")`
- 旧页面功能 100% 保留
- API 契约不变，旧 JS 和新 React 可并存访问

### 12.2 数据库 / 后端
- 0 改动

### 12.3 回滚步骤

1. 停服
2. `git revert` feature commits
3. 删除 `static/dist/`
4. 恢复 Procfile / railway.json
5. 重启

## 13. 风险缓解

| 风险 | 缓解 |
|---|---|
| Railway Nixpacks 不装 node | `.nixpacks/environment.toml` 显式加 nodejs-18_x |
| Vite prod build 生成的 hash 文件名与 Flask static 不配合 | `vite_helpers.py` 读 manifest 自动处理 |
| SocketIO 在 React StrictMode 下双连接 | `getSocket()` 单例 + effect cleanup |
| Tailwind v4 与 `style.css` CSS vars 冲突 | v4 `@theme` 覆盖同名，测试保证非迁移页 pixel-match |
| CSRF token 在 fetch 中遗漏 | `src/lib/api.ts` 强制注入，禁用裸 fetch |
| React island 间共享状态（如登录态）不一致 | 每 island 从 meta 读，不共享运行时状态 |
| 移动端 iOS Safari bundle loading 慢 | manualChunks + 首屏 ≤ 180KB gzipped |
| HMR 在 Flask template 里 `{{ csrf_token() }}` 刷新后失效 | HMR 只影响 JS，session 刷新走 Flask 正常路径 |

## 14. 与其他模块的集成

| 模块 | 集成点 |
|---|---|
| [screener-v3](./screener-v3.md) | 本方案 Phase 3 完成 PRD 未完成的 Phase 6 UI 部分 |
| [paper-trade v1.3](./paper-trade.md) | 本方案 Phase 5 完成 F4 图表 + F5 tab 合并的 React 实现 |
| [unified-progress](./unified-progress.md) | `ProgressStream` 统一 React 组件 |
| [mobile-optimization](./mobile-optimization.md) | Tailwind v4 tokens 对齐；移动端 375 / 768 断点复用 |
| [multi-tenant](./multi-tenant.md) | `g.user` 通过 `<meta>` 注入 + CSRF 无缝复用 |
| [model-switch](./model-switch.md) | 顶栏 provider dropdown **v1.1 可迁** 到 React，v1.0 保留 Jinja |

## 15. v2.0 完整迁移（剩余 11 页）

v1.0 覆盖 4 高价值页（screener-v3 / tasks / paper-trade detail / dashboard）。v2.0 把**剩余全部页面**都迁到 React island，实现视觉完全统一，并最终废弃旧 `index.html` + `app.js` + Bootstrap。

### 15.1 剩余页面清单

按交互复杂度 + 业务价值分 4 组：

| 组 | 页面 | 复杂度 | 主要组件 | 优先级 |
|---|---|---|---|---|
| **A 数据列表** | Portfolio 持仓 / History 分析记录 / Alerts 预警 / Reports 报告中心 / Paper 会话列表 | 中 | DataTable + Filter + Row actions | P0 |
| **B 复杂详情** | Analysis 分析详情 / Backtest 回测设置+结果 | 高 | 多 Tab 报告 + ECharts + 流式 | P0 |
| **C 表单驱动** | Settings 设置 / Analysis 触发表单 | 中 | Tabs + Form 控件 | P1 |
| **D 认证** | Login / Register / Reset | 低 | Form 单屏 | P1 |

共 11 页，合起来再排 ~40-50h（v2.0 的工作量比 v1.0 大约两倍）。

### 15.2 新增共享组件

v2.0 会沉淀出 v1.0 没覆盖到的模式：

| 组件 | 作用 | 在哪些页用 |
|---|---|---|
| **`<AppShell>`** | 统一 Nav + Sidebar + Mobile Tabbar，取代旧 `index.html` 外壳 | 所有 React 页 |
| **`<DataTable>`** | 列定义 + 排序 + 过滤 + 行操作 + 分页 + 空态 | Portfolio / History / Alerts / Reports / Paper list / Tasks |
| **`<FilterBar>`** | 搜索框 + chip-row 多维度筛选 + date range | History / Alerts / Reports / Paper list |
| **`<AuthCard>`** | 极简登录/注册卡片（logo + form + footer 链接） | Login / Register / Reset |
| **`<Form>` 系列** | 基于 react-hook-form + zod 的字段封装（Input/Select/Switch + 错误展示） | 所有表单页 |
| **`<SettingsTabs>`** | 左侧垂直 tab + 右侧内容区（Apple System Preferences 风） | Settings |
| **`<EChartsPanel>`** | ECharts React 包装，响应 theme/resize，支持 loading skeleton | Backtest / Dashboard / Paper-trade |

### 15.3 每页规格

#### 15.3.1 Portfolio（持仓管理）

**路径**：`/portfolio`

**现状**：`index.html` L562-677 一堆 `col-6 col-md-4` 表单（买入/卖出各 4 字段）+ 持仓列表

**升级方案**：

```
┌─ Page: 持仓管理 ──────────────────────────────┐
│                                                │
│  持仓总值  持仓数  今日盈亏  胜率              │
│  [stat]   [stat]  [stat]   [stat]             │   ← v1.0 Stat 组件
│                                                │
│  ┌─ 持仓表 ─────────────────────────────┐     │
│  │ [搜索] [市场 ▾] [排序 ▾]   [+ 买入] │     │
│  │ ┌────────────────────────────────────┐│     │
│  │ │ 代码 名称 持仓 成本 现价 盈亏 信号  ⋯││     │   ← DataTable
│  │ │ ...                                  ││     │
│  │ └────────────────────────────────────┘│     │
│  └────────────────────────────────────────┘     │
│                                                │
│  ┌─ 近 30 天净值曲线 ────────────────────┐     │
│  │ [ECharts]                              │     │   ← EChartsPanel
│  └────────────────────────────────────────┘     │
└───────────────────────────────────────────────┘

动作：
  - 点 [+ 买入]  → Dialog 表单（ticker / shares / price / notes）
  - 行末 ⋯       → DropdownMenu（分析 / 加仓 / 卖出 / 移除）
  - 点代码        → 跳 /analysis?ticker=<x>
```

**API**：复用现有 `/api/portfolio` GET/POST/DELETE，新增 `/api/portfolio/summary`（Stats 聚合）。

**关键组件**：`DataTable` / `Dialog` / `DropdownMenu` / `EChartsPanel`。

**移动端**：DataTable 超过 ≤768px 切 `.m-card` 卡片视图（复用 [mobile-optimization §3.3 table-to-cards](./mobile-optimization.md) 模式的 React 实现）。

#### 15.3.2 History（分析记录）

**路径**：`/history`

**现状**：L438-462 简单列表 + 搜索框

**升级方案**：

```
┌─ Page: 分析记录 ──────────────────────────────┐
│                                                │
│  [搜索 ticker / 关键词]                        │
│  [全部 | 我的]  [信号 ▾] [Provider ▾] [日期 ▾] │   ← FilterBar
│                                                │
│  ┌────────────────────────────────────────────┐│
│  │ ★ NVDA  BUY  2026-04-19 ...                ││
│  │   核心论点：AI 基础设施...                   ││   ← 卡片列表（非 table）
│  │   Buffett · Wood · Druckenmiller           ││
│  │ ─────────────────────────────────          ││
│  │ ☆ AAPL  HOLD  2026-04-18 ...               ││
│  │   ...                                        ││
│  └────────────────────────────────────────────┘│
│                                                │
│  [加载更多]                                    │
└───────────────────────────────────────────────┘

特性：
  - 每行可点 ★ 加/取消 bookmark（集成 multi-tenant analysis_bookmarks）
  - 点标题跳 /analysis/<id>
  - 「我的」tab 只显示自己 bookmark 的 + 自己触发的
  - 支持无限滚动
```

**API**：复用 `/api/analysis/history`（可能需要加 `?bookmarked=true` 过滤）；`/api/analysis/bookmarks` POST/DELETE。

**关键组件**：`FilterBar` / `Card` / 虚拟滚动（data > 500 行考虑 react-virtual）。

#### 15.3.3 Alerts（预警中心）

**路径**：`/alerts`

**现状**：L679-758 4 字段表单 + 2 table（active / history）

**升级方案**：

```
┌─ Page: 预警中心 ──────────────────────────────┐
│                                                │
│  [运行中 12]  [今日触发 3]  [本周触发 18]      │   ← Stats
│                                                │
│  [Tab: 规则 | 历史]                            │
│                                                │
│  Tab=规则:                                     │
│  ┌────────────────────────────────────────────┐│
│  │ [+ 新增规则]                                ││
│  │ ┌─────────────────────────────────────────┐││
│  │ │ NVDA  价格 ≥ $210  [启用] ⋯             │││   ← DataTable
│  │ │ AAPL  跌破 $200    [启用] ⋯             │││
│  │ └─────────────────────────────────────────┘││
│  └────────────────────────────────────────────┘│
│                                                │
│  Tab=历史:                                     │
│   按时间倒序的触发事件流                        │
└───────────────────────────────────────────────┘

[+ 新增规则] 点开 Dialog:
  条件类型: [价格高于 ▾]
  股票:    [搜索 / 粘贴]
  阈值:    [输入]
  通知方式: [☑ 站内] [☑ 邮件] [☐ Telegram]
```

**API**：`/api/alerts` GET/POST/PUT/DELETE（现有）+ `/api/alerts/history`。

**关键组件**：`Tabs` / `DataTable` / `Dialog` / `Switch` / `Combobox`（股票搜索）。

#### 15.3.4 Reports（报告中心）

**路径**：`/reports`

**现状**：L759-795 生成表单 + 简单列表

**升级方案**：

```
┌─ Page: 报告中心 ──────────────────────────────┐
│                                                │
│  ┌─ 生成新报告 ───────────────────────────────┐│
│  │ 类型:[周报 ▾]  股票:[NVDA]  时段:[近 7 天] ││
│  │                          [预览] [生成]     ││
│  └────────────────────────────────────────────┘│
│                                                │
│  已生成报告:                                    │
│  ┌────────────────────────────────────────────┐│
│  │ ★ NVDA 周报 · 2026-04-20 · PDF / MD / HTML ││
│  │ ☆ AAPL 持仓复盘 · 2026-04-18 · ...         ││
│  └────────────────────────────────────────────┘│
└───────────────────────────────────────────────┘

动作：
  - [生成] → 异步 task → 跳 /tasks/<id> 看进度
  - 完成后可从 /tasks 或 /reports 下载
```

**API**：`/api/reports` GET/POST（复用现有）。

**关键组件**：`Form` / `DataTable` / `DropdownMenu`（导出格式）。

#### 15.3.5 Backtest（策略回测）

**路径**：`/backtest`

**现状**：L796-865 大量参数字段 + 触发 + 结果

**升级方案**：

```
┌─ Page: 策略回测 ──────────────────────────────┐
│                                                │
│  [Tab: 新建 | 历史]                            │
│                                                │
│  Tab=新建（左右 2 栏）:                         │
│  ┌─左 40%─────────┐ ┌─右 60%────────────────┐ │
│  │ 策略参数         │ │ 即时预览              │ │
│  │ 标的: [NVDA]   │ │ [即时 Sharpe 估算]    │ │
│  │ 区间: [3M ▾]   │ │ 样本: 近 100 天       │ │
│  │ 初始: [$10000] │ │ [mini chart]          │ │
│  │ 策略: [买入持 ▾]│ │                        │ │
│  │ [+参数组合]    │ │                        │ │
│  │                 │ │                        │ │
│  │ 预估成本 ¥0    │ │                        │ │
│  │ [开始回测]     │ │                        │ │
│  └─────────────────┘ └────────────────────────┘ │
│                                                │
│  Tab=历史:                                     │
│   DataTable: 策略 / 标的 / 区间 / Sharpe / 时长 │
│   点击行 → 跳结果详情页                         │
└───────────────────────────────────────────────┘

结果详情 /backtest/<id>:
  - 净值曲线 (EChartsPanel 大图)
  - 指标卡 (Sharpe / max drawdown / 胜率 / PnL)
  - 交易明细 DataTable
  - 回测参数 JSON 折叠
```

**API**：`/api/backtest` 已有；新增 `/api/backtest/estimate`（预览）。

**关键组件**：`Tabs` / `Form` / `EChartsPanel` / `DataTable` / `Accordion`。

#### 15.3.6 Paper list（纸面交易会话列表）

**路径**：`/paper-trade`（无 ticker 参数）

**现状**：L866-933 会话卡片 grid + 添加按钮

**升级方案**：

```
┌─ Page: 纸面交易 ──────────────────────────────┐
│                                                │
│  [默认 session ★]  总值 $100k  Sharpe 1.82    │   ← 突出默认
│                                                │
│  [+ 新建 session]   [搜索]   [Tab: 我的 | 全部] │
│                                                │
│  ┌────────────────────────────────────────────┐│
│  │ ┌──────────────┐ ┌──────────────┐          ││
│  │ │ session 卡   │ │ session 卡   │          ││   ← Grid of 2-3 cols
│  │ │ NVDA / AAPL  │ │ TSLA / MSFT  │          ││
│  │ │ PnL +5.2%    │ │ PnL -1.8%    │          ││
│  │ │ 8 trades     │ │ 3 trades     │          ││
│  │ └──────────────┘ └──────────────┘          ││
│  └────────────────────────────────────────────┘│
│                                                │
│  点卡片 → /paper-trade/<session_id>            │
│  （session 详情页在 v1.0 Phase 5 已做）         │
└───────────────────────────────────────────────┘
```

**API**：`/api/paper/sessions` GET/POST。

**关键组件**：`Card` grid + `FilterBar` + `Tabs`。

#### 15.3.7 Settings（设置）

**路径**：`/settings`

**现状**：L1019-1058 简单 settings-row 列表

**升级方案** —— Apple System Preferences 风 Tabs：

```
┌─ Page: 设置 ───────────────────────────────────┐
│                                                │
│  ┌─左 220px───┐ ┌─右──────────────────────────┐│
│  │ 账号       │ │ 账号                         ││
│  │  · 个人资料│ │                              ││
│  │  · 修改密码│ │  邮箱     admin@local        ││
│  │ 集成       │ │  显示名   Admin              ││
│  │  · LLM     │ │  角色     管理员             ││
│  │  · 通知    │ │  创建于   2026-04-15         ││
│  │ 系统       │ │                              ││
│  │  · 邀请码  │ │  [修改密码]                  ││
│  │  · 数据    │ │                              ││
│  │ 高级       │ │                              ││
│  │  · 诊断    │ │                              ││
│  └─────────────┘ └──────────────────────────────┘│
│                                                │
│  当前子页内容：                                 │
│    集成/LLM → provider 切换（迁 model-switch）  │
│    集成/通知 → 邮件/Telegram 配置               │
│    系统/邀请码 → admin 专属：列表 + 生成（迁 multi-tenant）│
│    系统/数据 → 导入/导出 / 数据库备份           │
│    高级/诊断 → 系统状态 / 日志尾 / 清缓存        │
└───────────────────────────────────────────────┘
```

**API**：多个分散端点按子页调用。

**关键组件**：`SettingsTabs`（新）+ `Form` + 各子页独立组件。

**特别注意**：这页涉及多个子模块，建议 Phase 化：先框架，再每个子页单独迁入。

#### 15.3.8 Analysis（AI 多 Agent 分析）

**路径**：
- `/analysis`（触发 + 记录列表）
- `/analysis/<id>`（单次分析详情）

**现状**：L263-437 非常复杂（触发表单 + 8 个 tab 的报告展示 + debate / risk / decision）

**升级方案**：

##### Analysis 列表/触发 `/analysis`

```
┌─ Page: AI 多 Agent 分析 ──────────────────────┐
│                                                │
│  ┌─ 新建分析 ─────────────────────────────────┐│
│  │ 股票: [代码或粘贴]   日期: [今天 ▾]        ││
│  │ 深度: ○经典 ⬤标准 ○加强                   ││
│  │                     [估算] [开始分析]      ││
│  └────────────────────────────────────────────┘│
│                                                │
│  我最近的分析:                                  │
│  DataTable: ticker / date / signal / provider /│
│             duration / score / actions         │
└───────────────────────────────────────────────┘
```

##### Analysis 详情 `/analysis/<id>`

```
┌─ Analysis #25 · NVDA · 2026-04-19 ─────────────┐
│                                                │
│  [BUY]  置信度 85%   由 alice 触发              │
│  [⋯ 操作]   [↗ 再次分析]                       │
│                                                │
│  ┌─ Executive Summary ────────────────────────┐│
│  │ AI 基础设施周期上行, Blackwell 交付加速...  ││   ← executive_summary 字段
│  └────────────────────────────────────────────┘│
│                                                │
│  [Tab: 概览 | 市场 | 情绪 | 新闻 | 基本面 |    │
│        辩论 | 风险 | 决策]                      │
│                                                │
│  当前 tab 的 Markdown 渲染（react-markdown）    │
│                                                │
│  底部:                                          │
│  [加入持仓追踪] [导出 PDF] [分享]               │
└───────────────────────────────────────────────┘

移动端：
  Tab 用 tabs-scrollable（横滑）
  Tab 内 Markdown 正常渲染
```

**API**：`/api/analyze` POST / `/api/analysis/<id>` GET（现有）。

**关键组件**：`Tabs` / `Markdown` / `Dialog`（操作菜单）/ `DataTable`（列表页）。

**注意**：Tab 数量多（8 个），移动端强制横滑；复用 [mobile-optimization](./mobile-optimization.md) `.tabs-scrollable`。

#### 15.3.9 Login（登录）

**路径**：`/login`

**现状**：multi-tenant v1.0 新建（见 [multi-tenant.md §10.1](./multi-tenant.md)）

**升级方案** —— 极简登录卡：

```
┌───────────────────────────────────────────────┐
│                                                │
│               [Logo]                          │
│          StockAI Terminal                     │
│                                                │
│        ┌──────────────────────────┐           │
│        │  登录                     │           │
│        │                           │           │
│        │  邮箱                     │           │
│        │  [                      ] │           │
│        │                           │           │
│        │  密码                     │           │
│        │  [                      ] │           │
│        │                           │           │
│        │  [ 登录 ───────────────► ]│           │
│        │                           │           │
│        │  忘记密码? 联系管理员      │           │
│        │  没账号? 填邀请码注册 →    │           │
│        └──────────────────────────┘           │
│                                                │
│                                                │
└───────────────────────────────────────────────┘

特性:
  - 居中卡片 + 背景轻微渐变
  - 回车提交
  - 失败时红色震动 shake 动画
  - 登录中按钮变 loading spinner
```

**API**：`/api/auth/login`。

**关键组件**：`AuthCard` + `Form`。

#### 15.3.10 Register（注册）

**路径**：`/register`

与 Login 同布局，字段：邀请码 / 邮箱 / 密码 / 确认密码 / 显示名。

邀请码实时校验（失焦时 debounce 调 `/api/invite/validate`）：
- ✅ 绿色 `√ 有效邀请码`
- ❌ 红色 `× 邀请码无效 / 已用 / 过期`

#### 15.3.11 Reset（重置密码）

**路径**：`/reset?token=<uuid>`

与 Login 同布局，字段：新密码 / 确认新密码。

进入时先调 `/api/auth/reset/validate?token=<x>`，无效 token 直接显示错误 card + 返回登录链接。

### 15.4 新增共享组件细节

#### `<AppShell>`

```tsx
// components/shared/AppShell.tsx
import { ReactNode } from "react"
import { Sidebar } from "./Sidebar"
import { MobileTabbar } from "./MobileTabbar"
import { NavTopbar } from "./NavTopbar"
import { ConnectionIndicator } from "./ConnectionIndicator"
import { Toaster } from "@/components/ui/toaster"

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--color-bg-primary)]">
      <NavTopbar />
      <div className="flex">
        <Sidebar />
        <main className="flex-1 min-w-0 pb-20 lg:pb-6">
          <div className="mx-auto max-w-7xl px-4 lg:px-8 py-6">
            {children}
          </div>
        </main>
      </div>
      <MobileTabbar />
      <ConnectionIndicator />
      <Toaster />
    </div>
  )
}
```

每个 React island 用 `<AppShell>{pageContent}</AppShell>` 包裹 → 所有页**视觉完全统一**。

侧边栏 active 态通过 `window.location.pathname` 判断。

#### `<DataTable>`

基于 **`@tanstack/react-table`**（L1 库，行业标准，20K⭐），不自写。

```tsx
// components/shared/DataTable.tsx
import {
  useReactTable, getCoreRowModel, getSortedRowModel, getFilteredRowModel,
  getPaginationRowModel, ColumnDef, flexRender,
} from "@tanstack/react-table"

interface Props<T> {
  data: T[]
  columns: ColumnDef<T>[]
  searchKey?: keyof T
  filterBar?: ReactNode
  emptyState?: ReactNode
  mobileRenderer?: (row: T) => ReactNode  // ≤768px 走卡片
}

export function DataTable<T>({ data, columns, ... }: Props<T>) {
  // ...
}
```

依赖：`npm install @tanstack/react-table`。

#### `<Form>` 系列

基于 **`react-hook-form` + `zod`**（行业标准组合）。

```tsx
// components/ui/form.tsx (shadcn 标配)
import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import * as z from "zod"

// shadcn 官方有完整 Form 组件文件，直接 copy
```

依赖：`npm install react-hook-form zod @hookform/resolvers`。

#### `<EChartsPanel>`

```tsx
// components/shared/EChartsPanel.tsx
import { useEffect, useRef } from "react"
import * as echarts from "echarts/core"
// ...各模块按需导入

interface Props {
  option: echarts.EChartsOption
  height?: number
  loading?: boolean
}

export function EChartsPanel({ option, height = 320, loading }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    chart.current = echarts.init(ref.current, "dark")
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart.current?.dispose() }
  }, [])

  useEffect(() => { chart.current?.setOption(option, true) }, [option])
  useEffect(() => {
    loading ? chart.current?.showLoading("default", { text: "", color: "var(--color-accent-blue)" })
            : chart.current?.hideLoading()
  }, [loading])

  return <div ref={ref} style={{ height, width: "100%" }} />
}
```

### 15.5 实施计划（Phase 8-15）

基于 v1.0 Phase 1-7 已完成。

| Phase | 内容 | 估时 |
|---|---|---|
| 8 | 新增共享组件：`<AppShell>` / `<DataTable>` (tanstack) / `<Form>` (react-hook-form+zod) / `<EChartsPanel>` / `<AuthCard>` | ~5h |
| 9 | Auth 三页：Login / Register / Reset（极简 Island，复用 multi-tenant 后端 API） | ~3h |
| 10 | Portfolio island | ~4h |
| 11 | History island | ~3h |
| 12 | Alerts island（Tabs + 规则/历史）| ~4h |
| 13 | Reports island | ~3h |
| 14 | Backtest island（新建 tab + 历史 tab + 结果详情页）| ~6h |
| 15 | Paper list island | ~2h |
| 16 | Analysis island（列表 + 详情，含 8 tab 报告）| ~6h |
| 17 | Settings island（SettingsTabs + 各子页）| ~5h |
| 18 | 废弃 `index.html` + `app.js` + Bootstrap；清理旧 `style.css` | ~3h |
| 19 | 端到端验收 + 视觉回归 + 部署 | ~3h |

**v2.0 总计 ~47h**（v1.0 28h + v2.0 47h = 共 **~75h**）。

实施顺序建议：
1. **Phase 8 先做**（共享组件是后面所有页的基础）
2. **Phase 9 放前面**（Auth 是独立的 island，作 AppShell 压测）
3. **Phase 10-13 按数据列表系列批量做**（共用 DataTable 模式，加速）
4. **Phase 14-16 复杂页**
5. **Phase 17 设置最复杂**（多子页）
6. **Phase 18 最后清理**

### 15.6 废弃旧代码（Phase 18）

所有页都迁完后：
- `templates/index.html` → 改 `render` 旁路到各 Flask 路由
- `static/js/app.js` → 删除（~4000 行！）
- `static/css/style.css` → 保留 CSS vars 部分，删 Bootstrap 覆盖 + 各页专用样式
- Bootstrap 5 `<link>` / `<script>` → 删除
- bootstrap-icons CSS → 删除（全部换 lucide-react）

**收益**：代码量减 5000+ 行；暗色主题唯一事实源在 Tailwind `@theme`；维护成本大幅下降。

### 15.7 v2.0 新增依赖

```json
{
  "@tanstack/react-table": "^8",
  "react-hook-form": "^7",
  "zod": "^3",
  "@hookform/resolvers": "^3",
  "echarts": "^5",
  "react-markdown": "^9"
}
```

全部行业标配，license 友好（MIT / Apache-2.0）。

### 15.8 v2.0 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md)：

**L0 项目内复用**：
- `AppShell` 组件复用现有 tabbar / nav HTML 思路
- `EChartsPanel` 复用现有 ECharts 图表配置思路（见 [app.js:4518-4549](../../stock_trading_system/web/static/js/app.js)）
- 所有 API 端点已存在

**L1 库**：
- `@tanstack/react-table` → 替代自写表格（行内编辑/排序/分页/虚拟滚动一站式）
- `react-hook-form` + `zod` → 替代自写表单状态管理 + 校验
- `react-markdown` → 替代自写 Markdown 渲染器

**L2 思路**：
- shadcn 官方 `Form` 组件源码（Apache-2.0 demo，可 copy）
- shadcn 官方 `DataTable` recipe（基于 tanstack table 的封装模板）

**L4 自写**：
- `<AppShell>` / `<SettingsTabs>` / `<AuthCard>` / `<EChartsPanel>` / `<FilterBar>` —— ~400 LOC
- 11 个 page component（平均 150 LOC 每页）—— ~1650 LOC
- 总计 ~2050 LOC 新写（含业务逻辑）

### 15.9 v2.0 风险

| 风险 | 缓解 |
|---|---|
| 迁移 11 页的长工期 Bug 堆积 | Phase 8 先做共享组件，Phase 9-17 每页独立 commit + 独立回滚 |
| Analysis 的 8 tab 报告内容比 v1.0 移植的任何页都复杂 | 优先覆盖 5 主要 tab（市场/基本面/新闻/辩论/决策），次要 tab 后续加 |
| tanstack/react-table 学习曲线 | shadcn 官网有完整 recipe；5-6 页的 DataTable 共用一个自封装 |
| 删除 app.js 的最后一步可能藏 bug | Phase 18 前先让新老并存 2 周（feature flag 切换），稳定后删 |
| 多个子页的 Settings 拆分复杂 | SettingsTabs 骨架先做，各子页独立 PR |
| Bootstrap 全量删除后旧用户页面样式丢失 | Phase 18 分"保留 CSS vars 删 Bootstrap" 和 "删 CSS vars" 两步 |

## 16. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-21 | 初版：Vite + Flask 协作管道 + manifest.json 驱动 + 4 岛屿首批迁移（screener-v3 / tasks / paper-trade / dashboard）+ 7 Phase 实施计划 + shadcn 组件库从 POC 迁入 + `lib/api.ts` / `lib/socket.ts` / `ProgressStream` 共享基础设施 + Railway 部署适配 |
| v2.0 | 2026-04-21 | 完整迁移：新增剩余 11 页（Portfolio / History / Alerts / Reports / Backtest / Paper list / Analysis 列表+详情 / Settings / Login / Register / Reset）+ 新增共享组件（`<AppShell>` / `<DataTable>` 基于 tanstack / `<Form>` 基于 react-hook-form+zod / `<EChartsPanel>` / `<AuthCard>` / `<SettingsTabs>` / `<FilterBar>`）+ 每页页面规格 + Phase 8-19 共 ~47h 实施计划 + Phase 18 废弃旧 index.html / app.js / Bootstrap |
