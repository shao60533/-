# 设计方案：LLM API 切换为 OpenRouter（聚合层 + 灵活模型切换）

| 项 | 值 |
|---|---|
| Feature | `llm-openrouter` |
| 版本 | v1.0 |
| 日期 | 2026-05-05 |
| 关联文档 | [model-switch v1.0](./model-switch.md)（本文继承其 router/UI/优先级架构） |
| 战略路线 | **C** —— 加 OpenRouter 为第三 provider 并默认走 OR；保留 Qwen/Gemini 直连作快路/大陆 fallback |

---

## 1. 背景与本质

[model-switch v1.0](./model-switch.md) 已经把"哪个 LLM 在跑"抽象成单一真源（`get_active_provider()`）+ env/user/config 优先级链，但仅支持 **qwen / gemini** 两态。本期诉求：

> 把 LLM API 换成 OpenRouter，灵活切换聚合层模型；deep 主用 `deepseek-v4-pro` / `gemini-3.1-pro-preview`，quick 走性价比的 `deepseek-v4-flash`。

**问题的本质** = 聚合层（OpenRouter）和直连层（Qwen/Gemini）是不同抽象等级的事物：聚合层一个 key 解锁 100+ 模型，直连层一个 key 一个 vendor。把"二选一 provider"扩成"二选一 provider + 聚合层下 N 个 model preset"是一次抽象升级，不是简单的 if 分支扩展。

**不做**：
- 删 Qwen/Gemini 直连路径（保留作低延迟/免费/大陆兜底）
- 应用层 LangChain `RunnableWithFallbacks` 三级 fallback（v1.0 仅靠 OR 内部 `provider_order` 跨 vendor 路由）
- 功能级 overrides（nl_parser / RenderingExtractor / roundtable 各用不同模型）—— v1.0 仅做全局 deep/quick 两挡
- 多租户 per-user OR key（全局 key，与现有 qwen/gemini 一致）

---

## 2. 现有 LLM 调用面审计

### 2.1 调用面（5 处，本期改造点）

| # | 文件:行 | 用途 | 当前形态 | 改造点 |
|---|---|---|---|---|
| 1 | [`llm/router.py`](../../stock_trading_system/llm/router.py) | `get_active_provider()` + `has_provider_key()` + `resolve_active_model()` | `Provider = Literal["qwen","gemini"]` | 扩 `"openrouter"` + 新增 `resolve_openrouter_model(role, feature?)` |
| 2 | [`llm/constants.py`](../../stock_trading_system/llm/constants.py) | `VALID_PROVIDERS = {"qwen","gemini"}` | 二态 | `+ "openrouter"` |
| 3 | [`llm/client.py`](../../stock_trading_system/llm/client.py) | `QwenTextClient` / `GeminiTextClient`（screener 内部 nl_parser/universe 用） | 工厂二选一 | 加 `OpenRouterTextClient`（继承 OpenAI-compatible） |
| 4 | [`screener/v3/guru_agents/base.py:355`](../../stock_trading_system/screener/v3/guru_agents/base.py) | `_get_chat_model(context)` 给 14 大师拿 LangChain ChatModel | qwen/gemini 二态 | 加 OR 分支（复用 `langchain_openai.ChatOpenAI`，换 base_url+key+model） |
| 5 | [`agents/analyzer.py`](../../stock_trading_system/agents/analyzer.py) | TradingAgents graph：`_configure_qwen` / `_configure_gemini` + `_build_quick_llm` | 二态硬编码 | 加 `_configure_openrouter`；graph cache key 升级 `f"{provider}:{deep_id}:{quick_id}"` |

### 2.2 配置 + UI 面（4 处）

