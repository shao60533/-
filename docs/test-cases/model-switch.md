# 测试用例：全局模型切换（Qwen ↔ Gemini）

| 项 | 值 |
|---|---|
| Feature | `model-switch` |
| 版本 | v1.0 |
| 日期 | 2026-04-18 |
| 关联 PRD | [../prd/model-switch.md](../prd/model-switch.md) |
| 关联设计 | [../design/model-switch.md](../design/model-switch.md) |

## 汇总

| 分类 | 用例数 |
|---|---|
| 单元：Provider resolver | 12 |
| 单元：LLMTextClient 工厂 | 4 |
| 单元：配置加载与持久化 | 6 |
| 集成：Analyzer | 6 |
| 集成：Screener V2 | 5 |
| API：GET/POST /api/settings/llm-provider | 10 |
| 前端：Nav 下拉 | 7 |
| 异常与边界 | 8 |
| 回归 | 5 |
| 性能 | 3 |
| **总计** | **66** |

---

## 1. 单元测试 —— Provider resolver（12）

目标文件：`tests/llm/test_router.py`

### TC-MS-U1：env 优先级高于 config

```python
@pytest.mark.unit
def test_env_beats_config(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    cfg = {"llm_provider": "qwen", "qwen": {"api_key": "k"}, "gemini": {"api_key": "g"}}
    assert get_active_provider(cfg) == "gemini"
```

### TC-MS-U2：config 高于 legacy 自动探测

```python
def test_config_beats_legacy(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"llm_provider": "gemini", "qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "gemini"
```

### TC-MS-U3：legacy —— 有 Qwen key 返回 qwen

```python
def test_legacy_qwen(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "qwen"
```

### TC-MS-U4：legacy —— 无 Qwen key 返回 gemini

```python
def test_legacy_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"gemini": {"api_key": "g"}}
    assert get_active_provider(cfg) == "gemini"
```

### TC-MS-U5：config 为 null 不触发未知值 warning

```python
def test_config_null_no_warning(caplog):
    cfg = {"llm_provider": None, "qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "qwen"
    assert "Ignoring unknown" not in caplog.text
```

### TC-MS-U6：env 值大小写不敏感

```python
@pytest.mark.parametrize("val", ["QWEN", "Qwen", "qwen", "  qwen  "])
def test_env_case_insensitive(monkeypatch, val):
    monkeypatch.setenv("LLM_PROVIDER", val)
    assert get_active_provider({}) == "qwen"
```

### TC-MS-U7：env 未知值被忽略并回退到 legacy

```python
def test_env_unknown_fallback(monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    cfg = {"qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "qwen"
    assert "Ignoring unknown LLM_PROVIDER" in caplog.text
```

### TC-MS-U8：config 未知值被忽略并回退到 legacy

```python
def test_config_unknown_fallback(caplog):
    cfg = {"llm_provider": "deepseek", "gemini": {"api_key": "g"}}
    assert get_active_provider(cfg) == "gemini"
    assert "Ignoring unknown config.llm_provider" in caplog.text
```

### TC-MS-U9：is_provider_locked_by_env —— 未设置 → False

### TC-MS-U10：is_provider_locked_by_env —— 设置有效值 → True

### TC-MS-U11：is_provider_locked_by_env —— 设置空字符串 → False

### TC-MS-U12：has_provider_key 两 provider 各 2 场景（有/无）

---

## 2. 单元测试 —— LLMTextClient 工厂（4）

目标文件：`tests/llm/test_client.py`

### TC-MS-U13：active=qwen → QwenTextClient

```python
def test_factory_returns_qwen(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"qwen": {"api_key": "k"}}
    client = get_text_client(cfg)
    assert client.provider_name == "qwen"
```

### TC-MS-U14：active=gemini → GeminiTextClient（mock google-generativeai）

### TC-MS-U15：Gemini client 无 key 直接 raise

```python
def test_gemini_client_missing_key_raises():
    with pytest.raises(RuntimeError, match="api_key is missing"):
        GeminiTextClient({"gemini": {}})
```

### TC-MS-U16：json_mode=True 两家都能产出合法 JSON（用 mock response）

