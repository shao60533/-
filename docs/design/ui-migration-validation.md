# 技术方案：UI 迁移完整验证计划

| 项 | 值 |
|---|---|
| Feature | `ui-migration-validation` |
| 版本 | v1.0 |
| 日期 | 2026-04-24 |
| 关联测试 | [../test-cases/ui-migration-validation.md](../test-cases/ui-migration-validation.md) |
| 触发 | [ui-react-island](./ui-react-island.md) v1.0 + v2.0 实施完毕后、上线前 |

## 1. 背景

过去数周累积的架构级改动对系统造成**同时多维度**影响：

| 模块 | 涉及范围 | 风险面 |
|---|---|---|
| [multi-tenant](./multi-tenant.md) v1.0 | `users` / `invite_codes` / `user_settings` 3 张新表 + 6 类私有表加 `user_id` FK + Flask session 认证 + CSRF | 数据归属、会话、权限泄露 |
| [model-switch](./model-switch.md) v1.0 | `llm_provider` 路由优先级链 + analyzer graph per-provider 缓存 | 用户级 provider 隔离失效、默认回退错位 |
| [screener-v3](./screener-v3.md) v1.0/v1.1 | 14 大师 agent + Pipeline + `task_events` 流 + Round-table | 结果一致性、进度事件丢失 |
| [paper-trade](./paper-trade.md) v1.3 | 5 处 UX 修正：Plan dedup / AI 决策 surface / `executive_summary` 列 / 图表 / tabs 合并 | 老 plan 数据回填、executive_summary 抽取失败 |
| [unified-progress](./unified-progress.md) v1.0 | `task_events` 表 + `emit_event()` + per-user room + catch-up API | 事件泄露、重连丢失、历史堵塞 |
| [mobile-optimization](./mobile-optimization.md) v1.0 | 11 页 CSS tokens + 7 通用组件 | 桌面视觉回归、旧页兼容 |
| [ui-react-island](./ui-react-island.md) v1.0/v2.0 | React 取代 Jinja 前端（11 页迁移）+ Vite 构建管道 + Railway 部署 | 路由切换、数据接线遗漏、视觉不一致 |

**单独做一次系统性验证不可省**，因为单模块测试用例无法覆盖跨模块耦合爆发的 bug。

## 2. 目标

在上线到生产环境前，通过**多层次验证**确认：

1. **零数据丢失**：迁移前后所有业务表 row 数一致、抽样字段一致
2. **零权限泄露**：user A 无法通过任何路径看 user B 的私有数据
3. **功能对等**：旧 Jinja UI 中可达的每个功能，在新 UI 中等价可达
4. **跨模块稳定**：screener-v3 → paper-trade → analysis 完整链路跑通
5. **实时可达**：task progress / SocketIO 事件按时序送达
6. **回滚可行**：任一 Phase 失败可 revert 到上一稳态
7. **生产可用**：Railway 部署产物与 staging 行为一致

### 2.1 验收阈值

| 维度 | 阈值 |
|---|---|
| 数据完整性 | 100%（一行不差） |
| 功能回归矩阵（本文 §6） | pass = 100% · waive 允许 ≤ 5%（需备注） |
| 跨模块集成用例 | 100% pass |
| 性能（LCP / TTI / 任务端到端）| 与迁移前偏差 ≤ ±15% |
| 安全（CSRF / 越权）| 0 漏洞 |

任一维度未达标 → **不允许生产部署**。

## 3. 验证层次（L0-L5）

按时间成本与覆盖度分层。部署到 staging 之前至少走完 L0-L3；生产切流前必须完整 L0-L5。

| 层 | 时长 | 覆盖面 | 自动化 | 执行时机 |
|---|---|---|---|---|
| **L0 · 冒烟** | 5 min | 能登录、首页渲染、发一个任务完成 | 半自动 | 每次 commit 后 |
| **L1 · 基础页面** | 30 min | 11 页全部打开 + 基础 CRUD | E2E 自动 | Phase 结束前 |
| **L2 · 功能回归** | 2h | 每个 PRD 列的功能逐个 | E2E + 手工 | Staging 部署后 |
| **L3 · 跨模块集成** | 4h | 多模块串联场景 20 条 | 手工 | Staging 稳定后 |
| **L4 · 数据完整性** | 1h | SQL 级别 row count + 抽样 + 约束 | 全自动脚本 | 迁移脚本跑完即刻 |
| **L5 · 对抗性** | 2h | 并发、session 边界、强制错误 | 半自动 | 上线前最后一关 |