| # | 文件 | 改造 |
|---|---|---|
| 1 | [`config/default_config.yaml`](../../stock_trading_system/config/default_config.yaml) | 加 `openrouter:` slice（含 `presets: [...]` + `active: {deep, quick}`） |
| 2 | [`web/app.py`](../../stock_trading_system/web/app.py) `/api/settings/llm-provider` GET/POST | 三态化 + `has_openrouter_key`；新增 `/api/settings/openrouter/active` GET/POST |
| 3 | [`components/shared/LLMSwitcher.tsx`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) | 两段式：provider 选择 + role(deep/quick) preset 选择（仅 OR active 时展开） |
| 4 | [`islands/settings/SettingsPage.tsx`](../../stock_trading_system/web/frontend/src/islands/settings/SettingsPage.tsx) | OpenRouter section：api_key + http_referer + x_title + presets CRUD 表 |

### 2.3 关键复用（L0/L1）

- **TradingAgents 上游已原生支持 OR**：[`tradingagents/llm_clients/openai_client.py`](../../../../opt/anaconda3/lib/python3.12/site-packages/tradingagents/llm_clients/openai_client.py) 中 `_PROVIDER_CONFIG["openrouter"] = ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY")`，`validators.py` 对 openrouter 跳过严格 model 校验。结论：`_configure_openrouter` **不需要 monkey-patch**，仅 `ta_config["llm_provider"] = "openrouter"` 即可。
- **`langchain_openai.ChatOpenAI`** 已在依赖里（qwen 用的就是它）。OR 是 OpenAI-compatible，传 `base_url + api_key` 即可。
- **`openai` Python SDK** 已在依赖。
- **零新增依赖**。

---

## 3. OpenRouter API 契约要点

| 项 | 值 |
|---|---|
| Endpoint | `https://openrouter.ai/api/v1/chat/completions`（含 `/v1/models`，与 OpenAI 完全兼容） |
| Auth | `Authorization: Bearer <OPENROUTER_API_KEY>` |
| 推荐 Header（分析用，不强制） | `HTTP-Referer: <site_url>` + `X-Title: <app_name>` |
| Model 字符串 | `<vendor>/<model>` —— 如 `deepseek/deepseek-v4-pro`、`google/gemini-3.1-pro-preview` |
| 跨 vendor fallback | `extra_body={"provider": {"order": ["deepseek","novita"], "allow_fallbacks": True}}` |
| `with_structured_output(Schema)` | 通过 LangChain ChatOpenAI tool calling，OR 透传到底层 vendor —— 零额外改造 |
| 大陆访问 | 部分 ISP 可达；不可达时回退 Qwen 直连（C 路线保留 Qwen 的关键理由） |

---

## 4. 模型预设设计（核心抽象）

### 4.1 单一字符串 → 预设池 + 激活指针

把 `openrouter.deep_think_model = "..."` 这种**单值字段**升级为**预设列表 + 激活指针**：

```yaml
openrouter:
  enabled: false
  api_key: ""                                 # 或 env OPENROUTER_API_KEY
  base_url: "https://openrouter.ai/api/v1"
  http_referer: ""
  x_title: "StockAI Terminal"
  timeout: 120

  # 模型预设池 —— 用户可在 Settings UI 增删改
  presets:
    - id: "deepseek-v4-pro"
      label: "DeepSeek V4 Pro"
      model: "deepseek/deepseek-v4-pro"
      role: "deep"
      provider_order: ["deepseek", "novita"]
      kwargs: {}
    - id: "gemini-3.1-pro"
      label: "Gemini 3.1 Pro"
      model: "google/gemini-3.1-pro-preview"   # 注意:OR 上为 preview 后缀
      role: "deep"
      provider_order: ["google-ai-studio", "google-vertex"]
      kwargs: {}
    - id: "deepseek-v4-flash"
      label: "DeepSeek V4 Flash"
      model: "deepseek/deepseek-v4-flash"
      role: "quick"
      provider_order: ["deepseek", "novita", "fireworks"]
      kwargs: {}

  # 激活指针 —— 三个 role 各指向 preset.id
  active:
    deep:  "deepseek-v4-pro"
    quick: "deepseek-v4-flash"
```