---

## 3. 单元测试 —— 配置加载与持久化（6）

目标文件：`tests/config/test_settings_llm_provider.py`

### TC-MS-U17：env `LLM_PROVIDER` 写入顶层字段

```python
def test_env_override_top_level(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    cfg = load_config()
    assert cfg["llm_provider"] == "gemini"
```

### TC-MS-U18：save_config 写入 llm_provider 后 reload 能读到

### TC-MS-U19：save_config 只改 llm_provider 不覆盖其他字段

```python
def test_save_preserves_other_fields(tmp_path, monkeypatch):
    # 写入 user yaml：qwen key + 其他配置
    # 调 save_config({"llm_provider": "gemini"})
    # assert qwen.api_key 仍在，llm_provider 已更新
```

### TC-MS-U20：save_config 原子写入（临时文件存在于同目录）

### TC-MS-U21：default_config.yaml 含 `llm_provider: null`

### TC-MS-U22：_apply_env_overrides 处理长度为 1 的 path 元组正确

---

## 4. 集成测试 —— Analyzer（6）

目标文件：`tests/agents/test_analyzer_provider_switch.py`

### TC-MS-I1：active=qwen，graph 用 qwen 配置初始化

```python
@pytest.mark.integration
def test_analyzer_uses_qwen(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    cfg = {"qwen": {"api_key": "k"}, "gemini": {"api_key": "g"}}
    a = StockAnalyzer(cfg)
    a._init_graph()
    assert "qwen" in a._graphs
    # assert ta_config 内 llm_provider == "qwen"（通过 mock TradingAgentsGraph 捕获）
```

### TC-MS-I2：active=gemini，graph 用 gemini 配置初始化

### TC-MS-I3：切换后第二次 `_init_graph` 初始化新 graph（字典 size 从 1 → 2）

```python
def test_graph_cached_per_provider(monkeypatch):
    cfg = {"qwen": {"api_key": "k"}, "gemini": {"api_key": "g"}}
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    a = StockAnalyzer(cfg)
    a._init_graph()
    assert set(a._graphs.keys()) == {"qwen"}

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    a._init_graph()
    assert set(a._graphs.keys()) == {"qwen", "gemini"}
```

### TC-MS-I4：切回已有 provider 直接命中缓存（不再 patch / 不再 new TradingAgentsGraph）

### TC-MS-I5：active=gemini 但 gemini key 为空 → raise RuntimeError

### TC-MS-I6：并发 8 线程调 `_init_graph(provider=qwen)` 只创建一次 graph（验证 lock）

---

## 5. 集成测试 —— Screener V2（5）

### TC-MS-I7：NL parser 用 Qwen client 解析"科技股 PE<30"

### TC-MS-I8：NL parser 用 Gemini client 解析同一句 → 得到结构等价 JSON（容差：字段齐全）

### TC-MS-I9：Universe filter 两 provider 各跑一次 → 股票数量在合理区间（5~50）

### TC-MS-I10：NL parser LLM 调用失败 → 降级到关键词 parser（回归原有 fallback）

### TC-MS-I11：切换 provider 中间触发 universe filter，无错误、使用新 provider

---

## 6. API 测试 —— `/api/settings/llm-provider`（10）

目标文件：`tests/web/test_llm_provider_api.py`

### TC-MS-A1：GET 返回当前 provider + 两 key 状态

```python
def test_get_returns_state(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    # fixture config with both keys
    resp = client.get("/api/settings/llm-provider")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["active"] in ("qwen", "gemini")
    assert body["has_qwen_key"] is True
    assert body["has_gemini_key"] is True
    assert body["locked_by_env"] is False
```

### TC-MS-A2：GET —— env 锁定态 locked_by_env=True

### TC-MS-A3：POST 合法 provider 切换成功

```python
def test_post_valid_switch(client, tmp_user_config):
    resp = client.post("/api/settings/llm-provider", json={"provider": "gemini"})
    assert resp.status_code == 200
    assert resp.get_json()["active"] == "gemini"
    # 验证 yaml 文件已写入
    assert "llm_provider: gemini" in tmp_user_config.read_text()
```

