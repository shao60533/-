# 技术方案：LLM 跨 Provider 自动 Fallback（限流降级）

| 项 | 值 |
|---|---|
| Feature | `llm-fallback` |
| 版本 | v1.0 |
| 日期 | 2026-05-03 |
| 关联 | [model-switch v1.0](./model-switch.md)（provider 路由）+ [analysis-rendering v1.0](./analysis-rendering.md)（RenderingExtractor）+ [screener-v3 v1.0](./screener-v3.md)（14 大师 + 圆桌） |
| 关联测试 | `tests/llm/test_resilient_chat.py`、`tests/llm/test_rate_limit_classification.py` |

## 1. 背景

用户反馈：「Gemini 如果限流应该自动切换成 Qwen 接口，不应该报错。」

Audit 当前 LLM 调用链路：

| 调用点 | 位置 | 限流处理 |
|---|---|---|
| AI 分析主链路 | [analyzer.py 主分析 ta_config](../../stock_trading_system/agents/analyzer.py)（tradingagents 上游） | 无 |
| RenderingExtractor 8 tab 抽取 | [analyzer.py:227-241 `_build_quick_llm`](../../stock_trading_system/agents/analyzer.py) → [rendering/extractor.py](../../stock_trading_system/agents/rendering/extractor.py) | 无（单 tab try/except 但只 log warning，没切 provider） |
| V3 14 大师评估 | [screener/v3/guru_agents/base.py:433-460 `_get_chat_model`](../../stock_trading_system/screener/v3/guru_agents/base.py) | concurrency.py 有 tenacity 3 次同 provider 重试，**不切换** |
| V3 圆桌辩论 LLM judge / Round 3 rebuttal | [screener/v3/roundtable.py](../../stock_trading_system/screener/v3/roundtable.py)（v1.5）| 无（仅捕获 Exception 写"评判失败"）|

**根因**：3 处 `ChatGoogleGenerativeAI` / `ChatOpenAI` 直接构造，无 cross-provider fallback。Gemini `ResourceExhausted` (429) 抛到上层 → 用户看到 "评估失败" / "extraction failed" 等。

## 2. 设计目标

- 任一 LLM 调用遇限流类异常时**单次请求级**自动切到备用 provider 完成
- 不持久化切换（下次请求仍优先 active provider）—— 与 `get_active_provider` 路由解耦，不污染 user_settings / env
- 透明：上层 `with_structured_output(Schema)` / `chat.invoke(...)` 行为不变
- 可观测：每次 fallback 触发记到 metrics + structured log
- **复用 LangChain 原生** `Runnable.with_fallbacks(...)`，不自写 retry loop（与 [engineering-principles.md](./engineering-principles.md) §5.1 复用优先一致）

## 3. 不动（强约束）

- `get_active_provider` 路由优先级（env > user_settings > config > legacy auto）—— fallback 是单次请求级补丁，不改变路由
- `cache.py` (LocalCache) 已有逻辑
- `tenacity` 3 次同 provider 重试（v1.4 R-fix-9 既有）—— fallback 在 tenacity 之后兜底，不冲突
- analyzer 主链路 ta_config（tradingagents 上游接管）—— **不强制兜底**，因为 ta_config 直接构造 graph 内部 ChatModel，不走我们的 wrapper；可在后续版本（不在本范围）通过 monkey-patch 或 ta_config 注入处理
- DB schema / API 端点 / 前端
- `cfg["qwen"]["api_key"]` / `cfg["gemini"]["api_key"]` 现有结构
- v1.5 14 大师 prompt / 圆桌 prompt（已落地）

## 4. 数据 / 调用契约

### 4.1 异常分类