### 4.2 选型理由（2026-05 OR 实价）

| 模型 | OR id | 价格 in/out per 1M | 上下文 | 用途 |
|---|---|---|---|---|
| **DeepSeek V4 Pro** | `deepseek/deepseek-v4-pro` | $0.435 / $0.87 | 1M | deep 默认（推理质量 + 极低单价） |
| **Gemini 3.1 Pro Preview** | `google/gemini-3.1-pro-preview` | $2 / $12 | 1M | deep 备选（多样性 / 跨厂商对照） |
| **DeepSeek V4 Flash** | `deepseek/deepseek-v4-flash` | $0.14 / $0.28 | 1M | quick 默认（与 deep 同 vendor，路由更稳；4× 便宜于 gemini-3.1-flash-lite） |

**模型名漂移风险**：preview 模型可能 GA 后改名（如 `google/gemini-3.1-pro` 上线、`-preview` 退役）。SettingsPage preset 表设计为**用户可编辑**，上游改名时用户改一行即可，不动代码。

### 4.3 预设解析函数

[`llm/router.py`](../../stock_trading_system/llm/router.py) 新增：

```python
def resolve_openrouter_model(
    config: dict, *, role: str, feature: str | None = None,
) -> dict:
    """Resolve active preset for (role, feature).

    role:    "deep" | "quick"
    feature: optional override key (v1.1; v1.0 ignored)

    Resolution order:
        1. active.overrides[feature]   (v1.1, not yet wired)
        2. active[role]                (global role default)
        3. first preset matching role  (yaml fallback)
        4. hardcoded safe default      (never raises)

    Returns:
        {id, label, model, provider_order, kwargs}
    """
```

返回 dict 永不为 None，缺配置时退化到硬编码 `("deepseek-v4-flash-fallback", "deepseek/deepseek-v4-flash")` —— 系统永不因 preset 缺失拒绝启动。

---

## 5. 调用面接入

### 5.1 Provider 三态（router/constants）

[`llm/constants.py`](../../stock_trading_system/llm/constants.py)：
```python
VALID_PROVIDERS = frozenset({"qwen", "gemini", "openrouter"})
```

[`llm/router.py`](../../stock_trading_system/llm/router.py)：
- `Provider = Literal["qwen", "gemini", "openrouter"]`
- `has_provider_key(cfg, "openrouter")` 检查 env `OPENROUTER_API_KEY` 或 `cfg.openrouter.api_key`
- `resolve_active_model(cfg, user_id)` openrouter 分支调 `resolve_openrouter_model(cfg, role="deep")["model"]`
- `get_active_provider` legacy auto-detect 链尾加：env `OPENROUTER_API_KEY` 在场 + 无更高优先级配置 → `"openrouter"`（高于 qwen），让 cloud 部署只配一个 env 即生效

### 5.2 OpenRouterTextClient（screener 内部 text-in/out）

[`llm/client.py`](../../stock_trading_system/llm/client.py) 新增（与 `QwenTextClient` 同骨架，OpenAI-compatible）：

```python
class OpenRouterTextClient:
    provider_name = "openrouter"

    def __init__(self, config: dict) -> None:
        from openai import OpenAI
        or_cfg = config.get("openrouter") or {}
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or or_cfg.get("api_key", "")
        )
        if not api_key:
            raise RuntimeError(
                "OpenRouter selected but openrouter.api_key is empty "
                "(and no OPENROUTER_API_KEY env)"
            )
        # 使用 quick preset(text-in/out 一般用于轻量任务)
        from stock_trading_system.llm.router import resolve_openrouter_model
        preset = resolve_openrouter_model(config, role="quick")
        self._model = preset["model"]
        self._provider_order = preset.get("provider_order") or []

        default_headers = {}
        if or_cfg.get("http_referer"):
            default_headers["HTTP-Referer"] = or_cfg["http_referer"]
        if or_cfg.get("x_title"):
            default_headers["X-Title"] = or_cfg["x_title"]

        self._client = OpenAI(
            api_key=api_key,
            base_url=or_cfg.get("base_url", "https://openrouter.ai/api/v1"),
            default_headers=default_headers or None,
        )

    def chat(self, *, system, user, json_mode=False, timeout=60) -> str:
        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "timeout": timeout,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._provider_order:
            kwargs["extra_body"] = {
                "provider": {
                    "order": self._provider_order,
                    "allow_fallbacks": True,
                },
            }
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
```