**共 ~9.5h**。

## 4. 数据完整性验证（L4）

核心问题：**改了 schema、加了 user_id 列、跑了 3+ 个迁移脚本，怎么证明数据一行没丢？**

### 4.1 迁移前快照（MUST 在任何迁移前执行）

```bash
# 1. 完整数据库备份
cp portfolio.db portfolio.db.pre-migration-$(date +%Y%m%d).bak

# 2. 生成每张表的行数 + 列校验和基线
python -m stock_trading_system.validation.snapshot \
  --out validation/snapshot-pre.json
```

**`validation/snapshot.py`（新增脚本）** 产出结构：

```json
{
  "generated_at": "2026-04-24T10:00:00Z",
  "db_path": "portfolio.db",
  "tables": {
    "positions": {
      "row_count": 128,
      "checksum": "a3f2...",              // sha1 of sorted rows (ignoring volatile columns like updated_at)
      "min_id": 1,
      "max_id": 128,
      "sample_rows": [ {... row 1 ...}, {... row 42 ...} ]  // 确定性抽样
    },
    "transactions": { ... },
    "analysis_history": { ... },
    ...所有 14+ 张表
  }
}
```

**抽样策略**：固定随机种子 `seed=42`，抽 10 行（或 5%，取大）。迁移后可按相同 seed 取同一批行对字段。

### 4.2 迁移后对比

```bash
# 迁移完成后
python -m stock_trading_system.validation.snapshot \
  --out validation/snapshot-post.json

python -m stock_trading_system.validation.compare \
  --pre validation/snapshot-pre.json \
  --post validation/snapshot-post.json
```

**对比脚本**检查：

| 检查项 | 规则 | 失败即 block |
|---|---|---|
| **行数一致** | `post.row_count == pre.row_count`（所有迁移前已存在的表）| ✅ |
| **行数增长**（新增表）| `post.row_count >= 0`（users/invite_codes/user_settings/task_events 等新表允许空）| — |
| **主键连续** | `min_id / max_id` 保持（若自增 PK） | ✅ |
| **抽样字段**（ticker/date/金额等业务字段）| 10 行对比，所有非迁移列字段逐字段 `==` | ✅ |
| **新增列默认值** | 如 `positions.user_id` 全部 = admin_id | ✅ |
| **外键完整性** | 所有 `user_id` / `session_id` / `task_id` FK 必须 resolve | ✅ |

### 4.3 业务一致性检查

仅 row count 对比不够，必须验证**业务不变量**：

```python
# stock_trading_system/validation/invariants.py
INVARIANTS = [
    # 每个 position 都属于某用户
    ("positions_have_owner",
     "SELECT COUNT(*) FROM positions WHERE user_id IS NULL", 0),

    # transactions 对 positions 的持仓求和一致（长期投资场景）
    ("transactions_match_positions",
     """SELECT p.ticker, p.user_id, p.shares,
               COALESCE(SUM(CASE WHEN t.action='BUY' THEN t.shares ELSE -t.shares END), 0) AS net
        FROM positions p LEFT JOIN transactions t
          ON p.ticker=t.ticker AND p.user_id=t.user_id
        GROUP BY p.ticker, p.user_id
        HAVING p.shares != net""", 0),

    # 所有 paper_trade_plans 都有指纹（v1.3 迁移后）
    ("plans_have_fingerprint",
     "SELECT COUNT(*) FROM paper_trade_plans WHERE fingerprint IS NULL", 0),

    # tasks.created_by 字符串全部升级为 FK
    ("tasks_created_by_is_int",
     "SELECT COUNT(*) FROM tasks WHERE typeof(created_by) = 'text'", 0),

    # analysis_history 的新列默认允许 NULL（executive_summary 可能未回填）
    # 但 trade_decision 不可为空
    ("analysis_have_decision",
     "SELECT COUNT(*) FROM analysis_history WHERE trade_decision IS NULL", 0),

    # alerts 都绑用户
    ("alerts_have_owner",
     "SELECT COUNT(*) FROM alerts WHERE user_id IS NULL", 0),

    # paper_trade_sessions 都绑用户
    ("paper_sessions_have_owner",
     "SELECT COUNT(*) FROM paper_trade_sessions WHERE user_id IS NULL", 0),

    # invite_codes 若有 used_by，其用户必存在
    ("invites_used_by_valid",
     """SELECT COUNT(*) FROM invite_codes
        WHERE used_by IS NOT NULL
          AND used_by NOT IN (SELECT id FROM users)""", 0),

    # task_events 所有 user_id 必须有效
    ("task_events_user_valid",
     """SELECT COUNT(*) FROM task_events
        WHERE user_id NOT IN (SELECT id FROM users)""", 0),

    # paper_trade_strategy_events.session_id 必须存在
    ("paper_events_session_valid",
     """SELECT COUNT(*) FROM paper_trade_strategy_events
        WHERE session_id NOT IN (SELECT id FROM paper_trade_sessions)""", 0),
]
```