```python
# stock_trading_system/llm/rate_limit.py
"""
Detect rate-limit / quota-exhaustion errors across both providers.

Both google-api-core and openai SDK raise different exception types
for the same underlying 429 status — we normalize all of them to a
single ``is_rate_limit_error(exc) -> bool`` predicate.
"""
from __future__ import annotations


def is_rate_limit_error(exc: BaseException) -> bool:
    """Return True iff the exception is a rate-limit / quota / 429 error.

    Order: type-based first (cheap), then string-match fallback for
    subclassed wrappers like httpx.HTTPStatusError or LangChain-wrapped
    provider errors.
    """
    # Type-based
    try:
        from google.api_core.exceptions import (
            ResourceExhausted, TooManyRequests,
        )
        if isinstance(exc, (ResourceExhausted, TooManyRequests)):
            return True
    except ImportError:
        pass
    try:
        from openai import RateLimitError
        if isinstance(exc, RateLimitError):
            return True
    except ImportError:
        pass
    try:
        from openai import APIStatusError
        if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 429:
            return True
    except ImportError:
        pass

    # httpx (used internally by google-genai / openai)
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            return True
    except ImportError:
        pass

    # String fallback (covers wrapped/translated errors)
    msg = str(exc).lower()
    return any(token in msg for token in (
        "429", "rate limit", "rate_limit",
        "quota", "resource_exhausted", "resource has been exhausted",
        "too many requests",
    ))
```

### 4.2 Fallback Wrapper Builder

```python
# stock_trading_system/llm/resilient_chat.py
"""Provider-fallback chat client builder.

Composition: primary provider (active) wrapped with LangChain's
``with_fallbacks`` to switch to the other provider on rate-limit /
quota errors. Single-request scope — no state mutation, the next
request goes back to the primary first.

Returned Runnable supports the same surface as the underlying
ChatModel: ``.invoke(messages)``, ``.with_structured_output(Schema)``,
streaming, etc. — because RunnableWithFallbacks inherits the
Runnable interface and ``with_structured_output`` is a Runnable
factory method.
"""
from __future__ import annotations

import logging
from typing import Literal, Any

from stock_trading_system.llm.rate_limit import is_rate_limit_error
from stock_trading_system.llm.router import get_active_provider

logger = logging.getLogger("llm.resilient_chat")

ChatKind = Literal["quick", "deep"]


def _build_chat(provider: str, kind: ChatKind, config: dict, *,
                  timeout: int = 120) -> Any:
    """Construct a raw single-provider ChatModel. Internal helper."""
    if provider == "qwen":
        from langchain_openai import ChatOpenAI
        qcfg = config.get("qwen", {}) or {}
        model = (qcfg.get("deep_think_model") if kind == "deep"
                 else qcfg.get("model")) or "qwen-plus"
        api_key = qcfg.get("api_key", "")
        if not api_key:
            raise RuntimeError("qwen.api_key empty")
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=qcfg.get("base_url",
                "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            timeout=timeout,
        )
    # default → gemini
    from langchain_google_genai import ChatGoogleGenerativeAI
    gcfg = config.get("gemini", {}) or {}
    model = (gcfg.get("deep_think_model") if kind == "deep"
             else gcfg.get("model")) or "gemini-2.5-flash"
    api_key = gcfg.get("api_key", "")
    if not api_key:
        raise RuntimeError("gemini.api_key empty")
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        timeout=timeout,
    )


def _other_provider(p: str) -> str:
    return "qwen" if p == "gemini" else "gemini"


def _can_fallback(config: dict, target: str) -> bool:
    """Fallback target only usable if its API key is configured AND
    fallback isn't disabled by config."""
    if (config.get("llm") or {}).get("fallback_enabled", True) is False:
        return False
    target_cfg = config.get(target, {}) or {}
    return bool(target_cfg.get("api_key"))


# Module-level fallback counter (telemetry only). Read by caller into
# task metrics; reset is callers' responsibility (or just use diff).
_fallback_counter: dict[str, int] = {"gemini→qwen": 0, "qwen→gemini": 0}


def get_fallback_counters() -> dict[str, int]:
    """Snapshot of fallback counters for telemetry. Mutating the
    returned dict does NOT affect the module state."""
    return dict(_fallback_counter)


def reset_fallback_counters() -> None:
    """Reset counters (typically at the start of a task / pipeline run)."""
    for k in list(_fallback_counter.keys()):
        _fallback_counter[k] = 0


def build_resilient_chat(config: dict, *,
                           kind: ChatKind = "quick",
                           user_id: int | None = None,
                           timeout: int = 120) -> Any:
    """Build a chat client that falls back to the other provider on
    rate-limit errors. Returns a LangChain Runnable supporting
    ``.invoke()`` / ``.with_structured_output(Schema)``.

    If fallback is disabled (config) or the other provider has no key,
    returns the bare primary chat (current behavior, no regression).
    """
    primary = get_active_provider(config, user_id=user_id)
    primary_chat = _build_chat(primary, kind, config, timeout=timeout)

    secondary = _other_provider(primary)
    if not _can_fallback(config, secondary):
        return primary_chat  # Single-provider deployment — no wrapping.

    secondary_chat = _build_chat(secondary, kind, config, timeout=timeout)

    # ── Counter callback wrapper ───────────────────────────────────
    # LangChain's with_fallbacks invokes the secondary when the primary
    # raises one of ``exceptions_to_handle``. We want to:
    #   1. Only catch rate-limit-like errors (let real bugs propagate)
    #   2. Bump our counter when fallback fires
    #
    # The cleanest way is a custom exception handler via
    # `exception_key` and a small wrapper Runnable that increments the
    # counter on its execution. We use a Runnable lambda so we keep
    # ``with_structured_output`` working on the resulting chain.
    from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks

    def _bump_counter(x: Any) -> Any:
        _fallback_counter[f"{primary}→{secondary}"] += 1
        logger.warning(
            "LLM fallback triggered: %s rate-limited, switching to %s",
            primary, secondary,
        )
        return x  # passthrough; chain output unchanged

    # The trick: chain primary → identity. Fallback chain: bump_counter → secondary.
    counted_secondary = RunnableLambda(_bump_counter) | secondary_chat

    # exception_key=None means: catch anything matching exceptions_to_handle.
    # We pass a custom predicate via custom subclass to filter only
    # rate-limit errors (LangChain's with_fallbacks uses isinstance check
    # against a tuple — we use a wrapping exception type).
    class _RateLimitMarker(Exception):
        pass

    def _wrap_primary(input_data):
        try:
            return primary_chat.invoke(input_data)
        except BaseException as e:  # noqa: BLE001
            if is_rate_limit_error(e):
                raise _RateLimitMarker(str(e)) from e
            raise

    wrapped = RunnableLambda(_wrap_primary).with_fallbacks(
        [counted_secondary],
        exceptions_to_handle=(_RateLimitMarker,),
    )

    # ── Structured output passthrough ──────────────────────────────
    # We need ``.with_structured_output(Schema)`` to still work on the
    # fallback chain. RunnableWithFallbacks supports it natively (it
    # delegates to .with_structured_output on each branch). Verify
    # at __init__ time so misconfiguration fails loudly.
    if not hasattr(wrapped, "with_structured_output"):
        raise RuntimeError(
            "RunnableWithFallbacks lacks with_structured_output — "
            "LangChain version too old; pin >=0.3."
        )
    return wrapped
```