`get_text_client(config)` factory 新增 openrouter 分支。

### 5.3 LangChain ChatModel for 14 大师 / RenderingExtractor

[`screener/v3/guru_agents/base.py:355`](../../stock_trading_system/screener/v3/guru_agents/base.py) `_get_chat_model(context)` 加：

```python
elif provider == "openrouter":
    from langchain_openai import ChatOpenAI
    from stock_trading_system.llm.router import resolve_openrouter_model

    or_cfg = config.get("openrouter", {})
    api_key = os.environ.get("OPENROUTER_API_KEY") or or_cfg.get("api_key", "")
    preset = resolve_openrouter_model(config, role="deep")  # 14 大师走 deep

    headers = {}
    if or_cfg.get("http_referer"): headers["HTTP-Referer"] = or_cfg["http_referer"]
    if or_cfg.get("x_title"):      headers["X-Title"] = or_cfg["x_title"]

    extra_body = {}
    if preset["provider_order"]:
        extra_body["provider"] = {
            "order": preset["provider_order"],
            "allow_fallbacks": True,
        }

    return ChatOpenAI(
        model=preset["model"],
        api_key=api_key,
        base_url=or_cfg.get("base_url", "https://openrouter.ai/api/v1"),
        default_headers=headers or None,
        timeout=or_cfg.get("timeout", 120),
        extra_body=extra_body or None,
        **preset.get("kwargs", {}),
    )
```

`with_structured_output(GuruSignal)` 通过 ChatOpenAI tool calling 自动走，OR 透传到 vendor —— 零额外改造。

### 5.4 TradingAgents graph（`_configure_openrouter`）

[`agents/analyzer.py`](../../stock_trading_system/agents/analyzer.py)：

```python
def _configure_openrouter(self, ta_config: dict) -> None:
    from stock_trading_system.llm.router import resolve_openrouter_model

    or_cfg = self._config.get("openrouter", {})
    api_key = os.environ.get("OPENROUTER_API_KEY") or or_cfg.get("api_key", "")
    if not api_key:
        raise RuntimeError("llm_provider=openrouter but openrouter.api_key is empty")
    os.environ["OPENROUTER_API_KEY"] = api_key  # tradingagents factory reads from env

    deep  = resolve_openrouter_model(self._config, role="deep")
    quick = resolve_openrouter_model(self._config, role="quick")

    ta_config["llm_provider"]    = "openrouter"   # upstream _PROVIDER_CONFIG already registered
    ta_config["deep_think_llm"]  = deep["model"]
    ta_config["quick_think_llm"] = quick["model"]
    ta_config["backend_url"]     = or_cfg.get("base_url", "https://openrouter.ai/api/v1")
    ta_config["llm_deep_kwargs"]  = {"timeout": 600}
    ta_config["llm_quick_kwargs"] = {"timeout": 120}
    # 推荐 headers (TradingAgents 是否消费见上游;不消费不会报错)
    headers = {}
    if or_cfg.get("http_referer"): headers["HTTP-Referer"] = or_cfg["http_referer"]
    if or_cfg.get("x_title"):      headers["X-Title"] = or_cfg["x_title"]
    if headers:
        ta_config["llm_default_headers"] = headers
```

