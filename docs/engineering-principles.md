# 工程原则（Engineering Principles）

| 项 | 值 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-04-19 |
| 适用范围 | 本仓库所有新增技术方案（[docs/design/](design/)）和实施代码 |

## 1. 核心原则：复用优先

> **"能复用就复用，能从项目中克隆成熟代码就克隆，自己写的越少越好。"**

自写代码是**最后手段**，不是起点。每一行自写代码都有持续维护成本：bug、文档、测试、安全补丁。

## 2. 优先级阶梯

新增功能前，按以下顺序考察可用方案，**停在最上层可用的那一级**：

| 级别 | 形式 | 成本 | 适用情形 |
|---|---|---|---|
| **L0** | **直接调用项目内已有模块** | 最低 | 功能已在本仓库某处实现；只需 import |
| **L1** | **直接使用依赖库** | 低 | 有成熟 pip/npm 包，license 兼容，活跃维护 |
| **L2** | **Vendor / fork 成熟开源项目** | 中 | 项目契合度高、license 允许、需要本地化 |
| **L3** | **clean-room 重写** | 高 | 参考开源项目的设计但 license 不允许直接复制 |
| **L4** | **自写** | 最高 | 以上均不可行，或需求极度定制 |

## 3. 应用规则

### 3.1 任何新设计必须回答

- **L0 复用**：本项目哪些模块可以直接/稍改 import？（至少列 3 个检查点）
- **L1 库**：有哪些成熟库能省掉我这段代码？（明确列出，哪怕最后选 L4 也要说明为何弃用）
- **L2/L3 开源参考**：有哪些开源项目解决了 80%？license 如何？
- **L4 自写部分**：剩下必须自写的是哪些不可避免的胶水/业务逻辑？

### 3.2 技术方案文档约束

每份 [docs/design/](design/) 文档的正文中**必须**有一节 `§ 复用 / Reuse` 明确列出：

```markdown
## § 复用 / Reuse

### L0 项目内复用
- [existing/module.py](../../path) — 用于 X 场景

### L1 依赖库
- `library-name>=X` — 替代自写 Y

### L2/L3 开源参考
- [repo/url](https://...) — license Z；采取 vendor / clean-room / 仅思路

### L4 自写（必要 & 无替代）
- 具体功能 + 行数估算 + 无替代的理由
```

### 3.3 Code review 检查

PR diff 超过 **200 行纯新增代码**时，reviewer 必须问：

> "这 200 行有没有 60% 可以被 L0/L1/L2 替代？"

若答不出清晰理由，PR 退回。

## 4. 反模式

以下写法均视为**违反本原则**：

- ❌ "顺手重写一个简单的 retry 装饰器"（→ `tenacity`）
- ❌ "自己封一个 JSON schema 验证"（→ `pydantic` / `jsonschema`）
- ❌ "写个轻量 HTTP 客户端"（→ `httpx` / `requests`）
- ❌ "实现个简单的任务队列"（→ 现有 `task_manager` / Celery / RQ）
- ❌ "手动解析 LLM JSON 输出"（→ `model.with_structured_output(Schema)`）
- ❌ "写个简单的表格换卡片视图组件"（先看 Bootstrap utility）
- ❌ "新建个配置加载器"（→ 已有 [settings.py](../stock_trading_system/config/settings.py)）

## 5. 审计矩阵（2026-04-19 截止）

对最近 4 份设计文档的复用检查：

### 5.1 [screener-v3.md](design/screener-v3.md) —— 需要修订（重点）