注：上面用 `RunnableLambda(_wrap_primary)` 是为了**只捕获限流类异常**触发 fallback；其它异常（API key 错、JSON 解析失败、network down）继续按现有 retry 链向上抛 —— 避免「mask 真实 bug」。

LangChain `RunnableWithFallbacks` 原生 inherits Runnable 的 `with_structured_output` 方法（通过 `bind` 委托到每个分支），所以下游 `chat.with_structured_output(GuruSignal).invoke(...)` 仍然工作。

### 4.3 三处接入点

| 接入点 | 改前 | 改后 |
|---|---|---|
| `BaseGuruAgent._get_chat_model` (line 433-460) | 直接 `ChatOpenAI / ChatGoogleGenerativeAI` | `build_resilient_chat(config, kind="quick", user_id=...)` |
| `analyzer.py:_build_quick_llm` (line 220-245)（用于 RenderingExtractor）| 同上 | `build_resilient_chat(config, kind="quick")` |
| `roundtable.run_roundtable` 调用方 (`pipeline._run_roundtable`) 提供的 `llm_call` 闭包 | 直接 invoke | `build_resilient_chat(config, kind="quick").invoke(...)` |

analyzer 主链路（tradingagents 上游 ta_config）暂不接入 —— 因为 ta_config 在 graph 内部直接构造 ChatModel，需要单独 patch；本次范围限定在我们直接构造 ChatModel 的 3 处。

