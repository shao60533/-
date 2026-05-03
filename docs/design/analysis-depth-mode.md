# AI 分析模式（标准 / 深度）

| 项 | 值 |
|---|---|
| Feature | `analysis-depth-mode` |
| 版本 | v1.0 |
| 日期 | 2026-05-03 |
| 关联 | [analysis-inbox v1.1](./analysis-inbox.md)（提交入口）+ [analysis-rendering v1.5](./analysis-rendering.md)（详情页 badge）+ [analysis-progress-truth-source v1.0](./analysis-progress-truth-source.md)（worker 链路） |
| 关联测试 | `tests/web/test_analysis_depth.py`、`tests/web/test_analysis_depth_mode.py`、`tests/agents/test_analyzer_iteration_gating.py`、`tests/frontend/AnalysisDepthSwitch.test.tsx` |

## 1. 背景与动机

v1.16 引入 `depth ∈ {quick, standard, deep}` 三档时，把"是否启用 iteration / Darwinian 权重链路"拆成了：

- `quick`  → 强制关 iteration
- `standard` → 跟随 `config.iteration.enabled`
- `deep`  → 强制开 iteration

实际生产里出现两个语义模糊：

1. **`quick` vs `standard` 对用户没有可感知差别**——都跑同一份 7 Agent 单次链路，文案上"~30s · ~$0.05 · 跳过辩论/反思"是早期愿景，从未真落地（worker 端 `quick` 和 `standard` 走同一函数路径），UX 上多一档徒增决策摩擦。
2. **`standard` 行为受 `config.iteration.enabled` 隐式 gate**——同一个用户选"标准分析"，系统侧 ops 改了一次 config 之后，行为从"7 Agent 单次"变成"7 Agent + iteration"，用户不知情、客观成本翻倍、产品语义不可预测。

收敛目标：**把"是否开启深度分析"做成一个产品级的二元决定**，与系统侧 iteration 总开关解耦。

## 2. 产品语义（CRD）

### 2.1 标准分析 (`depth = "standard"`，`deep_analysis = false`)

- 走当前普通 7 Agent 单次分析（`StockAnalyzer` 流式分支，**不**调用 `_run_with_weights`）
- **强制不启用** iteration / Darwinian 权重链路（不读 `config.iteration.enabled`）
- 展示文案：「标准分析」/「标准」
- 默认值（用户未明确选择时）

### 2.2 深度分析 (`depth = "deep"`，`deep_analysis = true`)

- 启用 iteration / Darwinian 权重链路（`_run_with_weights`）
- 后续可继续叠加多轮辩论、反思、压力测试等增强能力（v1.0 不引入新增强，仅锁定 gating）
- 展示文案：「深度分析」/「深度」

### 2.3 quick 档不再作为产品入口

- 前端**不**再展示「快速」选项
- 后端**仅**作为兼容输入，自动归一化为 `standard`
- DB 旧值 `quick` 一次性迁移为 `standard`

## 3. 归一化契约

### 3.1 `normalize_analysis_depth(params)` —— 统一入口

```python
# stock_trading_system/portfolio/database.py
def normalize_analysis_depth(params: dict) -> dict:
    """Read both new + legacy fields, return canonical form.

    Returns:
        {"depth": "standard" | "deep", "deep_analysis": bool}

    Priority:
        1. params["deep_analysis"] (bool) — new field, wins if present
        2. params["depth"] (str) — legacy field, mapped via:
              "deep"     → ("deep",    True)
              "standard" → ("standard", False)
              "quick"    → ("standard", False)   # legacy, no longer surfaced
              other/None → ("standard", False)   # safe default
    """
```

**优先级**：`deep_analysis` > `depth`。如果两者都给了且冲突，以 `deep_analysis` 为准（前端只发新字段，旧字段仅给老 client / 任务回放 / DB 兼容）。

### 3.2 `_normalize_depth(value)` —— 旧 API 收敛

