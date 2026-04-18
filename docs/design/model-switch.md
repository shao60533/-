# 技术方案：全局模型切换（Qwen ↔ Gemini）

| 项 | 值 |
|---|---|
| Feature | `model-switch` |
| 版本 | v1.0 |
| 日期 | 2026-04-18 |
| 关联 PRD | [../prd/model-switch.md](../prd/model-switch.md) |
| 关联测试用例 | [../test-cases/model-switch.md](../test-cases/model-switch.md) |

## 1. 背景

详见 [PRD §1](../prd/model-switch.md#1-背景)。一句话：把"有 Qwen key 就用 Qwen"的硬编码，改成可运行时切换的全局开关。

### 现有代码现状速查

| 位置 | 作用 | 问题 |
|---|---|---|
| [analyzer.py:97-145](../../stock_trading_system/agents/analyzer.py) | TradingAgents 7-agent pipeline 的 provider 分支 | 硬编码 `if qwen_key: ... else: ...` |
| [config/settings.py:75-78](../../stock_trading_system/config/settings.py) | env var 自动启用 Qwen | 无显式 `llm_provider` 字段 |
| [screener/v2/nl_parser.py:114](../../stock_trading_system/screener/v2/nl_parser.py) | NL → FilterSpec | 直接 `QwenProvider(config)` |
| [screener/v2/universe.py:41](../../stock_trading_system/screener/v2/universe.py) | Layer A 股池筛选 | 直接 `QwenProvider(config)` |
| [screener/screener.py:90-91](../../stock_trading_system/screener/screener.py) | AI tier-3 评分 | 硬编码分支 |

## 2. 设计目标

1. **单一真源**：一个函数 `get_active_provider(config) -> Literal["qwen", "gemini"]`，全系统唯一事实来源。
2. **优先级清晰**：`env var > user config > legacy 自动探测`。三层明确、可追溯。
3. **最小侵入**：不重写 analyzer 主逻辑，只在 provider 分支前加一个 "resolve → branch" 的 gate。
4. **零迁移**：现有用户不改 yaml、不加 env 的情况下，行为完全不变。
5. **抽象留口子**：新增 `LLMTextClient` Protocol，为 nl_parser / universe 解耦 Qwen 硬依赖，同时为未来 Claude/GPT 扩展留通道。
6. **热切换**：切换后**下次** `_init_graph()` 读新 provider，不重启进程。

### 非目标（见 [PRD §3.2](../prd/model-switch.md#32-out-of-scope不做)）

数据层切换、临时覆盖、多用户、自动 failover 均不做。

## 3. 方案总览

```
          ┌──────────────────────────┐
          │   Nav dropdown / Settings │   (前端 UI)
          │   "模型: [Qwen ▼]"        │
          └───────────┬──────────────┘
                      │ POST /api/settings/llm-provider
                      ▼
          ┌──────────────────────────┐
          │  web/app.py route        │
          │  - validate provider     │
          │  - check target key exists│
          │  - check env lock        │
          │  - save_config({...})    │
          └───────────┬──────────────┘
                      │ yaml atomic write
                      ▼
          ┌──────────────────────────┐
          │  ~/.stock_trading/config │
          │  llm_provider: "gemini"  │
          └───────────┬──────────────┘
                      │ next load_config()
                      ▼
  ┌───────────────────┴───────────────────────────────────────┐
  │          config/llm_router.py (NEW)                       │
  │                                                           │
  │   def get_active_provider(config) -> "qwen" | "gemini":   │
  │       1. env LLM_PROVIDER if set                          │
  │       2. config["llm_provider"] if set                    │
  │       3. legacy: has qwen key? -> qwen, else gemini       │
  │                                                           │
  │   def get_text_client(config) -> LLMTextClient:           │
  │       return QwenTextClient | GeminiTextClient            │
  └───────────────────┬───────────────────────────────────────┘
                      │ consumed by ↓
  ┌───────────────────┴─────────────────────────────────────┐
  │                                                         │
  ▼                         ▼                  ▼            ▼
analyzer.py          nl_parser.py      universe.py    screener.py
_init_graph()        parse()           filter()       evaluate()
```

## 4. 关键设计

### 4.1 新模块：`stock_trading_system/llm/`

现有没有 `llm/` 目录。本方案引入：

```
stock_trading_system/llm/
├── __init__.py
├── router.py          # get_active_provider / lock checks
├── client.py          # LLMTextClient Protocol + Qwen/Gemini impls
└── constants.py       # VALID_PROVIDERS, env var names
```

理由：

- 不放 `config/` —— 配置模块职责是加载/保存，不该解析语义；
- 不放 `agents/` —— agents 是 TradingAgents wrapper，层次偏业务；
- `llm/` 独立层，对应"选哪家模型"这一横切关注点。

### 4.2 Provider 解析函数（核心）

```python
# stock_trading_system/llm/router.py
from __future__ import annotations

import os
from typing import Literal

from stock_trading_system.llm.constants import (
    VALID_PROVIDERS, ENV_LLM_PROVIDER,
)
from stock_trading_system.utils import get_logger

logger = get_logger("llm.router")

Provider = Literal["qwen", "gemini"]


def get_active_provider(config: dict) -> Provider:
    """Single source of truth. Resolve which LLM provider is active.

    Priority:
        1. env LLM_PROVIDER (deployment override; never persisted)
        2. config["llm_provider"] (user setting from yaml)
        3. legacy auto-detect: qwen key present -> qwen, else gemini
    """
    # 1. env var
    env_val = os.environ.get(ENV_LLM_PROVIDER, "").strip().lower()
    if env_val in VALID_PROVIDERS:
        return env_val  # type: ignore[return-value]
    if env_val and env_val not in VALID_PROVIDERS:
        logger.warning(
            "Ignoring unknown LLM_PROVIDER=%r (valid: %s)",
            env_val, sorted(VALID_PROVIDERS),
        )

    # 2. config
    cfg_val = (config.get("llm_provider") or "").strip().lower()
    if cfg_val in VALID_PROVIDERS:
        return cfg_val  # type: ignore[return-value]
    if cfg_val and cfg_val not in VALID_PROVIDERS:
        logger.warning(
            "Ignoring unknown config.llm_provider=%r", cfg_val,
        )

    # 3. legacy auto-detect
    has_qwen = bool((config.get("qwen") or {}).get("api_key"))
    return "qwen" if has_qwen else "gemini"


def is_provider_locked_by_env() -> bool:
    """True if LLM_PROVIDER env var is set to a valid value.
    UI disables the switch when locked."""
    val = os.environ.get(ENV_LLM_PROVIDER, "").strip().lower()
    return val in VALID_PROVIDERS


def has_provider_key(config: dict, provider: Provider) -> bool:
    """Check if the target provider has an API key configured."""
    if provider == "qwen":
        return bool((config.get("qwen") or {}).get("api_key"))
    return bool((config.get("gemini") or {}).get("api_key"))
```

```python
# stock_trading_system/llm/constants.py
VALID_PROVIDERS = frozenset({"qwen", "gemini"})
ENV_LLM_PROVIDER = "LLM_PROVIDER"
```

### 4.3 LLMTextClient Protocol

**动机**：nl_parser 与 universe 目前硬依赖 `QwenProvider`。为支持切换到 Gemini，抽象一层 "给一段 prompt，返回一段文本（可要求 JSON mode）"。

```python
# stock_trading_system/llm/client.py
from __future__ import annotations

from typing import Protocol

from stock_trading_system.llm.router import get_active_provider


class LLMTextClient(Protocol):
    """Minimal text-in / text-out LLM interface for screener internals.

    NOT for TradingAgents — that uses its own LangChain-based graph.
    """
    provider_name: str

    def chat(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = False,
        timeout: int = 60,
    ) -> str: ...


class QwenTextClient:
    """Qwen implementation. Reuses existing QwenProvider infra."""
    provider_name = "qwen"

    def __init__(self, config: dict) -> None:
        from stock_trading_system.data.qwen_provider import QwenProvider
        self._provider = QwenProvider(config)

    def chat(self, *, system, user, json_mode=False, timeout=60) -> str:
        # Internals reuse the OpenAI-compatible client already present on QwenProvider.
        # (Existing QwenProvider exposes `_chat` or similar; if not, add a thin wrapper.)
        return self._provider.raw_chat(
            system=system, user=user, json_mode=json_mode, timeout=timeout,
        )


class GeminiTextClient:
    """Gemini implementation via google-generativeai."""
    provider_name = "gemini"

    def __init__(self, config: dict) -> None:
        import google.generativeai as genai
        api_key = (config.get("gemini") or {}).get("api_key", "")
        if not api_key:
            raise RuntimeError("Gemini selected but api_key is missing")
        genai.configure(api_key=api_key)
        model_name = (config.get("gemini") or {}).get("model", "gemini-2.5-flash")
        self._model = genai.GenerativeModel(model_name)

    def chat(self, *, system, user, json_mode=False, timeout=60) -> str:
        from google.generativeai.types import GenerationConfig
        gen_cfg = GenerationConfig(
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        # System instructions via Gemini's system_instruction field
        resp = self._model.generate_content(
            [{"role": "user", "parts": [f"{system}\n\n{user}"]}],
            generation_config=gen_cfg,
            request_options={"timeout": timeout},
        )
        return resp.text or ""


def get_text_client(config: dict) -> LLMTextClient:
    """Factory. Returns the client for the currently active provider."""
    provider = get_active_provider(config)
    if provider == "qwen":
        return QwenTextClient(config)
    return GeminiTextClient(config)
```

**注意**：`QwenProvider` 当前没有公开的 `raw_chat()` 方法；它的内部 OpenAI client 被用作数据 API 封装。需要补一个瘦方法或者 `QwenTextClient` 内部直接起一个新的 OpenAI-compatible client。选后者更干净，见 §4.6 实施步骤。

### 4.4 配置 schema 变更

**新增顶层字段** `llm_provider`：

```yaml
# stock_trading_system/config/default_config.yaml
llm_provider: null   # null -> 走 legacy 自动探测；"qwen" | "gemini" -> 强制指定

gemini:
  api_key: ""
  model: "gemini-2.5-flash"
  ...

qwen:
  enabled: false
  api_key: ""
  model: "qwen-plus"
  ...
```

**env var 映射**（新增到 [settings.py:42-60](../../stock_trading_system/config/settings.py) `env_map`）：

```python
"LLM_PROVIDER": ("llm_provider",),   # 顶层
```

⚠️ 注意 env_map 的路径元组现在支持长度 1（直接顶层键）。检查 `_apply_env_overrides` 的循环是否正确处理：

```python
# 当前实现 (settings.py:62-71)
for env_var, path in env_map.items():
    value = os.environ.get(env_var)
    if value is not None:
        node = config
        for key in path[:-1]:         # 空循环当 len(path) == 1
            node = node.setdefault(key, {})
        # ...
        node[path[-1]] = value        # 直接 config["llm_provider"] = value
```

已经兼容长度 1 的路径。✅

### 4.5 Analyzer graph 缓存 key by provider

现在 [analyzer.py:45](../../stock_trading_system/agents/analyzer.py) `self._graph = None` 是单一 graph 缓存。切换后要重新 init，否则旧 provider 的 graph 会继续服务。

**改造**：把单一缓存改成字典，按 `(provider, prompts_version)` 作为 key：

```python
# analyzer.py
class StockAnalyzer:
    def __init__(self, config: dict):
        self._config = config
        self._graphs: dict[str, Any] = {}  # provider -> TradingAgentsGraph

    def _init_graph(self) -> Any:
        from stock_trading_system.llm.router import get_active_provider
        provider = get_active_provider(self._config)
        if provider in self._graphs:
            return self._graphs[provider]

        self._patch_tradingagents_qwen()
        # ... existing ta_config construction, but branch explicitly on `provider`:
        if provider == "qwen":
            self._configure_qwen(ta_config)
        else:
            self._configure_gemini(ta_config)
        # ... build graph
        self._graphs[provider] = TradingAgentsGraph(...)
        return self._graphs[provider]
```

**重要**：把原来的 `if qwen_key: ... else: ...` 改成 `if provider == "qwen": ...`。保留内部 `qwen_key` / `gemini_key` 的实际读取，只是分支条件改掉。

**并发安全**：`_init_graph` 可能被并发请求同时调用（Flask 多线程）。用简单锁：

```python
import threading
self._graph_lock = threading.Lock()

def _init_graph(self):
    with self._graph_lock:
        provider = get_active_provider(self._config)
        if provider in self._graphs:
            return self._graphs[provider]
        # ... init
```

### 4.6 各 call site 改造

#### 4.6.1 `analyzer.py`

如 §4.5 所述，把硬编码 `if qwen_key` 改为 `if provider == "qwen"`，并对 graph 缓存做 per-provider 字典。

具体 diff 大致 30 行：把 [analyzer.py:91-145](../../stock_trading_system/agents/analyzer.py) 的单一 if/else 拆成两个私有方法 `_configure_qwen(ta_config)` 和 `_configure_gemini(ta_config)`，顶层 `_init_graph` 只做选择。

#### 4.6.2 `screener/v2/nl_parser.py`

```python
# 当前
from stock_trading_system.data.qwen_provider import QwenProvider
self._qwen = QwenProvider(config)
# ... 内部调 self._qwen.<something>(prompt)

# 改造后
from stock_trading_system.llm.client import get_text_client
self._llm = get_text_client(config)
# ... 内部调 self._llm.chat(system=..., user=..., json_mode=True)
```

NL parser 的 prompt 保持不变（两家都能理解同一份 prompt）；仅切换 client。

#### 4.6.3 `screener/v2/universe.py`

同上。Universe filter 也是一次性 prompt → JSON list，适用 `get_text_client`。

#### 4.6.4 `screener/screener.py` (旧 screener AI eval)

AI eval 逻辑分散在 [screener/screener.py:90-91](../../stock_trading_system/screener/screener.py)，同样换成 `get_text_client`。

### 4.7 前端：Nav 下拉

#### UI 位置

在现有 Nav 栏右侧（用户头像/系统状态附近）增加下拉：

```html
<!-- 伪代码，具体 HTML 对齐现有 nav 组件风格 -->
<div class="nav-llm-switcher">
  <label>模型</label>
  <select id="llm-provider-select">
    <option value="qwen">Qwen (通义千问)</option>
    <option value="gemini">Gemini</option>
  </select>
  <span class="nav-llm-lock" hidden>🔒</span>
</div>
```

#### 初始化 + 切换逻辑

```js
// static/js/llm-switcher.js (new file)
async function initLLMSwitcher() {
  const resp = await fetch('/api/settings/llm-provider');
  const { active, has_qwen_key, has_gemini_key, locked_by_env } = await resp.json();
  const sel = document.getElementById('llm-provider-select');
  sel.value = active;
  // 禁用选项：目标 provider 缺 key
  for (const opt of sel.options) {
    if (opt.value === 'qwen'   && !has_qwen_key)   opt.disabled = true;
    if (opt.value === 'gemini' && !has_gemini_key) opt.disabled = true;
  }
  if (locked_by_env) {
    sel.disabled = true;
    document.querySelector('.nav-llm-lock').hidden = false;
    document.querySelector('.nav-llm-lock').title = '由环境变量 LLM_PROVIDER 锁定';
    return;
  }
  sel.addEventListener('change', onSwitch);
}

async function onSwitch(ev) {
  const provider = ev.target.value;
  const resp = await fetch('/api/settings/llm-provider', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({provider}),
  });
  if (!resp.ok) {
    const {reason, message} = await resp.json();
    showToast(message || `切换失败: ${reason}`, 'error');
    // 回滚下拉到上一个值
    ev.target.value = ev.target.dataset.previous || 'qwen';
    return;
  }
  ev.target.dataset.previous = provider;
  showToast(`已切换到 ${provider === 'qwen' ? 'Qwen' : 'Gemini'}，下次分析生效`, 'success');
}
```

### 4.8 Web API

新增两个路由（挂到 [web/app.py](../../stock_trading_system/web/app.py)）：

#### `GET /api/settings/llm-provider`

Response 200：

```json
{
  "active": "qwen",
  "has_qwen_key": true,
  "has_gemini_key": true,
  "locked_by_env": false
}
```

#### `POST /api/settings/llm-provider`

Request：

```json
{"provider": "gemini"}
```

Response 200：

```json
{"active": "gemini", "source": "user_config"}
```

错误响应：

| Status | body | 触发条件 |
|---|---|---|
| 400 | `{"reason": "invalid_provider", "message": "provider must be 'qwen' or 'gemini'"}` | provider 字段不在白名单 |
| 400 | `{"reason": "missing_api_key", "message": "Gemini 未配置 API key..."}` | 目标 provider 无 key |
| 409 | `{"reason": "locked_by_env", "message": "LLM_PROVIDER 已由环境变量锁定"}` | env 变量已设置 |

服务端实现：

```python
# web/app.py
@app.route("/api/settings/llm-provider", methods=["GET"])
def get_llm_provider():
    from stock_trading_system.llm.router import (
        get_active_provider, has_provider_key, is_provider_locked_by_env,
    )
    cfg = get_config()
    return jsonify({
        "active": get_active_provider(cfg),
        "has_qwen_key":   has_provider_key(cfg, "qwen"),
        "has_gemini_key": has_provider_key(cfg, "gemini"),
        "locked_by_env":  is_provider_locked_by_env(),
    })


@app.route("/api/settings/llm-provider", methods=["POST"])
def set_llm_provider():
    from stock_trading_system.llm.router import (
        is_provider_locked_by_env, has_provider_key,
    )
    from stock_trading_system.llm.constants import VALID_PROVIDERS
    from stock_trading_system.config.settings import save_config

    if is_provider_locked_by_env():
        return jsonify({
            "reason": "locked_by_env",
            "message": "LLM_PROVIDER 已由环境变量锁定，请取消 env 设置后重试",
        }), 409

    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or "").strip().lower()
    if provider not in VALID_PROVIDERS:
        return jsonify({
            "reason": "invalid_provider",
            "message": f"provider 必须是 {sorted(VALID_PROVIDERS)} 之一",
        }), 400

    cfg = get_config()
    if not has_provider_key(cfg, provider):
        label = "Qwen" if provider == "qwen" else "Gemini"
        envname = "DASHSCOPE_API_KEY" if provider == "qwen" else "GEMINI_API_KEY"
        return jsonify({
            "reason": "missing_api_key",
            "message": f"{label} 未配置 API key，请在 ~/.stock_trading/config.yaml "
                       f"或环境变量 {envname} 中设置",
        }), 400

    save_config({"llm_provider": provider})  # atomic write + reload
    logger.info("LLM provider switched to %s via UI", provider)

    # 触发 analyzer 单例的 graph 缓存 "失效" —— 见 §4.9
    _invalidate_analyzer_graphs()

    return jsonify({"active": provider, "source": "user_config"})
```

### 4.9 Analyzer 单例与 graph 失效

Web 层通常持有一个 `StockAnalyzer` 单例（或每次请求新建）。切换后要让它丢掉旧 graph。

两种实现：

**方案 A（推荐，简单）**：`_graphs` 按 provider 作 key，切换后不必清除。下次 `_init_graph()` 读新 provider，自动命中/初始化对应 key 下的 graph。不失效，也正确。

**方案 B（显式清除）**：导出一个模块级函数 `invalidate_all_graphs()`，API 在切换后调用。更"显式"但并非必要。

**采用方案 A**。`_invalidate_analyzer_graphs()` 在 §4.8 里其实是空实现或直接去掉。这样设计更干净，且 graph 缓存命中时第二次切回同一 provider 成本 ~0。

### 4.10 错误处理 & fallback

**v1.0 不做自动 failover**（见 [PRD §3.2](../prd/model-switch.md#32-out-of-scope不做)）。

各 call site 对 LLM 调用失败的处理：

| 调用点 | 失败行为 |
|---|---|
| Analyzer | 现有：异常向上抛，`AnalysisResult` 带 signal="ERROR" |
| NL parser | 现有：降级到关键词 fallback parser |
| Universe | 现有：降级到 Layer B/C（非 LLM 路径） |
| 旧 screener AI | 现有：跳过 AI tier，只返回 tier-1/2 结果 |

切换 provider 本身不改以上降级逻辑。

## 5. 数据契约

### 5.1 配置文件

```yaml
# ~/.stock_trading/config.yaml
llm_provider: gemini   # 新增；null/缺省 = legacy 自动探测

qwen:
  api_key: "sk-..."

gemini:
  api_key: "AIza..."
```

### 5.2 API 契约

见 §4.8。

### 5.3 日志

```
[INFO] llm.router: get_active_provider resolved: gemini (source=config)
[INFO] agents.analyzer: Using Gemini LLM provider (model=gemini-2.5-flash)
[INFO] web.app: LLM provider switched to gemini via UI
```

## 6. 兼容性与迁移

| 场景 | 行为 |
|---|---|
| 用户从未改过配置 | `llm_provider: null` → legacy 探测 → 与当前行为**完全一致** |
| 用户设置了 `DASHSCOPE_API_KEY` env | 仍走 legacy 探测 → Qwen（不变） |
| 用户设置 `LLM_PROVIDER=qwen` env | 新行为：锁定为 Qwen |
| 用户改 `llm_provider: gemini` 但没 Gemini key | 启动时 resolver 返回 `"gemini"` → analyzer 运行时报 key 缺失错 → UI 已在切换时拒绝（前置校验），但 CLI 直接改 yaml 不走校验会踩到 |

**yaml 直改的兜底**：`_init_graph` 在 Gemini 分支增加启动期断言：

```python
if provider == "gemini" and not gemini_key:
    raise RuntimeError(
        "llm_provider=gemini but gemini.api_key is empty. "
        "Set GEMINI_API_KEY env var or update config.yaml."
    )
```

Qwen 分支同理。

## 7. 回滚方案

如果上线后发现严重问题：

1. **配置级回滚**：在 `~/.stock_trading/config.yaml` 删除 `llm_provider` 字段 → 回到 legacy 行为；
2. **代码级回滚**：`git revert` 本次 commit；analyzer 恢复硬编码分支。

依赖关系：本 feature 不引入新表、不改数据库、不改现有 API 的既有路径。回滚风险低。

## 8. 实施计划

### Phase 1 —— 后端骨架（~2h）

1. 新建 `stock_trading_system/llm/{__init__.py, router.py, client.py, constants.py}`；
2. 给 `default_config.yaml` 加 `llm_provider: null`；
3. `settings.py` env_map 加 `LLM_PROVIDER`；
4. 单元测试 `test_router.py` 覆盖优先级链、未知值兜底。

### Phase 2 —— Analyzer 改造（~1h）

1. `analyzer.py` 把 `_graph` 改成 `_graphs` 字典；
2. 提取 `_configure_qwen` / `_configure_gemini`；
3. `_init_graph` 顶层 `get_active_provider()` 分支；
4. 加 provider 启动期缺 key 断言；
5. 集成测试：设置 `LLM_PROVIDER` 后跑一次 mock 分析，assert graph key 正确。

### Phase 3 —— Screener V2 改造（~1.5h）

1. `QwenTextClient` 实现（wrap 新 OpenAI-compatible client 或复用 QwenProvider）；
2. `GeminiTextClient` 实现（确认 `google-generativeai` 依赖在 `requirements.txt`）；
3. `nl_parser.py` / `universe.py` 换 `get_text_client`；
4. 旧 `screener.py` AI eval 换 `get_text_client`；
5. 单元测试 nl_parser + universe 两家都过。

### Phase 4 —— API + UI（~2h）

1. `/api/settings/llm-provider` GET/POST 两路由；
2. `static/js/llm-switcher.js` + Nav HTML 注入；
3. Toast 集成（沿用现有 toast 组件）；
4. E2E：手动切换 + 立即触发分析验证。

### Phase 5 —— 收尾（~1h）

1. 文档更新（README 段落：如何切模型）；
2. changelog 三件套；
3. 跑全量单测 + lint（black + ruff）。

**总计 ~7.5h**。

## 9. 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| QwenProvider 没有可复用的 `raw_chat()`，需新增 | 高 | 低 | 直接在 QwenTextClient 起独立 OpenAI client，不动 QwenProvider |
| Gemini Python SDK (`google-generativeai`) 未装 | 中 | 中 | requirements.txt 已间接依赖（TradingAgents 的 Gemini 路径需要）；显式 pin 版本 |
| Nav 栏改动触发整体样式回归 | 低 | 中 | 只加独立组件，不改容器；视觉 diff 走 Playwright 截图 |
| Flask 多线程下 analyzer 单例的 `_graphs` 字典竞态 | 低 | 低 | 用 `threading.Lock()`（见 §4.5） |
| 切换瞬间正在跑的分析中断 | 低 | 低 | 方案 A（按 provider 字典缓存）天然不中断 |
| yaml 手改成 `llm_provider: claude` 之类未支持值 | 中 | 低 | resolver 的未知值回退 + warning 日志 |

## 10. 与自我迭代 Agents 模块的交互

自我迭代模块（[docs/design/self-iterating-agents.md](./self-iterating-agents.md) v3.0）通过 `ta_config["agent_prompts"]` 注入当代 prompt 变体。本 feature 只影响 **哪家 LLM 执行**这些 prompt，不影响 prompt 内容。

**有意思的副作用**：切换 provider 本身就是一种 A/B 测试维度。后续可以把 `provider` 作为 `agent_scorecards` 的一列，比较同一 prompt 在两家模型上的 Sharpe 差异。本 feature 不主动实现此统计，但**建议 Phase 5 给 scorecards 表加 `provider` 列作为未来扩展点**（一行 ALTER TABLE）。

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-18 | 初版：llm/ 独立模块 + router/client 分层 + analyzer graph 按 provider 缓存 + Nav 下拉 UI |