**运行**：

```bash
python -m stock_trading_system.validation.invariants
```

任一不变量失败 → **停止上线**。

### 4.4 归属迁移验证（admin 继承老数据）

[multi-tenant v1.0](./multi-tenant.md) 的首次启动把老数据归给 admin。验证：

```sql
-- 迁移前 positions 总数 == 迁移后 admin 的 positions 数
SELECT COUNT(*) FROM positions WHERE user_id = (SELECT id FROM users WHERE email='admin@local');
-- 预期 == snapshot-pre.json positions.row_count

-- 同理 alerts / paper_trade_sessions / transactions
```

## 5. 功能回归矩阵（L2）

把**迁移前可达的每个功能**列成矩阵，新旧 UI 各验一次。矩阵在 [test-cases/ui-migration-validation.md](../test-cases/ui-migration-validation.md) 里完整展开。

### 5.1 矩阵骨架

| 页 | 功能 | 入口 | 期望结果 | 新 UI pass | 老 UI pass | 备注 |
|---|---|---|---|---|---|---|
| Dashboard | 显示总值 | `/` | 数字 == portfolio_summary | | | |
| Dashboard | 显示今日 PnL | `/` | 数字 == calc_from_snapshots | | | |
| Analysis | 触发分析 | `/analysis` → 提交 | task_id 返回 + SocketIO 流出 | | | |
| ... | ... | ... | ... | | | |

**每页至少覆盖**：
- 基础渲染（空态 + 数据态）
- 主 CTA（买入/分析/筛选/新建预警 等）
- 行内操作（删除/编辑/复制）
- 筛选 + 搜索
- 排序 + 分页（若有）
- 权限隔离（user A 不见 user B 私有）

### 5.2 执行方式

