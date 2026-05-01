# Schwab Trader API 集成 — 实时行情与账户数据接入

> **版本**: 1.1（OAuth 引导从命令行改为 Web 端点）
> **日期**: 2026-04-25
> **状态**: 实施中（P0 + P1 已落地,等 Schwab App 审核完成 callback URL 变更）
> **原则**: 能复用就复用，L1 直接用 `schwab-py`，不自写 HTTP 客户端
> **参考**: [engineering-principles.md](../engineering-principles.md) · [architecture-upgrade.md](architecture-upgrade.md)

---

## 〇、先说结论

用户已开通 Schwab Developer 账号，要求"所有交易实时查询内容都优先切到这个上面"。

**结论**：Schwab 是目前最有价值的升级 —— IB 云端不可用、Polygon 免费档限流、yfinance 延迟数据、Qwen 不可信，实际上**现有系统在云端从没有真·实时**。Schwab 对个人开发者免费，提供 NBBO 级别实时报价、完整的账户/订单/持仓数据、WebSocket 流推送，MIT 许可的 [`schwab-py`](https://github.com/alexgolec/schwab-py) 库成熟稳定。

**改造范围**: 数据层 provider 新增 + 实时链路重排，**前端 API 零变更**。

---

## 一、复用 / Reuse

### L0 项目内复用

- [data/data_manager.py](../../stock_trading_system/data/data_manager.py) — 新 provider 插入 US 链路最前端，沿用 `_is_skipped` / `_record_fail` 熔断机制。
- [data/data_router.py](../../stock_trading_system/data/data_router.py) — `primary="schwab"` 分支，复用已有的 `LocalCache` 和 `validate_quote`。
- [data/local_cache.py](../../stock_trading_system/data/local_cache.py) — SQLite 缓存，TTL 机制照搬（price_quote=60s）。
- [portfolio/manager.py](../../stock_trading_system/portfolio/manager.py) — `get_holdings()` 的 ThreadPool 并发抓价改为 **Schwab 批量 quotes 一次请求**，同时节省配额和时延。
- [data/validators.py](../../stock_trading_system/data/validators.py) — `validate_quote` 复用。
- [utils/helpers.py](../../stock_trading_system/utils/helpers.py) — `detect_market` 复用，CN 股依旧走 AkShare，Schwab 只处理 US。

### L1 依赖库

- **`schwab-py>=1.4`** ([github.com/alexgolec/schwab-py](https://github.com/alexgolec/schwab-py)，MIT) — 替代自写所有 OAuth、HTTP、WebSocket 逻辑。提供 `schwab.auth.client_from_token_file` / `easy_client`、`client.get_quote(s)`、`client.get_price_history_every_day`、`client.get_account`、`client.place_order`、`schwab.streaming.StreamClient`。
- **`authlib`**（`schwab-py` 传递依赖）— OAuth 2.0 客户端。
- **`httpx`**（`schwab-py` 传递依赖）— 异步 HTTP。

### L2 / L3 开源参考

- `tda-api` (schwab-py 前身，同作者，2022 年停止维护) — 仅作接口设计参考，不引入。
- `schwab-py` 的 example 目录提供 OAuth 引导脚本，可直接采用。

### L4 自写（必要 & 无替代）

| 模块 | 估算 | 理由 |
|------|------|------|
| `SchwabProvider` 类 | ~180 行 | 将 `schwab-py` 输出 schema 映射到项目内部 `{ticker, last, close, bid, ask, high, low, volume}` 标准格式，与 IB / yfinance / Polygon provider 同形。无法复用。 |
| OAuth 首次引导 CLI | ~40 行 | 调用 `schwab.auth.client_from_login_flow` 打开浏览器、写 token.json。复用 schwab-py example 基础上做最小包装。 |
| Token 过期监控 | ~30 行 | 读取 `token.json` mtime，>6 天告警。属业务策略。 |
| DataManager / DataRouter 链路插入 | ~60 行 | 现有链路 diff，不是新建。 |
| Schwab 账户只读 API 端点（P2） | ~150 行 | Flask endpoint 胶水，返回持仓/订单/交易。 |

**合计自写 ≈ 460 行**，其中 DataManager/Router 改动是 diff 而非新增，净新增约 400 行。PR 拆分：P0 provider（180 行）+ P1 链路插入（60 行）+ P2 账户端点（150 行，独立 PR）。

---

## 二、Schwab Trader API 能力盘点

| 能力 | 端点 | schwab-py 方法 | 本项目用途 |
|------|------|---------------|-----------|
| 单标的/批量实时报价 | `GET /marketdata/v1/quotes` | `client.get_quotes(symbols)` | `/api/price`、`/api/quote`、`portfolio.get_holdings` 批量 |
| K 线历史（日/分钟） | `GET /marketdata/v1/pricehistory` | `client.get_price_history_every_day` / `every_minute` | `/api/chart` |
| 期权链 | `GET /marketdata/v1/chains` | `client.get_option_chain` | P2 新能力 |
| 市场 Movers | `GET /marketdata/v1/movers/{id}` | `client.get_movers` | 可用作 screener 候选池 |
| 账户列表/持仓/余额 | `GET /trader/v1/accounts` | `client.get_account_numbers` / `get_account` | P2 只读对账 |
| 订单历史 | `GET /trader/v1/accounts/{hash}/orders` | `client.get_orders_for_account` | P2 只读 |
| 交易记录 | `GET /trader/v1/accounts/{hash}/transactions` | `client.get_transactions` | P2 只读 |
| 下单 | `POST /trader/v1/accounts/{hash}/orders` | `client.place_order` | **P3 及以后**，需双重确认 + 限额 |
| 流式行情 | WSS (`schwab.streaming`) | `StreamClient.level_one_equities_subs` / `chart_equity_subs` | P3 推送 dashboard |

**限流**：每端点约 120 req/min；quotes 单次最多 500 symbol（批量是唯一省配额的方式）。

**认证**：OAuth 2.0 三腿；access-token 30 min 自动刷新；**refresh-token 7 天必须重新人工授权**（这是 Schwab 的硬约束，不是 schwab-py 的缺陷）。

---

## 三、数据流与现有链路整合

### 3.1 现有数据来源矩阵（改造后）

| 场景 | US 链路 | CN 链路 | 说明 |
|------|--------|--------|------|
| 实时单点价格 | **Schwab** → IB → Polygon → yfinance → Qwen | AkShare → Qwen | 新增 Schwab 为首选 |
| 批量持仓刷新 | **Schwab get_quotes 批量** → (不走 fallback，走单查链路) | AkShare 串并行 | **性能关键路径** |
| 历史 K 线（图表） | **Schwab price_history** → yfinance → Polygon | AkShare | TradingView Widget 方案不变，但 `/api/chart` 后端取数切 Schwab |
| 历史 K 线（回测） | yfinance（主）→ Schwab（备） | AkShare | 回测需大批量且不限流友好，yfinance 仍更合适；**Schwab 作为 free-tier 回填的备选** |
| 基本面 | yfinance → IB（不变） | AkShare | Schwab **不提供** |
| 新闻 | Polygon → yfinance（不变） | AkShare | Schwab 新闻能力有限，不迁移 |
| 期权链 | **Schwab（新）** | — | 项目现在没有，P2 新能力 |
| 账户数据 | **Schwab（新，只读）** | — | 项目现在没有，P2 新能力 |

### 3.2 云端 vs 本地部署

| 部署 | IB | Schwab | yfinance | Qwen |
|------|-----|--------|----------|------|
| 本地（Mac） | ✅ | ✅ | ✅ | ✅ |
| Railway 云 | ❌ | ✅ | ✅ | ✅ |

**价值点**：Schwab 是**第一个在云端可用的真实时源**。本地/云配置差异统一为 `providers.schwab_enabled` 单开关。

---

## 四、模块设计

### 4.1 `data/schwab_provider.py`（新建）

```python
class SchwabProvider:
    """Schwab Trader API data provider — OAuth-based, US market only."""

    def __init__(self, config: dict):
        self._cfg = config.get("schwab", {})
        self._enabled = self._cfg.get("enabled", False)
        self._app_key = self._cfg.get("app_key") or os.getenv("SCHWAB_APP_KEY", "")
        self._app_secret = self._cfg.get("app_secret") or os.getenv("SCHWAB_APP_SECRET", "")
        self._token_path = self._cfg.get("token_path", "data/schwab_token.json")
        self._client: Client | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._app_key) and os.path.exists(self._token_path)

    def _get_client(self):
        if self._client is None:
            from schwab.auth import client_from_token_file
            self._client = client_from_token_file(
                token_path=self._token_path,
                api_key=self._app_key,
                app_secret=self._app_secret,
            )
        return self._client

    # ── 单标的 ──
    def get_stock_price(self, ticker: str) -> dict | None: ...

    # ── 批量（关键新能力）──
    def get_stock_price_batch(self, tickers: list[str]) -> dict[str, dict]:
        """一次请求 N 个 symbol，最多 500 个。Schwab 独有的省配额接口。"""
        if not tickers or not self.enabled:
            return {}
        try:
            resp = self._get_client().get_quotes(tickers[:500])
            raw = resp.json()  # {"AAPL": {...}, "TSLA": {...}}
            return {t: self._normalize_quote(t, raw[t]) for t in raw if t in tickers}
        except Exception as e:
            logger.warning("Schwab batch quote failed: %s", e)
            return {}

    # ── 历史 K 线 ──
    def get_stock_history(self, ticker: str, period: str, interval: str) -> pd.DataFrame | None: ...

    # ── 账户（P2）──
    def get_account_positions(self, account_hash: str) -> list[dict]: ...
    def get_account_orders(self, account_hash: str) -> list[dict]: ...

    @staticmethod
    def _normalize_quote(ticker: str, raw: dict) -> dict:
        """Schwab schema → 项目内部 quote schema。"""
        q = raw.get("quote", {})
        return {
            "ticker": ticker,
            "last": q.get("lastPrice"),
            "close": q.get("closePrice"),
            "bid": q.get("bidPrice"),
            "ask": q.get("askPrice"),
            "high": q.get("highPrice"),
            "low": q.get("lowPrice"),
            "volume": q.get("totalVolume"),
            "source": "schwab",
            "timestamp": q.get("quoteTime"),
        }
```

**同形接口约束**：`get_stock_price` / `get_stock_history` 与 `IBProvider` / `YFinanceProvider` / `PolygonProvider` 方法签名保持一致，保证 `DataManager` 链路只加一行分支，不改调用方。

### 4.2 `data/data_manager.py`（修改）

```diff
 def __init__(self, config: dict):
     self._ib = IBProvider(config)
+    self._schwab = SchwabProvider(config)
     self._polygon = PolygonProvider(config)
     ...
-    self._fail_count = {"ib": 1, "polygon": 1}
+    self._fail_count = {"ib": 1, "polygon": 1, "schwab": 0}

 def get_price(self, ticker, market=None):
     if market == "cn":  # 不变
         ...
+    # US 链路：Schwab 优先
+    if (providers.get("schwab_enabled", True) and self._schwab.enabled
+            and not self._is_skipped("schwab")):
+        result = self._schwab.get_stock_price(ticker)
+        if result:
+            self._record_success("schwab")
+            return result
+        self._record_fail("schwab")
     # 以下 IB/Polygon/yfinance/Qwen 链路不变
```

### 4.3 `portfolio/manager.py`（性能关键改造）

```diff
 def get_holdings(self) -> list[dict]:
     positions = self._db.get_all_positions()
     if not positions:
         return []
-    # 并行单查 N 次
-    with ThreadPoolExecutor(...) as pool: ...
+    # 优先：Schwab 一次批量
+    us_tickers = [p.ticker for p in positions if p.market == "us"]
+    schwab_prices = {}
+    schwab = self._data_manager._schwab
+    if schwab.enabled and us_tickers:
+        schwab_prices = schwab.get_stock_price_batch(us_tickers)
+
+    # 对未命中的 ticker 走原有 fallback 链路并行
+    missing = [p for p in positions if p.ticker not in schwab_prices]
+    with ThreadPoolExecutor(...) as pool: ...
```

**效果**：15 支持仓在启用 Schwab 后从 15 次单查 → 1 次批量，Dashboard 首屏加载时延预估从 3-8s 降至 <500ms。

### 4.4 `data/data_router.py`（修改）

```diff
 routing = (config.get("data_routing") or {})
 self._primary = routing.get("primary", "qwen")
+self._realtime_primary = routing.get("realtime_primary", "schwab")

 def get_price(self, ticker, market=None):
     cached = self._cache_get("price_quote", ticker)
     if cached is not None:
         return cached
+    # 实时报价首选 Schwab
+    if self._realtime_primary == "schwab" and self._schwab.enabled:
+        q = validate_quote(self._schwab.get_stock_price(ticker))
+        if q:
+            self._cache_set("price_quote", ticker, q)
+            return q
     # Qwen / yfinance / AkShare 兜底链路不变
```

### 4.5 配置项（`config/default_config.yaml`）

```yaml
schwab:
  enabled: false
  app_key: ""                # 或 env SCHWAB_APP_KEY
  app_secret: ""             # 或 env SCHWAB_APP_SECRET
  callback_url: "https://127.0.0.1:8182"
  token_path: "data/schwab_token.json"
  account_hash: ""           # 可选；设置后 P2 账户端点激活

providers:
  schwab_enabled: true       # 主开关，默认 on 但需 schwab.enabled+token 才生效

data_routing:
  realtime_primary: "schwab" # 新增；"schwab" | "qwen" | "local"
```

---

## 五、OAuth 引导流程（Web 端点版）

**改动原因（v1.1）**：原方案的本地命令行 + 127.0.0.1 监听器在中国本土网络环境下被代理工具(Clash/Surge)劫持 `api.schwabapi.com` 到 198.18.0.0/15 段,SSL 握手超时无法完成。改为 **Web 公网回调**,把 OAuth 引导彻底搬到 Railway:Railway 数据中心直连 Schwab API,不受本地代理影响。

### 5.1 一次性配置

#### Step 1 — Schwab Developer Portal

在 [developer.schwab.com](https://developer.schwab.com) 创建 Individual Developer App:

- **Callback URL**: `https://<railway-domain>/oauth/schwab/callback`(精确,大小写斜杠)
- 提交 → 等 Schwab 审核(几小时到 1-2 天) → 状态变 "Ready for Use" → 拿到 `App Key` 和 `App Secret`

#### Step 2 — Railway Variables

```
SCHWAB_APP_KEY=<App Key>
SCHWAB_APP_SECRET=<App Secret>
SCHWAB_CALLBACK_URL=https://<railway-domain>/oauth/schwab/callback
SCHWAB_OAUTH_SECRET=<openssl rand -hex 16>
SCHWAB_TOKEN_PATH=/app/data/schwab_token.json
```

#### Step 3 — 浏览器一键授权

部署生效后访问:

```
https://<railway-domain>/oauth/schwab/start?secret=<SCHWAB_OAUTH_SECRET>
```

流程:
1. magic-link 校验 `secret` query → ok
2. `schwab.auth.get_auth_context(api_key, callback_url)` 生成 state + auth URL
3. state 存 Flask session(签名 cookie)
4. 302 重定向到 `https://api.schwabapi.com/v1/oauth/authorize?...`
5. 用户在 Schwab 登录页输账号密码 → Allow
6. Schwab 把 `?code=xxx&state=xxx` 回调到 `/oauth/schwab/callback`
7. callback 校验 state,调用 `client_from_received_url` 用 code 换 token
8. token 写入 `/app/data/schwab_token.json`(Persistent Volume)
9. 返回 `{"status": "ok", "token_path": "..."}`

### 5.2 验证

```
GET https://<railway-domain>/api/schwab/diagnose?secret=<SCHWAB_OAUTH_SECRET>
```

返回:
```json
{
  "enabled": true,
  "token_age_days": 0.001,
  "single_quote_ok": true,
  "single_quote_latency_ms": 230,
  "single_quote_sample": {"ticker": "AAPL", "last": 175.20, "close": 174.80},
  "batch_quote_ok": true,
  "batch_quote_count": 5,
  "batch_quote_latency_ms": 380,
  "history_ok": true,
  "history_bars": 22,
  "history_latency_ms": 450
}
```

### 5.3 7 天 refresh-token 续期策略

Schwab 平台硬性要求 refresh-token 每 7 天人工重新授权(不是 schwab-py 缺陷)。

| 时机 | 监控/动作 |
|------|----------|
| token 文件年龄 < 5 天 | 正常运行,access-token 自动 refresh |
| 5-6 天 | `/api/provider-probe` 返回 `schwab.token_age_days >= 5`,前端 banner 提示 |
| 6-7 天 | scheduler 触发邮件/Telegram 告警 |
| > 7 天 | refresh-token 失效 → schwab-py 调用抛错 → SchwabProvider 失败计数 → DataManager 自动跳过 → 链路降级 yfinance/Qwen |

续期 = 重新访问 `/oauth/schwab/start?secret=...` 一次,token.json 被覆盖。

### 5.4 端点清单

| 路由 | 用途 | 鉴权 |
|------|------|------|
| `GET /oauth/schwab/start?secret=<S>` | 启动 OAuth,302 到 Schwab | magic-link secret |
| `GET /oauth/schwab/callback?code=...&state=...` | 接 Schwab 回调,换 token | state 校验 |
| `GET /api/schwab/diagnose?secret=<S>` | 跑 single + batch + history smoke,报告 token age | magic-link secret |
| `GET /api/provider-probe` | 包含 schwab 一项,显示 ok / latency / token_age | 普通登录用户(系统页) |

**安全设计**:
- magic-link `secret` 是 32 字符随机串,放 env 变量,不入 git
- callback URL 在 Schwab Portal 锁定到 Railway 域名,即便 secret 泄露,攻击者也拿不到 code(Schwab 不会回调到陌生域名)
- state 参数用 Flask 签名 cookie 存,防 CSRF

---

## 六、分阶段交付计划

### P0 — SchwabProvider 基础实现（1-2 天）

| 任务 | 产物 | 验收 |
|------|------|------|
| 安装 schwab-py | `requirements.txt` 新增 `schwab-py>=1.4` | `pip install` 成功 |
| OAuth 引导脚本 | `data/schwab_auth_bootstrap.py` | 本地跑通拿到 token.json |
| SchwabProvider 类 | `data/schwab_provider.py` + `tests/test_schwab_provider.py` | 单测 mock `schwab-py` 客户端覆盖 get_stock_price / batch / history / 异常分支；覆盖率 ≥ 85% |
| 配置扩展 | `config/default_config.yaml` | 示例配置 + env var 文档 |
| Provider probe 加 schwab | `web/app.py::_provider_probe` 增一项 | `/api/provider-probe` 返回 schwab latency |

### P1 — 实时链路重排（半天）

| 任务 | 产物 | 验收 |
|------|------|------|
| DataManager 插入 schwab | diff ≈ 15 行 | `get_price("AAPL")` 在启用时走 schwab；单测覆盖失败熔断 |
| DataRouter 插入 schwab | diff ≈ 10 行 | `realtime_primary=schwab` 分支走通 |
| PortfolioManager 批量化 | [portfolio/manager.py](../../stock_trading_system/portfolio/manager.py) `get_holdings` 改造 | 15 持仓 Dashboard 首屏 < 500ms（启用 Schwab 时）；禁用时回退原 ThreadPool 路径 |
| Token 过期监控 | scheduler 每日任务 | token 年龄 > 5 天触发 alert |

### P2 — 账户只读对账（独立 PR，1-2 天）

| 任务 | 产物 |
|------|------|
| SchwabProvider 加账户方法 | `get_account_positions` / `get_account_orders` / `get_account_transactions` |
| 新 API 端点 | `/api/account/schwab/positions`、`/orders`、`/transactions` |
| 前端对账视图 | Dashboard 新增"Schwab 实盘 vs 手工录入"对比面板 |

**红线**：P2 只读，不触碰 `PortfolioManager` 写入路径。手工 portfolio 数据保持为 source-of-truth。

### P3 — 下单能力（独立设计文档）

不在本方案范围。真金白银写入必须单独走审批 + 双重确认 + 限额 + 审计日志，单独起 `docs/design/schwab-trading.md`。

### P4 — WebSocket 实时推送（独立 PR）

- `SchwabStreamer` 类包 `schwab.streaming.StreamClient`。
- 独立 asyncio 线程管理订阅生命周期。
- 推送目标：已有 socketio `realtime_quote` 频道（替换 dashboard 轮询）。
- 重连策略：Railway 重启后 `on_startup` 自动恢复订阅列表。

---

## 七、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Refresh token 7 天过期未续 | Schwab 链路全失效 | 分级告警（§5.3）+ 自动降级 yfinance |
| 限流 120 req/min 被撞 | 5xx / 429 | `portfolio.get_holdings` 必走批量；熔断阈值 `_SKIP_THRESHOLD` 保持 1 |
| schwab-py upstream 变更 | 集成脆弱 | pin 版本 `schwab-py>=1.4,<2`；单测 mock 减少对真 API 依赖 |
| 多租户 NBBO 合规 | 数据不可二次分发 | 当前系统是单租户手工账户；若开启多租户，每用户各自跑 OAuth，不共享 token |
| OAuth 回调端口占用 | 首次授权失败 | `callback_url` 配置化；schwab-py 有 port 探测 |
| token.json 泄漏 | Schwab 账户被操纵 | 文件权限 600；Railway 走 Secret Volume；`.gitignore` 加 `*_token.json` |
| IB 与 Schwab 持仓口径差异 | 对账错乱 | P2 明确"Schwab=实盘、手工=计划"语义，UI 上分栏展示 |

---

## 八、测试策略

### 8.1 单元测试（pytest）

- `test_schwab_provider.py`：mock `schwab-py` 客户端，覆盖
  - 正常 quote / batch / history
  - `enabled` 门闩（无 token 文件、app_key 空）
  - 异常路径（401 / 429 / 网络超时）返回 None 不抛
- `test_data_manager_schwab.py`：mock SchwabProvider，验证 US 链路 schwab → ib 熔断顺序
- `test_portfolio_batch.py`：验证 `get_holdings` 走批量路径且未命中回退单查

### 8.2 集成测试（需真 token，手动）

- `tests/integration/test_schwab_live.py`：`@pytest.mark.live_schwab` 标记，CI 跳过，本地用真 token 跑一次 smoke。

### 8.3 回归验证矩阵

| 场景 | 启用 Schwab | 禁用 Schwab |
|------|:----------:|:-----------:|
| `/api/price/AAPL` | Schwab | yfinance / Qwen |
| `/api/quote/AAPL` | Schwab | yfinance / Qwen |
| `/api/chart/AAPL?period=1mo` | Schwab → yfinance | yfinance |
| `/api/portfolio/holdings`（10 US 支） | 1 次批量 | N 次 ThreadPool |
| `/api/provider-probe` | schwab 有值 | schwab 字段缺失 |
| Token 过期 | 自动降级 yfinance + banner | N/A |

---

## 九、开放问题（评审确认）

1. **CN 股处理**：Schwab 仅支持 US；CN 依旧走 AkShare，不变。✅
2. **双轨 DataManager/DataRouter 是否统一**：本次**不统一**，两边对称改 diff 最小；合并方案另起 ticket。
3. **P2 账户对账是否必要**：建议做，可验证手工 portfolio 的准确性；如用户暂不需要可跳过。
4. **Schwab sandbox**：Schwab 目前无 sandbox，测试需用真账号小额数据；引导脚本加警告。
5. **多账户支持**：一期只支持单 `account_hash`，多账户留 P2+。

---

## 十、决策清单（待用户确认）

| # | 决策 | 默认建议 |
|---|------|---------|
| D1 | 本次是否同时推进 P0 + P1？ | ✅ 建议一起，价值最大化 |
| D2 | P2 账户只读是否并入本次范围？ | 建议**独立 PR**，本次只做 P0+P1 |
| D3 | 回测历史数据是否也切 Schwab？ | **不切**，yfinance 对大批量更友好 |
| D4 | 是否同步治理 screener v2 / paper_trader 绕过 DataRouter 直调 yfinance 的技术债？ | 建议**不在本次**，另起 ticket |
| D5 | 多租户合规（NBBO 不可分发）是否现在处理？ | 当前单租户，**不需要**；多租户上线前必须处理 |