保留 `_normalize_depth(value: Any) -> str`，但**返回集合收窄到 `{"standard", "deep"}`**（不再返回 `"quick"`）。所有现有 5 个调用点（`api_analyze`、`api_analysis_history` DTO、`api_history_detail` DTO、`TaskStore._save_analysis_result`、`workers.make_analysis_worker`）都通过这个函数收敛。

```python
VALID_DEPTHS = ("standard", "deep")  # 内部唯一合法集合

def _normalize_depth(v) -> str:
    """Coerce any incoming depth (incl. legacy 'quick') to canonical."""
    if v is None: return "standard"
    s = str(v).strip().lower()
    if s == "quick": return "standard"   # legacy compat
    return s if s in VALID_DEPTHS else "standard"
```

## 4. Iteration 强制语义

### 4.1 `_iteration_enabled` 的新规则

```python
@property
def _iteration_enabled(self) -> bool:
    depth = getattr(self, "_depth_override", None) or "standard"
    if depth == "deep":
        # 系统层禁用了 iteration → 明确降级，不静默
        if not bool(self._config.get("iteration", {}).get("enabled", False)):
            self._iteration_downgrade_reason = (
                "system_iteration_disabled"  # 系统侧 config.iteration.enabled=false
            )
            return False
        return True
    # standard（含旧 quick 归一）—— 永远不开 iteration，
    # 不读 config.iteration.enabled，避免产品开关被系统侧静默改写。
    return False
```

### 4.2 降级语义（深度选择 + 系统禁用）

用户选「深度分析」但系统层 `config.iteration.enabled = false`：

- **不**静默当 iteration 已开
- **不**直接报错（避免影响 ops 的临时关闭权）
- **明确降级为标准模式运行**：
  - logger.warning 一行 `analysis depth=deep downgraded to standard: iteration disabled by system config`
  - 在 `AnalysisResult` 上挂 `iteration_downgraded_reason: "system_iteration_disabled"`
  - worker 把它写到结果 dict（`out["iteration_downgraded_reason"]`），后续可由前端 banner 显示「此次实际按标准模式运行（iteration 已被系统禁用）」（v1.0 不强制 banner，仅持久化字段，留给后续 UX 增强）

## 5. 数据模型

### 5.1 `analysis_history.depth` 字段

- 类型：`TEXT DEFAULT 'standard'`（**不变**，无 schema 改动）
- 取值：仅 `{"standard", "deep"}`（旧值 `quick` / `NULL` 由迁移处理）
- DTO 同时返回：
  - `depth: "standard" | "deep"`
  - `deep_analysis: boolean`（= `depth == "deep"`）

### 5.2 旧值迁移

启动期一次性 migration（幂等）：

```sql
UPDATE analysis_history
   SET depth = 'standard'
 WHERE depth = 'quick' OR depth IS NULL OR depth = '';
```

**位置**：`PortfolioDatabase._migrate_analysis_history` 末尾追加（已有的"v1.16 ALTER TABLE ADD COLUMN depth"分支后）；`TaskStore._ensure_analysis_history_table` 同步追加（TaskStore 在另一个 .db 里维护 analysis_history 副本）。

**幂等性**：每次启动都跑，但只有 `quick`/`NULL`/`""` 行受影响，已经是 `standard`/`deep` 的不动；行数 0 时是 no-op。

## 6. 前端契约

### 6.1 删除三段选择，改单一开关

```tsx
// 删除：
type AnalysisDepth = "quick" | "standard" | "deep"
const DEPTH_OPTIONS = [...]  // 三段选项数组

// 新增：
const [deepAnalysis, setDeepAnalysis] = useState<boolean>(false)
// UI: <Switch checked={deepAnalysis} onCheckedChange={setDeepAnalysis} />
//     label "开启深度分析"
//     hint  "默认标准分析；开启后启用迭代/Darwinian 权重链路"
```