`_init_graph` 在 provider 分支补 `elif provider == "openrouter": self._configure_openrouter(ta_config)`。

**graph cache key 升级**（重要）：现有 `cache_key = provider` 在 OR 下会复用旧 graph、跑旧模型。改为：
```python
if provider == "openrouter":
    deep  = resolve_openrouter_model(self._config, role="deep")
    quick = resolve_openrouter_model(self._config, role="quick")
    cache_key = f"openrouter:{deep['id']}:{quick['id']}"
else:
    cache_key = provider or ""
```

### 5.5 `_build_quick_llm`（RenderingExtractor 用）

[`agents/analyzer.py:215`](../../stock_trading_system/agents/analyzer.py) 加 openrouter 分支，与 §5.3 同形态但 `role="quick"`。

### 5.6 Worker / Pipeline 透传

[`tasks/workers.py:458`](../../stock_trading_system/tasks/workers.py)：
```python
# 旧:provider = params.get("provider", "qwen")
# 新:
from stock_trading_system.llm.router import get_active_provider
provider = (
    params.get("provider")
    or get_active_provider(get_config(), user_id=params.get("user_id"))
)
```

[`screener/v3/pipeline.py:67`](../../stock_trading_system/screener/v3/pipeline.py) 默认值 `"qwen"` 改为 `None`（pipeline 内若 None 则调 router 解析）。

---

## 6. 后端 API 三态化

### 6.1 `/api/settings/llm-provider`（[`web/app.py:2438`](../../stock_trading_system/web/app.py)）

GET 响应增字段：
```json
{
  "active": "openrouter",
  "has_qwen_key": false,
  "has_gemini_key": false,
  "has_openrouter_key": true,
  "locked_by_env": false
}
```

POST `provider` 接受 `qwen | gemini | openrouter`；缺 key → 400 `{reason: "missing_api_key", message: "OpenRouter 未配置 API key"}`。

### 6.2 `/api/settings/openrouter/active`（新增）

```
GET  /api/settings/openrouter/active
→ {
    deep:  {id, label, model, provider_order, kwargs},
    quick: {...},
    presets: [...all presets...],
  }

POST /api/settings/openrouter/active
body: {role: "deep" | "quick", preset_id: "deepseek-v4-pro"}
→ 200 {active: {deep, quick}}
→ 400 {reason: "unknown_preset"} 当 preset_id 不在 presets 里
→ 409 {reason: "locked_by_env"} 当 LLM_PROVIDER env 锁定时(防止误改)
```

写回 yaml `openrouter.active.deep|quick`，触发 `_reset_config_dependent_singletons(["llm_provider"])` 让 graph cache 失效。

### 6.3 `/api/settings`（[`web/app.py:2177`](../../stock_trading_system/web/app.py)）

GET/POST 加 openrouter slice 读写：
- GET 时 `api_key` 掩码为 `***last4`（与 qwen/gemini 一致）
- POST 时 `api_key=""` 视为不修改（不清空）
- POST 接受 presets 数组替换（先做整体替换，CRUD 粒度操作 v1.1 再加）

### 6.4 `/api/diagnostics/providers`（[`web/app.py:3175`](../../stock_trading_system/web/app.py)）

加 openrouter 项：key 是否在场 + 最近一次调用 timestamp + 平均延迟。

---

## 7. 前端 UI

### 7.1 `<LLMSwitcher>` 两段式（[`components/shared/LLMSwitcher.tsx`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx)）

```
┌────────────────────────────────────────┐
│ ✨ 模型: OpenRouter ▼                  │  ← provider(qwen/gemini/openrouter)
│   ──────────────────────              │
│   深度: DeepSeek V4 Pro    ▼          │  ← role=deep preset(仅 OR 时显示)
│   快速: DeepSeek V4 Flash  ▼          │  ← role=quick preset
│   ──────────────────────              │
│   [⚙ 管理预设]                        │  ← /settings#openrouter
└────────────────────────────────────────┘
```