### TC-MS-A4：POST 非法 provider → 400 invalid_provider

### TC-MS-A5：POST 目标 provider 缺 key → 400 missing_api_key

### TC-MS-A6：POST env 锁定 → 409 locked_by_env

### TC-MS-A7：POST 空 body → 400 invalid_provider

### TC-MS-A8：POST 缺 provider 字段 → 400

### TC-MS-A9：POST 大小写混合 "GEMINI" → 成功（归一化）

### TC-MS-A10：POST 连续两次切换（qwen → gemini → qwen）都成功，yaml 最终态正确

---

## 7. 前端测试 —— Nav 下拉（7）

目标：Playwright / 手动 E2E

### TC-MS-E1：页面加载后下拉显示当前 provider

### TC-MS-E2：点击下拉打开菜单，显示两个选项

### TC-MS-E3：选择另一项 → Toast "已切换到 ..."

### TC-MS-E4：刷新页面 → 下拉保持新选中值

### TC-MS-E5：切换失败（模拟 400）→ Toast 错误 + 下拉回滚到原值

### TC-MS-E6：env 锁定态 → 下拉禁用 + 🔒 图标 + hover tooltip

### TC-MS-E7：其中一家缺 key → 该选项灰显禁用

---

## 8. 异常与边界（8）

### TC-MS-X1：yaml 被手改为 `llm_provider: claude`（未支持值）→ 启动不崩，走 legacy，log warning

### TC-MS-X2：`~/.stock_trading/config.yaml` 无写权限 → save_config 抛 PermissionError；API 返回 500 + 人类可读 message

### TC-MS-X3：env `LLM_PROVIDER=  qwen  `（带空格）→ 正确归一化

### TC-MS-X4：Qwen key 存在但过期（实际调用 401）→ analyzer 异常 + signal=ERROR（现有行为，不改）

### TC-MS-X5：Gemini HK 出口 IP 被封（连接错）→ 现有异常捕获路径生效

### TC-MS-X6：切换期间并发 5 个 `POST /api/analyze` → 行为一致（要么全用旧，要么全用新，不混）

### TC-MS-X7：save_config 原子写入中途断电模拟（kill -9 during write）→ 下次启动配置不损坏

### TC-MS-X8：yaml 为损坏 YAML → load_config 现有异常路径生效

---

## 9. 回归（5）

### TC-MS-R1：未配置 `llm_provider` 的老 yaml + Qwen key → 行为与当前一致（Qwen）

### TC-MS-R2：未配置 + 无 Qwen key + 有 Gemini key → Gemini（当前一致）

### TC-MS-R3：`DASHSCOPE_API_KEY` env 自动启用 Qwen 逻辑不变

### TC-MS-R4：纸面交易、持仓分析、报告生成均不受影响（因只消费 analyzer 输出）

### TC-MS-R5：自我迭代模块 `agent_prompts` 注入在两 provider 下都生效

---

## 10. 性能（3）

### TC-MS-P1：切换 API 端到端延迟 ≤ 500ms（含 yaml 写入）

### TC-MS-P2：首次分析新 provider 冷启 graph ≤ 3s

### TC-MS-P3：第二次切回已用过的 provider，命中缓存 < 100ms

---

## 覆盖要求

| 模块 | 目标覆盖率 |
|---|---|
| `stock_trading_system/llm/router.py` | 100% 行覆盖 |
| `stock_trading_system/llm/client.py` | ≥ 90% 行覆盖 |
| `stock_trading_system/agents/analyzer.py`（改动行）| ≥ 85% |
| Web 路由 | ≥ 90% |

运行命令：

```bash
pytest tests/llm/ tests/config/test_settings_llm_provider.py \
       tests/agents/test_analyzer_provider_switch.py \
       tests/web/test_llm_provider_api.py \
       --cov=stock_trading_system/llm \
       --cov=stock_trading_system/config/settings.py \
       --cov-report=term-missing
```

## 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-18 | 66 | 初版：单元 22 + 集成 11 + API 10 + 前端 7 + 异常 8 + 回归 5 + 性能 3 |