### 6.2 提交体

```ts
apiPost("/api/tasks/submit", {
  type: "analysis",
  params: { ticker, date, deep_analysis: deepAnalysis },
})
```

不再传 `depth` 字段——后端 `normalize_analysis_depth` 接到 `deep_analysis: false/true` 自然产出 `{depth: "standard"|"deep", deep_analysis: <bool>}`。

### 6.3 文案归一

```ts
function depthLabel(d?: string | null, deepAnalysis?: boolean | null): string {
  // 新字段优先
  if (deepAnalysis === true)  return "深度"
  if (deepAnalysis === false) return "标准"
  // fallback 旧 depth 字段（旧记录 / 任务列表 row 仅有 depth）
  switch ((d || "").toLowerCase()) {
    case "deep":     return "深度"
    case "standard": return "标准"
    case "quick":    return "标准"   // 旧 quick 显示为标准
    default:         return "标准"   // NULL / 未知
  }
}
```

### 6.4 显示位置

| 位置 | 文案 |
|---|---|
| AnalysisPage 表单开关 label | `开启深度分析` |
| AnalysisPage 表单开关 off hint | `标准分析（7 Agent 单次）` |
| AnalysisPage 表单开关 on hint | `深度分析（启用迭代 / Darwinian 权重）` |
| 详情页 header badge | `[标准]` / `[深度]` |
| Inbox / 任务列表 RunningRow badge | `标准` / `深度` |
| Inbox CompletedRow badge | `标准` / `深度` |

不再出现 `快速` 文案。

## 7. 后端契约

### 7.1 `/api/tasks/submit` (type=analysis)

```python
# stock_trading_system/web/app.py
# 在路由侧调用 normalize_analysis_depth(data["params"]) 后写回 params
# 这样 TaskStore.params_json 也是清洁的 {ticker, date, depth, deep_analysis}
```

### 7.2 `/api/analyze`（legacy 单点）

同样走 `normalize_analysis_depth`。

### 7.3 `/api/history` 列表 DTO

每行加 `deep_analysis: bool`（与 `depth` 共存）。

### 7.4 `/api/history/<id>` 详情 DTO

加 `deep_analysis: bool`，`depth` 字段保留。

### 7.5 worker (`make_analysis_worker`)

- 入口用 `normalize_analysis_depth(params)`
- 把 `depth` 透传给 `analyzer.analyze(depth=depth)`
- 把 `analyzer.iteration_downgrade_reason`（如果有）写到 `out["iteration_downgrade_reason"]`

## 8. 复用清单（reuse-first）

| 复用对象 | 文件 | 复用方式 |
|---|---|---|
| `_normalize_depth(v)` | `stock_trading_system/portfolio/database.py:32` | 收窄 VALID_DEPTHS 到 `{standard, deep}` + 加 quick→standard 兼容映射，所有 5 个调用点不动 |
| `analysis_history.depth` 列 + ALTER TABLE migration | `stock_trading_system/portfolio/database.py:343-356` | 复用 schema，仅在 migration 末尾追加 UPDATE 旧值的语句 |
| `StockAnalyzer._depth_override` + `_iteration_enabled` | `stock_trading_system/agents/analyzer.py:182-198` | 仅替换 property body，签名不变 |
| `progress_cb` 信号链 / `analysis_pipeline` 事件 | `stock_trading_system/tasks/workers.py:151` | 不动 |
| 前端 `depthLabel()` / InboxRow badge / 详情页 header | `stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx:185` | 替换函数体，调用点不动 |
| 现有测试 `tests/web/test_analysis_depth.py` 9 case | — | 改造其中 quick 相关断言 + 新增覆盖（共 ≥10 case） |

**不动**：`AnalysisResult` dataclass schema、`/api/history` items 列表 schema、TaskStore params_json 序列化机制、`_run_with_weights` 内部、PipelineDAG 步骤定义、详情页 8 tab 展示。