OR 不是 active provider 时下半段折叠，保持 qwen/gemini 现有视觉。

### 7.2 `<SettingsPage>` OpenRouter section

```
OpenRouter
─────────────────────────────────────
  API Key:      [sk-or-***last4   ] [显示] [清除]
  HTTP-Referer: [                 ]
  X-Title:      [StockAI Terminal ]
  ───── 模型预设 ──────────────────
  ┌──────────────────────────────────────────────────┐
  │ ★ deep:  DeepSeek V4 Pro    deepseek/deepseek... │ [编辑] [删除]
  │   deep:  Gemini 3.1 Pro     google/gemini-3.1... │ [编辑] [删除] [设默认]
  │ ★ quick: DeepSeek V4 Flash  deepseek/deepseek... │ [编辑] [删除]
  └──────────────────────────────────────────────────┘
  [+ 添加预设]
  ───── 测试 ─────────────────────
  [测试 deep ping]  [测试 quick ping]   ← 1-token hello
```

★ = 当前激活。"添加预设"弹窗 5 字段：id / label / model / role / provider_order(逗号分隔) / kwargs(JSON)。

---

## 8. 边界与风险

### 8.1 与 [model-switch v1.0](./model-switch.md) 的关系

完全沿用其架构（router 单一真源、env > user > config 优先级、`/api/settings/llm-provider` 端点、LLMSwitcher UI）。本期 = **三态扩展 + 聚合层 preset 层**，不重写。

### 8.2 OpenRouter 限流 / 故障应对

- **OR 内置 fallback**：`extra_body.provider.order = ["deepseek","novita"]` + `allow_fallbacks: True`，OR 在底层 vendor 故障时自动跨 vendor 切。配置在 preset 级。
- **应用层 fallback**：v1.0 **不做**。v1.1 评估 `RunnableWithFallbacks(OR_runnable, qwen_runnable)`，OR 整个挂掉时降级到 Qwen 直连。
- **超时**：deep 600s / quick 120s，与 qwen/gemini 一致。

### 8.3 模型名漂移

`google/gemini-3.1-pro-preview` 含 `-preview` 后缀；OR 上游 GA 后可能改名。SettingsPage preset 表设计为**用户可编辑**，改名时用户改一行 yaml/UI 即可，不动代码。

### 8.4 大陆访问

`openrouter.ai` 在大陆部分 ISP 可达。不可达时回退 Qwen 直连（这是选 C 不选 A 的关键理由）。`OPENROUTER_PROXY` env 留口子（v1.1 评估）。

### 8.5 graph cache 隔离

切 OR preset 后必须用新 graph 跑新模型。cache_key 升级为 `f"openrouter:{deep_id}:{quick_id}"` 解决。**测试覆盖**：切 deep preset 前后 `_init_graph` 创建新 graph 而非复用。

### 8.6 不动清单

- 数据层（DataRouter / Polygon / yfinance / Schwab）
- 多租户边界（`created_by` SQL，[v1.18 R-fix-12](./analysis-inbox.md)）
- analyzer/screener 业务逻辑 / prompt / 大师评分流程
- TradingAgents 上游包（不改 site-packages）
- Qwen/Gemini 直连路径（保留作快路 / 大陆 fallback）
- 现有 yaml + env 优先级链
- shadcn 组件 / Tailwind tokens

---

## 9. 测试

### 9.1 后端单测

`tests/test_llm_router_openrouter.py`：
1. `LLM_PROVIDER=openrouter` env → `get_active_provider()` = `"openrouter"`
2. 仅 `OPENROUTER_API_KEY` env 在场 + 无 LLM_PROVIDER + 无 user_settings + 无 config.llm_provider + 无 qwen.api_key → legacy auto-detect = `"openrouter"`
3. `has_provider_key(cfg, "openrouter")` env 优先于 config
4. `resolve_active_model(cfg)` provider=openrouter 时返回 `("openrouter", deep_preset.model)`