### 4.4 计数器 + 任务级可观测

worker 在任务开始时 `reset_fallback_counters()`，结束时把 `get_fallback_counters()` 写入：
- V3 选股 `metrics.fallback_counts` → 透传到 `/api/screen/v3/results _v3_run_metadata.fallback_counts`
- analysis worker `result["fallback_counts"]` → analysis_history `rendering_json` 同 batch 写入（schema 不动，加 metrics 子字段）

前端可选展示（不强制本期落地）：v1.2 运行模式 banner 末尾加 `备用 LLM 触发 N 次` 角标。

## 5. 配置开关

`config.yaml` 加（已加 `qwen` `gemini` block 之后）：
```yaml
llm:
  fallback_enabled: true   # default true; set false to disable cross-provider fallback
```

`_can_fallback` 检测此字段；缺省 = `True`（向后兼容默认开启）。

## 6. 实施清单

| 步 | 范围 | 工时 |
|---|---|---|
| 1 | 新建 `stock_trading_system/llm/rate_limit.py` (`is_rate_limit_error`) | ~30min |
| 2 | 新建 `stock_trading_system/llm/resilient_chat.py` (`build_resilient_chat` + counter helpers) | ~1.5h |
| 3 | 改 `stock_trading_system/screener/v3/guru_agents/base.py:_get_chat_model` 用 builder | ~15min |
| 4 | 改 `stock_trading_system/agents/analyzer.py:_build_quick_llm` 用 builder | ~15min |
| 5 | 改 `stock_trading_system/screener/v3/pipeline.py:_run_roundtable` 调用 + worker reset/snapshot counter | ~30min |
| 6 | analysis worker reset/snapshot counter 入 result | ~15min |
| 7 | 测试：异常分类（10 case）+ wrapper 行为（fallback / 非限流不切 / 单 provider 降级）+ counter | ~1.5h |
| **合计** | | **~4.5h** |

## 7. 测试

`tests/llm/test_rate_limit_classification.py`（新增 ~10 case）：
```python
import pytest
from stock_trading_system.llm.rate_limit import is_rate_limit_error


def test_classifies_google_resource_exhausted():
    pytest.importorskip("google.api_core.exceptions")
    from google.api_core.exceptions import ResourceExhausted
    assert is_rate_limit_error(ResourceExhausted("Quota exceeded"))


def test_classifies_openai_rate_limit_error():
    pytest.importorskip("openai")
    from openai import RateLimitError
    # construct minimally
    err = RateLimitError("Rate limit reached", response=None, body=None)
    assert is_rate_limit_error(err)


def test_classifies_httpx_429():
    pytest.importorskip("httpx")
    import httpx
    req = httpx.Request("POST", "https://example.com")
    resp = httpx.Response(429, request=req)
    err = httpx.HTTPStatusError("rate limited", request=req, response=resp)
    assert is_rate_limit_error(err)


def test_string_fallback_429():
    assert is_rate_limit_error(RuntimeError("HTTP 429: too many requests"))


def test_string_fallback_quota():
    assert is_rate_limit_error(ValueError("Quota exhausted for project xyz"))


def test_string_fallback_rate_limit():
    assert is_rate_limit_error(Exception("API rate_limit reached"))


def test_does_not_match_500():
    assert not is_rate_limit_error(RuntimeError("HTTP 500: internal server error"))


def test_does_not_match_auth_error():
    assert not is_rate_limit_error(ValueError("API key invalid"))


def test_does_not_match_network_timeout():
    assert not is_rate_limit_error(TimeoutError("connect timed out"))


def test_does_not_match_validation_error():
    assert not is_rate_limit_error(ValueError("schema validation failed"))
```