**自动化**：Playwright 脚本执行 E2E 用例（见 [test-cases 文档 §2](../test-cases/ui-migration-validation.md#2-自动化-e2e-用例)）。

**手工**：视觉敏感 + 主观判断项（见 [test-cases §3](../test-cases/ui-migration-validation.md#3-手工-checklist)）。

## 6. 跨模块集成验证（L3）

矩阵测试只能覆盖单页单功能。**真正的 bug 来自多模块叠加**。列出 20 条必跑的端到端场景：

### 6.1 关键集成场景

| # | 场景 | 涉及模块 | 预期 |
|---|---|---|---|
| 1 | alice 选 Qwen，触发 screener-v3，bob 选 Gemini 同时触发 | multi-tenant + model-switch + screener-v3 + unified-progress | 两人 provider 不互相污染；进度事件按 user 隔离 |
| 2 | alice 触发分析，登出，2h 后登录，看到 task 已 success | multi-tenant + unified-progress | catch-up 成功补齐事件 |
| 3 | alice paper-trade 触发 → analysis 生成 → plan dedup → tier 进度 | paper-trade v1.3 + analysis + unified-progress | 同指纹不 insert 新 plan，reconfirmed_count++ |
| 4 | admin 生成邀请码 → bob 注册 → 登录 → 看到共享 analysis_history 但空 portfolio | multi-tenant | 权限边界正确 |
| 5 | alice 设 llm_provider=gemini → UI 立即显示 Gemini → 下次分析日志证实 | model-switch + ui-react-island | 用户级覆盖生效 |
| 6 | 5 个用户并发触发 screener-v3 | 所有 async 模块 | 无事件 cross-talk，资源不爆 |
| 7 | 迁移后登录 admin → dashboard 显示迁移前的持仓总值 | multi-tenant migration | 老数据归属正确 |
| 8 | 删除 alice（软删）→ 她的 analysis_history 仍共享可见但无 bookmark 入口 | multi-tenant | 软删不破坏共享数据 |
| 9 | alice 关浏览器期间任务完成 → 再开看到 task_completed 事件补齐 + 结果页可读 | unified-progress | seq + catch-up 正确 |
| 10 | Railway 部署新版本 → 旧 session cookie 仍有效登录 | 部署 + multi-tenant | cookie 不过期 |
| 11 | alice 在 iPhone Safari 上完成完整 paper-trade 流程 | mobile-optimization + paper-trade + ui-react-island | 触摸 / 响应式 / 日度图表都可用 |
| 12 | Bookmark 某 analysis → 其他用户看不到 bookmark 标记 | multi-tenant | 私有 bookmark 正确 |
| 13 | model-switch Qwen → Gemini 即时切换，正在跑的旧 task 用 Qwen 跑完，新 task 用 Gemini | model-switch | graph 按 provider 缓存 |
| 14 | 诊断 screener-v3 → 14 大师 + round-table 全量跑完 → 结果与设计 schema 一致 | screener-v3 v1.0/v1.1 | Pydantic 结构化输出解析成功 |
| 15 | paper-trade plan 指纹一致时 reconfirmed_count 正确累加 | paper-trade v1.3 F1 | 并发下也正确（2 线程同时）|
| 16 | executive_summary 生成失败时 thesis 显示占位，不写 "regex 解析" | paper-trade v1.3 F3 | grep "regex 解析" 仓库 0 命中 |
| 17 | Tasks 页"全部"tab 显示所有人的任务但只能取消自己的 | multi-tenant + unified-progress | 权限 403 |
| 18 | Analysis 详情 8 tab 切换（桌面 + 移动）流畅 | ui-react-island + mobile-optimization | ≤767 tabs-scrollable |
| 19 | 导出 PDF / MD 正常生成 → 下载可用 | analysis export | 异步任务走通 |
| 20 | 回滚一个 Phase（git revert）→ 前端降级 → 数据不变 | 回滚预案 | 未迁页面继续工作 |

每条场景在 [test-cases §4](../test-cases/ui-migration-validation.md#4-跨模块集成脚本) 有脚本化步骤。

## 7. 性能验证（与 L4 一起做）

### 7.1 基线 vs 现状

对比迁移前 / 迁移后：

| 指标 | 迁移前 | 迁移后目标 |
|---|---|---|
| 首页 LCP（4G throttle） | baseline | ≤ baseline × 1.15 |
| Analysis 详情 TTI | baseline | ≤ baseline × 1.15 |
| screener-v3 任务端到端 | baseline（若可对比）| 不超 +15% |
| Railway cold start | baseline | ≤ baseline + 30s（含 npm build） |
| 单 island JS gzipped | n/a | ≤ 180KB |
| portfolio.db 体积 | baseline | ≤ baseline × 1.05（新增表 + 索引）|

### 7.2 自动化

```bash
# Lighthouse CI
npx lhci autorun --config=.lighthouserc.json

# 对比报告
python -m stock_trading_system.validation.perf_compare \
  --before perf/baseline.json \
  --after perf/post.json
```

## 8. 安全验证（L5）

### 8.1 越权测试矩阵

写自动化脚本 `validation/cross_user_access.py`：

```python
# 2 个 fixture user: alice / bob
# 逐条测试 alice 尝试访问 bob 的资源
FORBIDDEN_PATHS = [
    f"/paper-trade/<bob_session_ticker>",
    f"/api/portfolio/<bob_ticker>",
    f"/api/alerts/<bob_alert_id>",
    f"/api/paper/sessions/<bob_session_id>/trades",
    f"/api/tasks/<bob_task_id>/cancel",  # POST
]

# 所有路径应返回 403 / 404（不是 200）
for path in FORBIDDEN_PATHS:
    assert as_alice(path).status in (403, 404), f"LEAK: {path}"
```

### 8.2 CSRF 验证

- 所有 POST/PUT/DELETE fetch 缺 `X-CSRFToken` → Flask 返回 403
- 伪造 CSRF token → 403
- GET 请求不需要 CSRF（保持兼容）

### 8.3 Session 验证

- HttpOnly cookie：`document.cookie` 在浏览器里读不到 session cookie
- SameSite=Lax：跨域 POST 不携带
- 登出后原 cookie 的任何 API 请求均 401
- `SESSION_VERSION_KEY` 升级后老 session 自动失效

### 8.4 未登录保护

- 所有 `/api/*`（除 auth + health）未登录返回 401
- 所有页面路由（除 `/login` / `/register` / `/reset`）重定向到 `/login?next=<path>`
- SocketIO 连接无 session → 直接拒绝

## 9. 回滚预案（L5 的一部分）

### 9.1 数据库回滚

```bash
# 数据库恢复（迁移失败）
cp portfolio.db.pre-migration-20260424.bak portfolio.db
systemctl restart stock-trading   # 或 Railway 重部署
```

### 9.2 代码回滚

按 Phase 粒度：

```bash
git log --oneline | grep "feat(ui)"
# ui-v2 每个 Phase 独立 commit
git revert <bad-phase-commit>
# 或整体回滚
git revert <first-ui-v2-commit>..HEAD
```

Flask 路由 `@app.route("/")` 改回 `render_template("index.html")` → 老 SPA 立即可用。

### 9.3 前端降级

若某 island 有 bug 但数据已变化：

1. Flask 路由切回 `render_template("index.html")` 同时 `hash="/old-page"`
2. 旧 `app.js` 会读 hash 显示对应旧 tab
3. 后端数据（加了 user_id 列的表）对旧 `app.js` 透明（它查询时默认不带 WHERE user_id，会报 SQL 错 —— 需要提前预案：旧 `app.py` 查询也加 WHERE，或在上线前 ensure 旧代码已兼容 user_id scope）

**关键**：**不允许回滚到 [multi-tenant](./multi-tenant.md) 之前的 schema**，因为新表新列不能回滚。数据库只能前滚。

### 9.4 feature flag（预留）

若某 island 想快速隐藏：
- Flask 路由加环境变量开关：`ENABLE_REACT_SCREENER_V3=true`
- 为 false 时 `render_template("index.html")` + hash
- 可不改代码重启生效

## 10. 执行流程

### 10.1 Pre-flight（部署前 1-2 天）

```
Day -2:
  [ ] L4 迁移前快照（staging + production 各一份）
  [ ] L1 基础页面 E2E 跑通（staging）
  [ ] L2 功能回归 70% 完成

Day -1:
  [ ] L2 剩余 30% 完成
  [ ] L3 跨模块集成 20 条全部通过
  [ ] L5 越权 / CSRF / session 验证通过
  [ ] 性能对比报告（L4 并行）
  [ ] 回滚脚本演练（staging 真实回滚一次，验证流程）

Day 0（上线日）:
  [ ] 维护窗口公告
  [ ] 生产迁移（运行迁移脚本）
  [ ] L4 产品数据对比（生产 pre vs post snapshot）
  [ ] L0 冒烟：登录 + 首页 + 1 任务
  [ ] L2 快速抽 10% 跑一遍
  [ ] 发公告：上线成功
```

### 10.2 Post-deploy（上线后 1 周）

```
Hour +1:
  [ ] 监控错误日志 → 0 严重错误才算 OK
  [ ] 监控 /health
  [ ] 手工点 3 个用户账号各跑完整流程

Day +1:
  [ ] 错误率 < baseline × 1.5 → OK
  [ ] 用户反馈通道（TBD）收集

Day +3:
  [ ] 性能基线重测，确认无显著回退

Day +7:
  [ ] 最终 go/no-go：若所有指标 OK → 宣布迁移成功
  [ ] 否则：启动 hotfix 或回滚
```

## 11. 验证工具

### 11.1 新增脚本目录

```
stock_trading_system/validation/
├── __init__.py
├── snapshot.py            # 生成表快照（row count + checksum + 抽样）
├── compare.py             # 对比 snapshot 前后
├── invariants.py          # 业务不变量 SQL 检查
├── cross_user_access.py   # 越权测试
├── perf_compare.py        # 性能对比
└── smoke.py               # L0 冒烟脚本（5 min）

tests/validation/
├── test_multi_tenant_isolation.py   # 自动化 L3
├── test_migration_integrity.py      # 自动化 L4
└── test_cross_user.py               # 自动化 L5 越权
```

### 11.2 统一入口

```bash
# 一键全量验证（L0-L5）
python -m stock_trading_system.validation.run_all \
  --level full \
  --report validation/report-$(date +%Y%m%d).json

# 仅冒烟（CI）
python -m stock_trading_system.validation.run_all --level smoke
```

输出报告 JSON：

```json
{
  "started_at": "2026-04-24T10:00:00Z",
  "finished_at": "2026-04-24T19:30:00Z",
  "db_path": "portfolio.db",
  "levels": {
    "L0_smoke":       { "pass": 5,  "fail": 0,  "duration_sec": 284 },
    "L1_basic":       { "pass": 33, "fail": 0,  "duration_sec": 1745 },
    "L2_functional":  { "pass": 72, "fail": 2,  "duration_sec": 7200 },
    "L3_integration": { "pass": 18, "fail": 2,  "duration_sec": 12400 },
    "L4_data":        { "pass": 14, "fail": 0,  "duration_sec": 3200 },
    "L5_adversarial": { "pass": 10, "fail": 0,  "duration_sec": 6300 }
  },
  "failures": [
    { "level": "L2_functional", "case": "alerts-history-mobile", "reason": "..." },
    { "level": "L3_integration", "case": "scenario-11", "reason": "..." }
  ],
  "go_no_go": "NO_GO"   // 或 "GO" / "GO_WITH_WAIVERS"
}
```

### 11.3 用户 sign-off

所有 L0-L5 pass + 0 CRITICAL waiver → 用户（admin）在终端签字：

```bash
python -m stock_trading_system.validation.sign_off \
  --report validation/report-20260424.json \
  --signer admin@local
# → validation/sign-off-20260424.json 含 admin 凭证哈希 + 时间戳
```

这个文件是**允许生产部署的凭证**。

## 12. 记录模板

每次验证执行留档在 `validation/runs/<date>/`：

```
validation/runs/2026-04-24/
├── snapshot-pre.json
├── snapshot-post.json
├── compare.diff.json
├── invariants.json
├── l0_smoke.log
├── l2_functional.playwright-report/
├── l3_integration-manual.md         # 手工 checklist 填表
├── l4_data.json
├── l5_adversarial.log
├── perf_compare.html
├── report.json                       # 聚合总报告
└── sign-off.json                     # 签字凭证
```

保留 ≥ 90 天用于审计。

## 13. 复用 / Reuse

遵循 [engineering-principles.md](../engineering-principles.md)：

- **L0**：现有 Flask / SQLAlchemy / SQLite / pytest / Playwright / Lighthouse CI
- **L1**：`hashlib` / `pytest-xdist`（并发）/ `playwright`
- **L4 自写**（业务特定）：~400 LOC 验证脚本（snapshot / compare / invariants / cross_user / sign_off）

无新依赖。

## 14. 风险与假设

| 风险 | 缓解 |
|---|---|
| 迁移脚本在生产比 staging 数据量大 10 倍 → 耗时不可预估 | Pre-flight 在 staging 用生产数据镜像跑一次，记录时间 |
| 某个隐蔽的业务不变量未覆盖 | L4 invariants 脚本设计时列了 10 条，留一项"user 反馈发现再补" |
| Playwright 自动化用例覆盖不全导致漏过视觉回归 | 手工 checklist 作兜底 |
| 生产 L4 snapshot 产出需要停写操作 | 维护窗口明确公告（~30 min） |
| 签字流程形式大于内容 | admin 实际跑一次主流程再签字，而非仅点按钮 |

## 15. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-24 | 初版：6 层验证（L0 冒烟 → L5 对抗性）+ 数据完整性 snapshot/invariant 设计 + 20 条跨模块集成场景 + 回滚预案 + 统一执行入口 + 签字凭证 |