`tests/test_resolve_openrouter_model.py`：
1. `active.deep="deepseek-v4-pro"` + presets 含该项 → 返回该 preset
2. `active.deep` 指向不存在 preset id → 落到第一个 role=deep preset
3. presets 全空 → 硬编码 safe default（不抛）
4. preset `provider_order` 通过 `extra_body.provider.order` 透传到 ChatOpenAI（mock 检查）

`tests/test_openrouter_text_client.py`（mock `openai.OpenAI`）：
1. 缺 key（env + config 都空） → RuntimeError
2. 默认走 quick preset model
3. `chat()` 请求 base_url == `openrouter.ai/api/v1`；headers 含 `HTTP-Referer` 当 config 配了
4. `json_mode=True` → `response_format={"type":"json_object"}`
5. preset.provider_order 非空时 `extra_body.provider.order` 设置

`tests/test_analyzer_configure_openrouter.py`：
1. `_configure_openrouter(ta_config)` 设置 `llm_provider="openrouter"` / `backend_url=openrouter.ai/api/v1` / deep+quick model strings
2. 缺 key → RuntimeError
3. graph cache key 切 deep preset 前后变化（`openrouter:deepseek-v4-pro:deepseek-v4-flash` → `openrouter:gemini-3.1-pro:deepseek-v4-flash`）

`tests/test_settings_openrouter_active.py`：
1. `POST /api/settings/openrouter/active {role:"deep", preset_id:"gemini-3.1-pro"}` → 写回 yaml
2. preset_id 不存在 → 400 reason=`unknown_preset`
3. LLM_PROVIDER env 锁定时 → 409 reason=`locked_by_env`
4. 切换后 `_reset_config_dependent_singletons` 被调用

`tests/test_settings_llm_provider_endpoint_openrouter.py`：
1. POST `{provider:"openrouter"}` + key 在场 → 200, active=openrouter
2. POST `{provider:"openrouter"}` 无 key → 400 reason=missing_api_key
3. GET 返回 `has_openrouter_key`

### 9.2 前端单测

`LLMSwitcher.test.tsx`：
1. 三态下拉 + 缺 key 项显示"未配置" + disabled
2. 选 OpenRouter → POST `provider:"openrouter"`；toast "已切换到 OpenRouter"
3. active=openrouter 时下半段渲染 deep/quick 两个 dropdown
4. 切 deep preset → POST `/api/settings/openrouter/active {role:"deep", preset_id:...}`

`SettingsPage.openrouter.test.tsx`：
1. OR section 渲染 api_key + 3 字段 + presets 表 + 测试按钮
2. presets 表 ★ 标当前激活
3. 添加预设弹窗 5 字段提交 → POST `/api/settings` 含新 preset
4. api_key 显示掩码 `sk-or-***last4`

### 9.3 集成 / E2E

`tests/integration/test_screener_v3_openrouter.py`（CI gated by `OPENROUTER_API_KEY`）：
1. `LLM_PROVIDER=openrouter` + 1 大师 + 1 ticker → `screen_v3` worker 完整跑通，结果含 `GuruSignal` 结构化字段
2. RenderingExtractor 用 OR quick preset 抽 8 tab，`rendering_json` 非空

手动回归 checklist：
- [ ] `/settings` 配 OR key + 3 个 preset → 保存
- [ ] Header LLMSwitcher 切到 OpenRouter
- [ ] LLMSwitcher 下半段切换 deep preset 从 deepseek-v4-pro → gemini-3.1-pro
- [ ] 发起一次 `/analysis/AAPL` quick depth → 完整 7-agent 跑通，rendering_json 8 tab 齐
- [ ] 发起一次 `/screener-v3` agent_rt 模式 3 大师 → 圆桌结果非空
- [ ] `/api/diagnostics/providers` openrouter 健康
- [ ] 切回 Qwen → 下次分析用 Qwen，graph cache 命中