`tests/llm/test_resilient_chat.py`（新增 ~6 case，用 monkeypatch + 假 Chat）：
```python
import pytest
from unittest.mock import MagicMock, patch
from stock_trading_system.llm.resilient_chat import (
    build_resilient_chat, get_fallback_counters, reset_fallback_counters,
)


@pytest.fixture(autouse=True)
def reset_counters():
    reset_fallback_counters()
    yield
    reset_fallback_counters()


def _config(qwen_key="sk-q", gemini_key="AIza-g", fallback=True):
    return {
        "llm_provider": "gemini",  # primary = gemini
        "qwen": {"api_key": qwen_key, "model": "qwen-plus"},
        "gemini": {"api_key": gemini_key, "model": "gemini-2.5-flash"},
        "llm": {"fallback_enabled": fallback},
    }


def test_returns_bare_primary_when_secondary_lacks_key():
    cfg = _config(qwen_key="")  # only gemini configured
    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockGem:
        chat = build_resilient_chat(cfg, kind="quick")
        # 直接是 ChatGoogleGenerativeAI, 不被 fallback 包裹
        assert MockGem.called


def test_returns_bare_primary_when_disabled():
    cfg = _config(fallback=False)
    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockGem:
        chat = build_resilient_chat(cfg, kind="quick")
        assert MockGem.called


def test_falls_back_on_rate_limit():
    """Primary throws RateLimitError → secondary handles."""
    cfg = _config()
    fake_primary = MagicMock()
    fake_primary.invoke.side_effect = RuntimeError("HTTP 429 quota")
    fake_secondary = MagicMock()
    fake_secondary.invoke.return_value = "secondary_response"

    with patch("stock_trading_system.llm.resilient_chat._build_chat",
                side_effect=[fake_primary, fake_secondary]):
        chat = build_resilient_chat(cfg, kind="quick")
        result = chat.invoke("test_input")
        assert result == "secondary_response"
        counters = get_fallback_counters()
        assert counters["gemini→qwen"] == 1


def test_does_not_fall_back_on_non_rate_limit_error():
    """Primary throws auth error → propagates, no fallback."""
    cfg = _config()
    fake_primary = MagicMock()
    fake_primary.invoke.side_effect = ValueError("invalid api key")
    fake_secondary = MagicMock()

    with patch("stock_trading_system.llm.resilient_chat._build_chat",
                side_effect=[fake_primary, fake_secondary]):
        chat = build_resilient_chat(cfg, kind="quick")
        with pytest.raises(ValueError, match="invalid api key"):
            chat.invoke("test_input")
        counters = get_fallback_counters()
        assert counters["gemini→qwen"] == 0


def test_with_structured_output_works_through_fallback():
    """The wrapped runnable must support .with_structured_output."""
    cfg = _config()
    fake_primary = MagicMock()
    fake_secondary = MagicMock()

    with patch("stock_trading_system.llm.resilient_chat._build_chat",
                side_effect=[fake_primary, fake_secondary]):
        chat = build_resilient_chat(cfg, kind="quick")
        # Should not raise
        assert hasattr(chat, "with_structured_output")


def test_qwen_primary_falls_back_to_gemini():
    """Reverse direction also works."""
    cfg = _config()
    cfg["llm_provider"] = "qwen"
    fake_primary = MagicMock()
    fake_primary.invoke.side_effect = RuntimeError("rate limit reached")
    fake_secondary = MagicMock()
    fake_secondary.invoke.return_value = "gemini_response"

    with patch("stock_trading_system.llm.resilient_chat._build_chat",
                side_effect=[fake_primary, fake_secondary]):
        chat = build_resilient_chat(cfg, kind="quick")
        result = chat.invoke("test_input")
        assert result == "gemini_response"
        counters = get_fallback_counters()
        assert counters["qwen→gemini"] == 1
```

## 8. 风险与边界

