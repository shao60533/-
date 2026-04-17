# Railway Deployment Guide

部署 Stock Trading Advisory System 到 [Railway](https://railway.app) 的完整流程。

## TL;DR (5 分钟部署)

```bash
# 1. Push your fork to GitHub
# 2. railway.app → New Project → Deploy from GitHub
# 3. Set env vars (see below)
# 4. Add Persistent Volume → /app/data
# 5. Visit your Railway URL — first hit may take 30-60s for cold start
```

---

## 1. 必需环境变量

| Env Var | Example | Why |
|---------|---------|-----|
| `DASHSCOPE_API_KEY` | `sk-xxxxxxxx` | Qwen LLM key — 主数据源（价格/基本面/新闻/分析） |

**自动生效**：设置 `DASHSCOPE_API_KEY` 后系统会自动启用 Qwen（`qwen.enabled=true`），无需改 `config.yaml`。

## 2. 可选环境变量

| Env Var | Example | When you need it |
|---------|---------|------------------|
| `PORT` | (Railway 自动注入) | 启动端口 — 已自动处理，不要手动设 |
| `GEMINI_API_KEY` | `AIza...` | 想用 Gemini 而不是 Qwen 跑 AI 分析时 |
| `TELEGRAM_BOT_TOKEN` | `1234:ABC...` | 启用 Telegram 推送 |
| `TELEGRAM_CHAT_ID` | `123456789` | 配合上面 |
| `EMAIL_SMTP_HOST` | `smtp.gmail.com` | 启用邮件推送 |
| `EMAIL_USERNAME` | `you@gmail.com` | 配合上面 |
| `EMAIL_PASSWORD` | `app-password` | 配合上面 |
| `EMAIL_TO` | `you@gmail.com` | 配合上面 |
| `POLYGON_API_KEY` | `...` | **不推荐**：免费层限流，云端用没意义 |

---

## 3. 部署文件清单

仓库根目录已预置：

| File | Purpose |
|------|---------|
| `Procfile` | Railway/Heroku 启动命令 |
| `railway.json` | Railway 构建+健康检查配置（healthcheck `/api/health`） |
| `runtime.txt` | Python 版本固定（3.11） |
| `requirements.txt` | 依赖清单 |

无需 Dockerfile — Railway 自动用 Nixpacks 构建。

---

## 4. Persistent Volume 配置 ⚠️ 必须

Railway 容器文件系统是临时的，重启会丢数据。**必须挂载 Volume**：

1. Railway Dashboard → Project → Service → Settings → Volumes
2. **Mount Path**: `/app/data`
3. **Size**: 1 GB 起步够用（持仓+任务记录+缓存）

挂载后，自动生效（`portfolio.db_path` 默认 `data/portfolio.db`，会被持久化）。

---

## 5. 默认架构（云端友好）

部署后默认配置（`default_config.yaml`）：

```yaml
providers:
  ib_enabled: false        # 默认禁用 IB（需本地 TWS）
  polygon_enabled: false   # 默认禁用 Polygon（限流）
  yfinance_enabled: true
  akshare_enabled: true    # 海外节点可能不可达，部署后用诊断接口验证

data_routing:
  primary: "qwen"          # Qwen 主，yfinance/AkShare 兜底
  enable_cache: true       # SQLite 缓存

tasks:
  max_workers: 3           # 并发任务数
  retention_days: 30       # 任务记录自动清理
  cleanup_interval: 21600  # 每 6 小时清理一次
```

如需调整（比如改主源为 yfinance），可：

- 编辑 `~/.stock_trading/config.yaml`（容器内路径需挂卷）
- 或通过 Web 设置页改

---

## 6. 部署后验证

### 6.1 健康检查

```bash
curl https://your-app.up.railway.app/api/health
# {"status":"ok"}
```

Railway 会自动每 60 秒探活，5 次失败重启。

### 6.2 数据源诊断 ⭐ 必跑

```bash
curl https://your-app.up.railway.app/api/diagnostics/providers
```

返回示例：

```json
{
  "ok": true,
  "providers": {
    "qwen":     {"ok": true,  "latency_ms": 4500, "error": null},
    "yfinance": {"ok": true,  "latency_ms": 800,  "error": null},
    "akshare":  {"ok": false, "latency_ms": 8000, "error": "timeout"}
  },
  "routing": {
    "primary": "qwen",
    "cache_enabled": true,
    "qwen_enabled": true,
    "yfinance_enabled": true,
    "akshare_enabled": true
  }
}
```

**典型部署后表现**：
- ✅ Qwen 通常可用（DashScope 全球可达）
- ✅ yfinance 通常可用（Yahoo 全球可达）
- ❓ AkShare：海外节点常失败 → 系统会自动降级，A 股功能受限

如 AkShare 不可用，建议在 Railway Variables 设 `RAILWAY_REGION` 选最近 A 股节点的区，或接受 A 股功能降级（Qwen 的 web search 仍可覆盖单点查询）。

### 6.3 任务系统验证

```bash
# 提交一个 echo 任务
curl -X POST https://your-app.up.railway.app/api/tasks/submit \
     -H "Content-Type: application/json" \
     -d '{"type":"echo","params":{"hi":"railway"}}'

# 查看任务列表
curl https://your-app.up.railway.app/api/tasks
```

---

## 7. 常见问题

### Q1: 第一次访问很慢？

冷启动 + 第一次 `import yfinance` 需要 30-60 秒。Railway 健康检查超时设为 60s 就是为这个。

### Q2: WebSocket 连不上？

Railway 默认支持 WebSocket。如果浏览器报 `transport=polling` 一直降级，检查 `Origin` 是否被 CORS 阻挡 — 我们设了 `cors_allowed_origins="*"`，应该 OK。

### Q3: 想关掉 Qwen 用本地兜底？

设环境变量：

```bash
QWEN_API_KEY=""    # 留空 → qwen.enabled 不会自动开
# 然后手动改 config.yaml 里 data_routing.primary = "local"
```

### Q4: 任务记录占用太多空间？

调小保留期：

```yaml
tasks:
  retention_days: 7         # 改成 7 天
  cleanup_interval: 3600    # 每小时清理一次
```

或手动触发清理：

```bash
curl -X POST https://your-app.up.railway.app/api/tasks/cleanup
```

### Q5: 一定要鉴权吗？

单人使用 + 不对外公开 → 不需要。
公网部署 → 在 Railway Variables 加 `RAILWAY_PRIVATE_DOMAIN` 限定访问，或在前面套个 Cloudflare Access。

---

## 8. 资源用量参考

| 资源 | 单人使用日均 |
|------|------------|
| CPU | 0.05 vCPU 平均 / 0.5 vCPU 峰值（AI 分析时） |
| 内存 | 200-400 MB |
| Volume | < 100 MB（含 30 天任务记录） |
| 网络出 | < 100 MB / 月 |
| **Railway 月费估算** | $5 Hobby Plan 完全够 |

---

## 9. 升级流程

```bash
git pull origin main
git push railway main   # 或者 GitHub auto-deploy
# Railway 自动构建并滚动重启
```

升级时会：
- 后台运行中的任务被中断 → TaskManager 启动时把它们标记为 `failed: "服务中断"` → 用户可在任务中心一键重试
- LocalCache 缓存保留（在 Volume 上）
- 任务历史保留（在 Volume 上）

---

*Have fun shipping. 部署有问题随时提 Issue。*