---

## 10. 实施顺序

| 步骤 | 工作 | 文件 | LOC |
|---|---|---|---|
| 1 | constants 三态 + router 三态 + 4 单测 | `llm/constants.py`, `llm/router.py`, tests | ~50 |
| 2 | `resolve_openrouter_model` + `_normalize_preset` + 4 单测 | `llm/router.py`, tests | ~80 |
| 3 | `OpenRouterTextClient` + `get_text_client` 三态 + 5 单测 | `llm/client.py`, tests | ~80 |
| 4 | `default_config.yaml` openrouter slice + 3 个默认 preset | `config/default_config.yaml` | ~30 |
| 5 | `guru_agents/base.py:_get_chat_model` OR 分支 | `screener/v3/guru_agents/base.py` | ~25 |
| 6 | `analyzer.py:_configure_openrouter` + `_build_quick_llm` OR 分支 + graph cache key 升级 + 3 单测 | `agents/analyzer.py`, tests | ~70 |
| 7 | `tasks/workers.py` + `screener/v3/pipeline.py` provider 默认值改读 router | workers.py, pipeline.py | ~10 |
| 8 | `/api/settings/llm-provider` 三态 + 3 单测 | `web/app.py`, tests | ~40 |
| 9 | `/api/settings/openrouter/active` GET/POST + 4 单测 | `web/app.py`, tests | ~60 |
| 10 | `/api/settings` openrouter slice 读写 + 掩码 | `web/app.py` | ~30 |
| 11 | `/api/diagnostics/providers` openrouter 项 | `web/app.py` | ~20 |
| 12 | `LLMSwitcher.tsx` 两段式 + 4 vitest case | `components/shared/LLMSwitcher.tsx`, tests | ~100 |
| 13 | `SettingsPage.tsx` OR section + presets 表 + 4 vitest case | `islands/settings/SettingsPage.tsx`, tests | ~220 |
| 14 | 手动回归 | — | — |
| **合计** | | | **~815 LOC** + ~600 行 doc/changelog |

每步独立 commit，独立回滚单位。

---

## 11. 复用 / Reuse 阶梯（[engineering-principles.md](../engineering-principles.md) L0→L4）

- **L0 项目内**：[model-switch v1.0](./model-switch.md) 单一真源链 / `LLMTextClient` Protocol / TradingAgents graph cache / LLMSwitcher UI / SettingsPage form / `/api/diagnostics/providers` / `_reset_config_dependent_singletons` 重置链 / shadcn Switcher 组件
- **L1 依赖库**：`langchain_openai.ChatOpenAI`（已 deps）+ `openai` SDK（已 deps）+ TradingAgents 上游 `_PROVIDER_CONFIG["openrouter"]`（site-packages 已注册）—— **零新增依赖**
- **L4 必须自写**：~815 LOC 胶水（router 三态 + preset 解析 + OR client + provider config + UI 两段式 + 测试），0 业务逻辑

---

## 12. 决策（已确认 2026-05-05）

| # | 项 | 选择 |
|---|---|---|
| 1 | 战略路线 | **C** — 加 OR 默认走，保留 Qwen/Gemini 直连 |
| 2 | Quick 默认 | `deepseek/deepseek-v4-flash` ($0.14/$0.28 per 1M) |
| 3 | Deep 默认 | `deepseek/deepseek-v4-pro` ($0.435/$0.87) |
| 4 | Deep 备选 | `google/gemini-3.1-pro-preview` ($2/$12) |
| 5 | 预设池规模 v1.0 | 3 项（deep×2 + quick×1），用户可在 Settings 里加 |
| 6 | 功能级 overrides | v1.0 不做 |
| 7 | 应用层三级 fallback | v1.0 不做（仅靠 OR `provider_order`） |

---

*v1.0 设计稿 — 等待确认后开始实施*