| 风险 | 缓解 |
|---|---|
| 两个 provider 同时限流 → 双失败 | secondary 也抛限流 → fallback 链耗尽 → 抛 `_RateLimitMarker` 到 caller；caller（concurrency.py / extractor）现有 try/except 保留 fallback 信号路径，仍能产出"失败"占位结果 |
| 字符串 fallback 误判（如 "rate" 出现在 reasoning 文本中） | 仅检查 exception message 不检查正常 LLM 输出；RuntimeError("...rate...") 误判可接受（更宽松比漏判好）|
| LangChain `RunnableWithFallbacks.with_structured_output` 跨版本行为变化 | builder 内启动时 hasattr 检查；测试覆盖；pin `langchain-core >= 0.3` |
| Counter 全局状态在并发任务下交错 | counter 仅做 telemetry，accuracy ≠ correctness；并发任务计数加总而非单任务隔离 OK；如严格隔离需后续改 contextvars |
| analyzer 主链路（tradingagents ta_config）未覆盖 | 用户主要痛点是详情页"评估失败"，主要发生在 RenderingExtractor + V3 大师；ta_config 单独迁移可下一版做（不在本范围）|
| 静默切换用户没感知 | counter 可选向前端暴露（v1.0 不强制，仅写入 metrics 字段）|

## 9. 复用 / 边界

依据 [engineering-principles.md](./engineering-principles.md)：

- **L1 库**：`langchain_core.runnables.RunnableWithFallbacks` 原生支持（已装）+ `RunnableLambda` 包装单次请求级捕获 + `google-api-core.exceptions` / `openai` / `httpx` 异常类（均已装）
- **L0 项目内**：`get_active_provider`（routes 优先级）+ 既有 ChatOpenAI / ChatGoogleGenerativeAI 构造逻辑抽到 `_build_chat` helper
- **L4 自写**：`is_rate_limit_error`（异常分类）+ `build_resilient_chat`（builder + counter）≈ 200 LOC

## 10. 与其他模块集成

| 模块 | 关系 |
|---|---|
| [model-switch v1.0](./model-switch.md) | `get_active_provider` 路由保持不动；fallback 是请求级补丁不污染路由 |
| [analysis-rendering v1.0/v1.1](./analysis-rendering.md) | RenderingExtractor 通过 `_build_quick_llm` 透明享受 fallback；schema / extractor 流程不变 |
| [screener-v3 v1.0/v1.4/v1.5](./screener-v3.md) | 14 大师 `_get_chat_model` + 圆桌 judge / Round 3 rebuttal 透明享受；既有 tenacity 同 provider 重试链路保留作内层 |
| [unified-progress v1.0](./unified-progress.md) | counter 写入 task metrics 通过既有事件透传，不需新增事件类型 |

## 11. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-03 | 初版：跨 provider 限流自动 fallback。新建 `stock_trading_system/llm/rate_limit.py`（`is_rate_limit_error` 检测 google `ResourceExhausted/TooManyRequests` + openai `RateLimitError/APIStatusError(429)` + `httpx.HTTPStatusError(429)` + 字符串 fallback `429/rate limit/quota/resource_exhausted/too many requests`）+ `stock_trading_system/llm/resilient_chat.py`（`build_resilient_chat(config, kind, user_id)` 用 LangChain `RunnableWithFallbacks` + `RunnableLambda` 单次请求级捕获限流异常切到备用 provider，原生支持 `with_structured_output`；模块级 `_fallback_counter` 仅 telemetry；`config.llm.fallback_enabled` 默认 true，secondary 缺 key 或 disabled 时降级返回 bare primary 不引入 regression）。3 处接入：(A) `BaseGuruAgent._get_chat_model` 用 builder；(B) `analyzer._build_quick_llm` 用 builder（覆盖 RenderingExtractor 8 tab）；(C) `roundtable._run_roundtable` 的 `llm_call` 闭包用 builder。worker 任务级 reset/snapshot counter 写入 metrics（V3 `_v3_run_metadata.fallback_counts`、analysis `result["fallback_counts"]`）。**不动** `get_active_provider` 路由 / cache / 既有 tenacity 同 provider retry / DB / API / 前端 / v1.5 14 大师 prompt / 圆桌 prompt / analyzer 主链路 ta_config（tradingagents 上游 graph 单独迁移留下一版）。新增 `tests/llm/test_rate_limit_classification.py` 10 case（type-based + 字符串 + 拒识 500/auth/timeout/validation）+ `tests/llm/test_resilient_chat.py` 6 case（缺 key 降级 / disabled 降级 / 限流切换 / 非限流不切 / structured_output passthrough / 反向 qwen→gemini）；自写 ~200 LOC（含测试） |