## 9. 验收清单

代码 / 测试 / 文档三项**全部**完成才算修复结束：

- [x] `normalize_analysis_depth` 实装并落地 5 个调用点
- [x] `_iteration_enabled` 收敛为「standard 永远 false / deep 强制 true（系统禁用时降级）」
- [x] `analysis_history.depth` 旧值 `quick`/`NULL` 启动时迁移为 `standard`
- [x] DTO 同时返回 `depth` + `deep_analysis`
- [x] 前端删除三段选择 / 改单一开关 / 提交体改 `deep_analysis`
- [x] 前端 `depthLabel` 不再出现 `快速`
- [x] 测试 ≥10 case 全绿（见 § 11）
- [x] CHANGELOG.md / `docs/design/changelog.md` 已更新

## 10. 边界与不做的事

- 不引入 deep 模式的新增强能力（多轮辩论 / 反思 / 压力测试），那些是后续版本的事
- 不动 LLM 的 `quick_think_llm` / `deep_think_llm` 两档配置（那是 LLM 模型选择，与产品 depth 是两个维度，参见 `llm-fallback.md`）
- 不引入数据库 schema 改动（仅 `UPDATE` 旧值）
- 不为 deep 模式引入新计费逻辑（v1.0 仅锁定 gating，价格暴露由后续产品决定）

## 11. 测试要求（≥10 case）

| # | 测试 | 验证点 |
|---|---|---|
| 1 | `test_submit_deep_analysis_true_persists_deep` | `deep_analysis=true` 提交 → 落库 `depth=deep` |
| 2 | `test_submit_deep_analysis_false_persists_standard` | `deep_analysis=false` → `depth=standard` |
| 3 | `test_legacy_depth_quick_maps_to_standard` | 兼容输入 `depth="quick"` → `standard` |
| 4 | `test_legacy_depth_standard_maps_to_standard` | `depth="standard"` → `standard` |
| 5 | `test_legacy_depth_deep_maps_to_deep` | `depth="deep"` → `deep` |
| 6 | `test_iteration_forced_off_for_standard_even_with_config_enabled` | standard + config.iteration.enabled=true → `_iteration_enabled is False` |
| 7 | `test_iteration_forced_on_for_deep_when_config_enabled` | deep + config=true → True |
| 8 | `test_iteration_downgrade_for_deep_when_config_disabled` | deep + config=false → `_iteration_enabled is False` 且 `_iteration_downgrade_reason="system_iteration_disabled"` |
| 9 | `test_history_dto_returns_both_depth_and_deep_analysis` | DTO 含 `depth` + `deep_analysis` 一致 |
| 10 | `test_legacy_null_depth_dto_renders_as_standard` | DB 旧 NULL row → DTO 返 `{depth:"standard", deep_analysis:false}` |
| 11 | `test_db_migration_quick_rows_become_standard` | 启动 migration 后 DB 里没有 `depth=quick` 行 |
| 12 | `test_frontend_depth_label_never_returns_quick_text` | 前端 `depthLabel` 任意输入都不返回「快速」 |

## 12. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-03 | 初版：把 quick/standard/deep 三档收敛为「标准 / 深度」二档；前端单一开关 `开启深度分析`；后端 `normalize_analysis_depth` 统一兼容新字段 `deep_analysis` 和旧字段 `depth`（含 quick 兼容）；analyzer `_iteration_enabled` 收敛——standard 永远 false（不再读 config.iteration.enabled），deep 强制 true（系统禁用时明确降级 + 记录原因）；DB 旧值启动期迁移 `quick`/`NULL` → `standard`；DTO 同时返回 `depth` + `deep_analysis`；前端 `depthLabel` 移除「快速」文案。**不动** AnalysisResult schema、`/api/history` items 列表 schema、analyzer `_run_with_weights` 内部 |