| 原方案（自写） | L0/L1 可替代项 | 节省 | 状态 |
|---|---|---|---|
| 自写 `_llm_reason` 逐 agent 手动解析 JSON | **`ChatOpenAI.with_structured_output(GuruSignal)`**（LangChain 原生 + Pydantic 2）| 每大师 ~30 LOC × 14 = **~420 LOC** | ⚠️ **必改** |
| 自写 `concurrency.py` 指数退避重试 | **`tenacity`**（`@retry(stop=stop_after_attempt(3), wait=wait_exponential())`）| ~30 LOC | ⚠️ **必改** |
| 自写 `roundtable.py` 双大师 2 轮辩论 | **复用 [TradingAgents bull_researcher.py + bear_researcher.py + conservative_debator.py + reflection.py](/opt/anaconda3/lib/python3.12/site-packages/tradingagents/agents/)** 作辩论基底，仅替换角色身份 prompt | ~150 LOC | ⚠️ **必改** |
| 自写 `GuruDataBundle` dataclass | 扩展现有 [v2/data_helper.py](../stock_trading_system/screener/v2/data_helper.py)，不另建 | 小 | 建议改 |
| 自写 `stream.py` WebSocket 广播 | 复用现有任务中心的 WebSocket 推送路径（[tasks/workers.py](../stock_trading_system/tasks/workers.py) 已有进度推送）| 中 | 建议改 |
| 14 大师 clean-room 重写 | 尝试 L2：[KRSHH/ritadel](https://github.com/KRSHH/ritadel) MIT（包含 7 位大师）—— **但其 MIT 对从 virattt copy 来的代码无法合法授予**，法律风险仍在；保留 clean-room | 不变 | 保留 |

**结论**：screener-v3.md 必须更新 §4.1 / §4.3 / §4.9 三节，把三项"自写"降级为复用。预计自写代码从 ~1200 LOC 降到 ~700 LOC（-40%）。

### 5.2 [multi-tenant.md](design/multi-tenant.md) —— 基本合理，小改进

| 原方案 | 可替代项 | 状态 |
|---|---|---|
| 自写 auth 模块（session/decorators） | 考虑过 **Flask-Login**，因规模小拒绝 | 明示 tradeoff，保留 |
| `bcrypt` | 已用 L1 | ✓ |
| `Flask-WTF` CSRF | 已用 L1 | ✓ |
| 邀请码用 `secrets.token_urlsafe` | L1 标准库 | ✓ |
| 邮箱格式校验未明确 | 建议 L1 `email-validator` | 小改 |
| 迁移脚本自写 sqlite3 | Alembic 通常 overkill（项目非 SQLAlchemy）| 保留 |

**结论**：基本合理。补充 `email-validator` 到依赖即可，不出正式修订。

### 5.3 [mobile-optimization.md](design/mobile-optimization.md) —— 合理，记录 tradeoff

| 原方案 | 可替代 | 状态 |
|---|---|---|
| `.form-row-mobile` | Bootstrap 5 `col-12 col-md-*` | 现有 markup 用 `col-6`，不改 markup 只加 media query → 合理 |
| `.table-to-cards` | Bootstrap `.table-responsive`（横滑）| 不等价（要卡片化降级），保留 |
| `.tabs-scrollable` | Bootstrap Nav 无 scroll-snap | 保留 |
| `.collapse-row` | Bootstrap `data-bs-toggle="collapse"` | **可以改用 Bootstrap collapse API 承载，省~20 LOC JS** | 建议改 |
| `.chip-row` | Badge + flex-wrap | 需水平滚动 snap，保留 |
| `.btn-group-wrap` | Bootstrap `.btn-group` + `flex-wrap` utility | **可用 Bootstrap `d-flex flex-wrap`** | 建议改 |
| `.num-responsive` | 纯 CSS `clamp()` | 标准，保留 |

**结论**：`.collapse-row` 和 `.btn-group-wrap` 两处可降级为 Bootstrap 原生。非阻塞性，可在实施时顺手调整。

### 5.4 [model-switch.md](design/model-switch.md) —— 保留，注明理由

| 原方案 | 可替代 | 状态 |
|---|---|---|
| 自写 `llm/router.py` | **LangChain `init_chat_model("qwen/qwen-plus")`** 支持 provider-string init | 本项目调用点最终 delegate 到 TradingAgents factory，LangChain init 帮不上；**保留**，但若未来脱离 TradingAgents 可重构 |
| `QwenTextClient` / `GeminiTextClient` | `langchain_openai.ChatOpenAI` / `langchain_google_genai.ChatGoogleGenerativeAI` | 其实这两个类就是 L0 —— 我们可以让 `QwenTextClient` 内部直接持有 `ChatOpenAI` 而不是新起 OpenAI client | 小改 |

**结论**：主体合理，但 client.py 内部可以更薄（直接持有 LangChain 的 ChatOpenAI 实例）。作为实施阶段的优化项。

### 5.5 [hardening-iteration-v1.md](design/hardening-iteration-v1.md) —— 复用比例 73%，符合原则（2026-05-13 方案审计）

5-Phase 硬化迭代（[hardening-iteration-v1.md](design/hardening-iteration-v1.md) v1.0）按本原则盘点：

| Phase | 主要项 | L0 / L1 / L2 / L4 LOC | 复用比例 |
|---|---|---|---|
| **P0 安全底座** | CSRFProtect / @admin_required / IDOR / 限流 / error_handler | L1×2（Flask-WTF 已依赖未接入 + Flask-Limiter）+ L0×1（auth/decorators 已存）+ L4×50（error_handler）| 90% |
| **P1 多租户契约** | Telegram authz / 删 legacy / `_user_id() raise` / cross_user_access 矩阵 / invariants | L0×4（auth/repository + validation/* 全扩）+ L4×160（业务专有授权 + 契约）| 60% |
| **P2 数据可信度** | LocalCache ttl / Pickle→JSON / themes.yaml / utils/timez / Paper Decimal / Polygon lock / Quote | L1×3（pydantic 已用 + zoneinfo + Decimal stdlib）+ L4×230（业务专有 + Decimal 化）| 50% |
| **P3 业务版本收敛** | v1/v2→v3 / backtest.py 退役 / DataManager 收口 / 迁移 runner / schema 统一 | L0×2（screener.v3.pipeline + strategy.backtester）+ L2×1（yoyo-migrations 思路 80 LOC）+ L4×80（runner + schema 抽取）| 80% |
| **P4 Web 拆分** | Blueprint × 11 + service 提取 + request_id + audit middleware | L4×50（中间件）+ 纯搬运 | 95%（搬运不算新增） |

**总体**：~520 LOC 自写 / 1390 LOC 删除 ≈ **净 -870 LOC**，自写占（写 + 复用）比例 **27%**，即**复用比例 73%**——符合 §3.3 "PR 200 行纯新增问 60% 可否替代" 红线。

**重点复用证据**（每条都来自本仓库已有代码 / 已声明依赖）：

| 方案条目 | 复用来源 | 行数节省 |
|---|---|---|
| P0.1 CSRFProtect 接入 | `requirements.txt` 已含 `Flask-WTF>=1.2`（[multi-tenant.md §5.1](design/multi-tenant.md) 已声明但 web/app.py 未接入）| 自写 ~120 LOC |
| P0.2 @admin_required 补装 | `auth/decorators.py:22` 已实现 | 自写 ~30 LOC |
| P0.4 Flask-Limiter 限流 | L1 库（pip 现成）| 自写 ~80 LOC |
| P0.3 alerts/portfolio owner 强制 | `auth/repository.py` user_id pattern 已成熟 | 设计参考节省 ~50 LOC |
| P1.4 cross_user_access 矩阵 | `validation/cross_user_access.py` 已有 3 条用例 + fixture | 矩阵扩展不另起框架 |
| P1.5 invariants 不变式 | `validation/invariants.py` 已有 10 条 | 同上 |
| P3.1 screener v3 sync wrapper | `screener/v3/pipeline.py` 已成熟 | 删除 v1/v2 共 ~600 LOC |
| P3.2 BacktestEngine 替换 Backtester | `strategy/backtester.py` 已成熟（worker 已用）| 删除 backtest.py ~300 LOC |
| P3.6 PortfolioDatabase WAL | `tasks/task_store.py:118` 已有 `PRAGMA WAL + busy_timeout` | 抄 ~5 LOC |
| P2.5 utils/timez | `zoneinfo` stdlib | 自写仅 alias ~30 LOC |
| P2.6 Paper Decimal | `decimal.Decimal` stdlib | 自写仅业务路径 ~150 LOC |
| P2.7 Quote 抽象 | `pydantic>=2` 已用 | 自写仅模型 ~30 LOC |

**反面观察**：本方案有一条违反了 §4 反模式的设计冲动——**P3.4 迁移 runner**（~80 LOC clean-room）原本可考虑 [alembic](https://alembic.sqlalchemy.org/) 或 [yoyo-migrations](https://ollycope.com/software/yoyo/) L1 库直接接入。决策保留自写的理由：(a) 项目非 SQLAlchemy 栈，alembic 接入需引入 SQLAlchemy 反向工程整套体系（>500 LOC + 抽 ORM）超额；(b) yoyo 良好但额外引入运行时依赖与 8 个现有 Python-function-style 迁移脚本风格不齐，迁移本身简单（applied_migrations 表 + 顺序跑），自写 80 LOC 维护成本低于库升级成本。**保留**，但实施时若 yoyo-migrations 体验充分覆盖需求则切到 L1。

**结论**：方案落地前的复用审计**通过**。实施过程中如自写 LOC 超额 20%（>624 LOC），需停下重审。

## 6. 本次审计产生的修订动作

| 文档 | 动作 | 优先级 |
|---|---|---|
| [design/screener-v3.md](design/screener-v3.md) | 新增 §13 "复用 / Reuse"；修订 §4.1（with_structured_output）/ §4.3（tenacity）/ §4.9（TradingAgents 辩论图复用）| **P0** |
| [design/mobile-optimization.md](design/mobile-optimization.md) | 实施时优先尝试 Bootstrap collapse / flex utility；不改文档 | P2 |
| [design/multi-tenant.md](design/multi-tenant.md) | requirements.txt 加 `email-validator`；不改文档 | P2 |
| [design/model-switch.md](design/model-switch.md) | 实施优化项；不改文档 | P2 |
| [design/hardening-iteration-v1.md](design/hardening-iteration-v1.md) | 复用审计**通过**（73% 复用率）；实施过程自写超额 20% 时停下重审；P3.4 迁移 runner 实施期可尝试 yoyo-migrations L1 切换 | **P1** |

## 7. 未来文档作者检查清单

创建新 `docs/design/*.md` 时自检：

- [ ] 文档正文含 `§ 复用 / Reuse` 小节，四级全部列出
- [ ] L0 至少列 3 个本仓库检查位置
- [ ] L1 列出至少 5 个候选库（哪怕最后不用）
- [ ] L2/L3 至少一条开源项目检索证据（"找过、没合适" 也算）
- [ ] 自写部分每块说明"为何不能用上面任何一级"
- [ ] changelog 条目最后一列含 "复用比例：N%"（可选但推荐）

## 8. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.1 | 2026-05-13 | 新增 §5.5 [hardening-iteration-v1.md](design/hardening-iteration-v1.md) 复用审计：5 Phase 总复用率 73%（自写 ~520 / 复用+删除 1390）；P0 复用率 90%（CSRFProtect / @admin_required 全 L0+L1）；P3.4 迁移 runner 自写 80 LOC 保留但留 L1 切换口子；§6 加方案修订动作表条目。**审计结论：通过**。 |
| v1.0 | 2026-04-19 | 初版：复用优先原则 + 4 级阶梯 + 最近 4 份设计审计矩阵 + 对 screener-v3 产生 3 处 P0 修订 |
