# 测试用例：UI 迁移完整验证

| 项 | 值 |
|---|---|
| Feature | `ui-migration-validation` |
| 版本 | v1.0 |
| 日期 | 2026-04-24 |
| 关联设计 | [../design/ui-migration-validation.md](../design/ui-migration-validation.md) |

## 汇总

| 层 | 用例数 |
|---|---|
| L0 冒烟（自动） | 5 |
| L1 基础页面（自动 E2E） | 33 |
| L2 功能回归矩阵（手工+自动） | 74 |
| L3 跨模块集成（20 场景脚本） | 20 |
| L4 数据完整性（SQL + script） | 14 |
| L5 对抗性（越权+CSRF+session+并发） | 18 |
| **总计** | **164** |

---

## 1. L0 冒烟（5 条，~5 min）

**目的**：确认主干没挂。每次部署后、每个 Phase commit 后跑。

### TC-VAL-L0-1：Flask 启动 + /health

```bash
curl -sf http://localhost:5000/api/health | jq .status
# 期望: "ok"
```

### TC-VAL-L0-2：登录 admin

```bash
curl -c cookies.txt -sf -X POST http://localhost:5000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@local","password":"<admin-pw>"}' | jq .user.id
# 期望: 数字 user id
```

### TC-VAL-L0-3：访问首页（React）

```bash
curl -b cookies.txt -sf http://localhost:5000/ | grep -q 'react-root'
# 期望: exit 0
```

### TC-VAL-L0-4：触发 screener-v3 estimate

```bash
curl -b cookies.txt -sf -X POST http://localhost:5000/api/screen/v3/estimate \
  -H 'Content-Type: application/json' \
  -H "X-CSRFToken: $(get_csrf)" \
  -d '{"nl_query":"AI","market":"US","candidate_n":20,"gurus":["buffett"],"mode":"agent","with_roundtable":false}' \
  | jq .cost_cny
# 期望: 非零数字
```

### TC-VAL-L0-5：WebSocket 连接

脚本化：`websocat ws://localhost:5000/socket.io/?transport=websocket` → 收到 `connect` 事件。

---

## 2. L1 自动化 E2E 用例（33 条，~30 min）

**目的**：每页基础渲染 + 1 个主流程可达。Playwright。

### 2.1 认证（3）

- **TC-VAL-L1-1**：未登录访问 `/` → 302 /login
- **TC-VAL-L1-2**：邮箱密码 login → 跳 `/`
- **TC-VAL-L1-3**：logout → session 失效 + 重定向

### 2.2 React 岛屿渲染（每页 1 条，12 条）

- **TC-VAL-L1-4** … **TC-VAL-L1-15**：以下每页访问 → root 内有预期标题 + 关键控件出现（Playwright locator）
  - `/`（Dashboard）
  - `/screener-v3`
  - `/tasks`
  - `/paper-trade/NVDA`（前提：NVDA session 已存在）
  - `/portfolio`
  - `/history`
  - `/alerts`
  - `/reports`
  - `/backtest`
  - `/analysis`
  - `/analysis/<id>`
  - `/settings`

### 2.3 Jinja 保留页（3）

- **TC-VAL-L1-16** **～TC-VAL-L1-18**：`/login` / `/register` / `/reset` 旧页面渲染无错

### 2.4 基础 CRUD 抽样（15）

每页抽 1 条：

- Portfolio 买入 NVDA 1 股 → 列表增加一行
- History 点击记录 → 跳详情
- Alerts 新增规则 → 列表显示
- Alerts 删除规则 → 列表减少
- Reports 触发生成 → 跳 tasks
- Backtest 新建提交 → 跳 tasks
- Paper list 新建 session → grid 增加一卡
- Analysis 触发 → 跳 tasks
- Settings 修改 display_name → 持久化
- Screener-v3 选 4 大师 → estimate 有数字
- Tasks 列表渲染 ≥ 1 行（用已完成的）
- Tasks 详情 ProgressStream 订阅连接成功
- ⌘K 打开 Command 面板
- Dashboard 指标卡数字非 0
- Dashboard 运行中任务列表响应 SocketIO

---

## 3. L2 功能回归矩阵（74 条，~2h）

完整矩阵放在 `validation/runs/<date>/l2_matrix.xlsx`（Excel）。这里列骨架。

### 3.1 Dashboard（6）

| # | 功能 | 验收 |
|---|---|---|
| TC-VAL-L2-1 | 总值数字正确 | = SUM(market_value) + cash |
| TC-VAL-L2-2 | 今日 PnL 正负色 | 正 green / 负 red |
| TC-VAL-L2-3 | 胜率数字 | ≤ 100% |
| TC-VAL-L2-4 | AI 洞察按分数降序 | 手工检查 |
| TC-VAL-L2-5 | 运行中任务实时更新 | 触发新任务 → 列表立即有 |
| TC-VAL-L2-6 | 持仓概览 top 3 | 按市值降序 |

### 3.2 Analysis（10）

- TC-VAL-L2-7 ～ L2-16 覆盖：触发、8 tab 切换、executive_summary 高亮、Markdown 渲染、辩论区展示、Bookmark、再次分析、导出 PDF、移动端 tabs-scrollable、错误态（无效 ticker）

### 3.3 History（5）

- Bookmark 切换 + 持久化
- 筛选 my/all
- 搜索 ticker + 关键词
- 无限滚动 loadmore
- 空态显示

### 3.4 Screener V3（8）

- 14 大师勾选
- 预估实时更新
- 深度模式切换
- 候选数切换
- classic 模式秒出
- Agent 模式跳 tasks
- Round-table 跑通
- 经典模式后端结果与旧 v2 一致

### 3.5 Tasks（6）

- 我的 / 全部 tab
- 任务详情进度条
- 断线重连 catch-up
- 取消任务
- 任务完成 toast
- 再次触发

### 3.6 Paper-trade（8）

- 会话列表
- 详情页四个板块（策略/持仓/档位/AI 决策）
- tier dedup（F1）
- executive_summary（F3）
- AI 决策 Markdown（F2）
- 双 grid 图表 + drawdown 阴影（F4）
- 记录 tab 按 Plan/Event 切换（F5）
- 移动端档位布局（v1.3 fix）

### 3.7 Portfolio（6）

- stat 4 卡
- DataTable 排序/搜索
- 买入 Dialog 提交
- 卖出 Dialog 提交
- 行末操作菜单
- 净值曲线

### 3.8 Alerts（5）

- 规则 / 历史 Tab
- 新增规则 Dialog
- 启用 Switch
- 触发历史展示
- 删除确认

### 3.9 Reports（4）

- 生成表单
- 跳 tasks
- 下载 PDF/MD/HTML
- 过期标记

### 3.10 Backtest（6）

- 新建/历史 Tab
- 实时预估
- 结果详情页 ECharts
- 交易明细 DataTable
- 再次运行
- 参数 JSON Accordion

### 3.11 Settings（6）

- SettingsTabs 导航
- 修改密码
- LLM provider 切换
- 邀请码管理（admin）
- 用户管理（admin）
- 系统诊断

### 3.12 Auth（4）

- Login 成功跳 `/`（尊重 next 参数）
- Register 邀请码实时校验
- Register 密码一致校验
- Reset 失败 token 显示错误 card

---

## 4. 跨模块集成脚本（20 条，~4h）

每条对应 [design §6.1](../design/ui-migration-validation.md#61-关键集成场景) 的场景，脚本化执行。

### TC-VAL-L3-1：双用户双 provider 并发

```python
# pytest -k test_dual_user_provider
@pytest.mark.integration
def test_dual_user_provider(alice_session, bob_session):
    # alice 设 qwen, bob 设 gemini
    alice_session.post("/api/settings/llm-provider", json={"provider": "qwen"})
    bob_session.post("/api/settings/llm-provider", json={"provider": "gemini"})

    # 同时触发两个 screener-v3
    r1 = alice_session.post("/api/screen/v3/trigger", json={...})
    r2 = bob_session.post("/api/screen/v3/trigger", json={...})
    task_a, task_b = r1.json()["task_id"], r2.json()["task_id"]

    # 等任务都完成
    wait_for_tasks([task_a, task_b], timeout=600)

    # 验证 provider 隔离
    assert get_task_events(task_a, filter="provider") == "qwen"
    assert get_task_events(task_b, filter="provider") == "gemini"

    # 验证事件不互相泄露（alice 的 socket 未收到 bob 的事件）
    assert "bob" not in alice_session.received_task_ids
```

### TC-VAL-L3-2：登出后重连 catch-up

```python
def test_logout_catchup(alice_session):
    # alice 触发一个需要 3 分钟的任务
    task_id = alice_session.post("/api/analyze", json={"ticker": "NVDA"}).json()["task_id"]

    # alice 登出
    alice_session.logout()
    time.sleep(60)  # 模拟 1 分钟离线

    # 重新登录（相同 email/pass）
    alice_session.login()

    # 访问 /tasks/<id>
    events = alice_session.get(f"/api/tasks/events?task_id={task_id}&since=0").json()

    # 至少 60s 的事件都在
    assert len(events) >= 1
    assert events[-1]["event"] == "task_progress"  # 还在跑
```

### TC-VAL-L3-3：paper-trade plan dedup

```python
def test_plan_dedup(alice_session):
    # 触发两次 identical analysis
    a1 = trigger_analysis_and_wait(alice_session, "NVDA", "2026-04-22")
    a2 = trigger_analysis_and_wait(alice_session, "NVDA", "2026-04-22")  # 参数完全一致

    # 获取 paper_trade 状态
    r = alice_session.get("/api/paper/tickers/NVDA").json()
    active = r["active_plan"]

    # 第二次应该是 reconfirmed_count=2，不是新 plan
    assert active["reconfirmed_count"] == 2
    assert active["analysis_ids"] == [a1, a2]
```

### TC-VAL-L3-4：邀请码注册 + 权限边界

```python
def test_invite_register_boundary(admin_session):
    # admin 生成邀请码
    code = admin_session.post("/api/admin/invites", json={"expires_in_days": 1}).json()["code"]

    # 新用户注册
    new_sess = register_with_code(code, "newuser@example.com", "Password1!")

    # 新用户看到共享 analysis_history 但空 portfolio
    assert len(new_sess.get("/api/analysis/history").json()["items"]) > 0
    assert new_sess.get("/api/portfolio/holdings").json()["items"] == []
```

### TC-VAL-L3-5：用户级 provider 覆盖

```python
def test_user_llm_provider_override(alice_session):
    alice_session.post("/api/settings/llm-provider", json={"provider": "gemini"})

    # 触发分析 → 查日志 provider
    task_id = alice_session.post("/api/analyze", json={"ticker": "AAPL"}).json()["task_id"]
    wait_task(task_id)

    events = get_task_events(task_id)
    provider_events = [e for e in events if "provider" in e["payload"]]
    assert all(e["payload"]["provider"] == "gemini" for e in provider_events)
```

### TC-VAL-L3-6 ～ TC-VAL-L3-20

场景对应 [design §6.1](../design/ui-migration-validation.md#61-关键集成场景) 的 #6-#20，每条写一个 pytest 用例。

---

## 5. L4 数据完整性（14 条，~1h）

### TC-VAL-L4-1：row count 不变

```sql
-- 所有迁移前已存在的表
SELECT 'positions',             COUNT(*) FROM positions UNION ALL
SELECT 'transactions',          COUNT(*) FROM transactions UNION ALL
SELECT 'daily_snapshots',       COUNT(*) FROM daily_snapshots UNION ALL
SELECT 'alerts',                COUNT(*) FROM alerts UNION ALL
SELECT 'alert_history',         COUNT(*) FROM alert_history UNION ALL
SELECT 'analysis_history',      COUNT(*) FROM analysis_history UNION ALL
SELECT 'agent_scorecards',      COUNT(*) FROM agent_scorecards UNION ALL
SELECT 'prompt_versions',       COUNT(*) FROM prompt_versions UNION ALL
SELECT 'tasks',                 COUNT(*) FROM tasks UNION ALL
SELECT 'paper_trade_sessions',  COUNT(*) FROM paper_trade_sessions UNION ALL
SELECT 'paper_trade_strategy_events', COUNT(*) FROM paper_trade_strategy_events UNION ALL
SELECT 'paper_trade_trades',    COUNT(*) FROM paper_trade_trades UNION ALL
SELECT 'paper_trade_equity',    COUNT(*) FROM paper_trade_equity UNION ALL
SELECT 'paper_trade_daily_stats', COUNT(*) FROM paper_trade_daily_stats;
```

对比 `snapshot-pre.json`：每行必须一致。

### TC-VAL-L4-2：positions 抽样字段一致

随机 10 行（固定 seed），`ticker / shares / avg_cost / added_date` 前后完全相等。

### TC-VAL-L4-3：transactions 抽样

同上，`ticker / action / shares / price / timestamp`。

### TC-VAL-L4-4：analysis_history 抽样

`ticker / date / signal / trade_decision` 字段一致（非空）。注：`executive_summary` 可能未回填，允许 NULL。

### TC-VAL-L4-5 ～ L4-8：其他 4 类私有表抽样

### TC-VAL-L4-9：所有不变量通过

```bash
python -m stock_trading_system.validation.invariants
# 期望：14 条全部 OK
```

### TC-VAL-L4-10：user_id 覆盖率

```sql
SELECT COUNT(*) FROM positions WHERE user_id IS NULL;                  -- 0
SELECT COUNT(*) FROM transactions WHERE user_id IS NULL;               -- 0
SELECT COUNT(*) FROM alerts WHERE user_id IS NULL;                     -- 0
SELECT COUNT(*) FROM paper_trade_sessions WHERE user_id IS NULL;       -- 0
SELECT COUNT(*) FROM daily_snapshots WHERE user_id IS NULL;            -- 0
```

### TC-VAL-L4-11：tasks.created_by 升级

```sql
-- 升级前是 TEXT (='user')，升级后是 INTEGER FK
SELECT COUNT(*) FROM tasks WHERE typeof(created_by) != 'integer';     -- 0
-- 所有老 'user' 已映射到 admin
SELECT COUNT(*) FROM tasks t
 LEFT JOIN users u ON t.created_by = u.id
 WHERE u.id IS NULL;                                                    -- 0
```

### TC-VAL-L4-12：paper_trade_plans fingerprint

```sql
SELECT COUNT(*) FROM paper_trade_plans WHERE fingerprint IS NULL;     -- 0
SELECT COUNT(*) FROM paper_trade_plans WHERE reconfirmed_count < 1;   -- 0
```

### TC-VAL-L4-13：task_events 索引生效

```sql
EXPLAIN QUERY PLAN
SELECT * FROM task_events WHERE user_id = 1 AND seq > 0 ORDER BY seq;
-- 期望 output 包含 "USING INDEX ix_task_events_user_seq"
```

### TC-VAL-L4-14：备份可恢复

```bash
# 用备份恢复到临时 DB，跑一轮 smoke
cp portfolio.db.pre-migration-*.bak /tmp/restore-test.db
DB_PATH=/tmp/restore-test.db python -m stock_trading_system.validation.smoke
# 期望 exit 0
```

---

## 6. L5 对抗性 / 安全（18 条，~2h）

### 6.1 越权（8）

每条构造"alice 尝试访问 bob 的资源"，期望 403/404。

- TC-VAL-L5-1：`GET /api/portfolio/holdings` alice 看不到 bob 的仓位（response 仅 alice 的）
- TC-VAL-L5-2：`GET /api/alerts` 同上
- TC-VAL-L5-3：`GET /api/paper/sessions` 同上
- TC-VAL-L5-4：`GET /api/paper/sessions/<bob_session_id>/trades` 直接猜 id → 404
- TC-VAL-L5-5：`DELETE /api/portfolio/<bob_ticker>` → 404
- TC-VAL-L5-6：`DELETE /api/alerts/<bob_alert_id>` → 403 或 404
- TC-VAL-L5-7：`POST /api/tasks/<bob_task_id>/cancel` → 403
- TC-VAL-L5-8：SocketIO room：alice 的 socket 收不到 bob 的 task_events

### 6.2 CSRF（3）

- TC-VAL-L5-9：POST 无 `X-CSRFToken` → 403
- TC-VAL-L5-10：POST 伪造 token → 403
- TC-VAL-L5-11：GET 无 CSRF → 正常（豁免）

### 6.3 Session（4）

- TC-VAL-L5-12：document.cookie 读不到 session（HttpOnly 生效）
- TC-VAL-L5-13：跨域（Origin 不同）POST 被 SameSite 阻断
- TC-VAL-L5-14：logout 后老 cookie 所有 API 都 401
- TC-VAL-L5-15：升级 `SESSION_VERSION_KEY` 后老 session 失效

### 6.4 并发（3）

- TC-VAL-L5-16：10 个用户同时登录 + 并发触发 analyze → 无 cross-task 污染
- TC-VAL-L5-17：对同一 active plan 2 线程并发 save_plan（fingerprint 一致）→ 仅 1 次 insert + reconfirmed=2（并发安全）
- TC-VAL-L5-18：同一 task 10 个线程同时 emit_event → seq 全递增无重复

---

## 7. 执行脚本

### 7.1 一键跑所有层

```bash
python -m stock_trading_system.validation.run_all \
  --level full \
  --output validation/runs/$(date +%Y%m%d)/
```

### 7.2 CI 常驻跑 L0+L1

```yaml
# .github/workflows/validation.yml
name: Validation Smoke + Basic
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - uses: actions/setup-node@v4
      - run: pip install -e . && npm ci --prefix stock_trading_system/web/frontend
      - run: npm run build --prefix stock_trading_system/web/frontend
      - run: python -m stock_trading_system.validation.run_all --level smoke+basic
```

### 7.3 签字凭证生成

```bash
python -m stock_trading_system.validation.sign_off \
  --report validation/runs/20260424/report.json \
  --signer admin@local \
  --note "生产上线前验证全绿，允许部署"
```

## 8. 覆盖要求

| 脚本 / 模块 | 要求 |
|---|---|
| `validation/snapshot.py` | 100% 行覆盖（单测） |
| `validation/compare.py` | 100% |
| `validation/invariants.py` | 100%（14 条 SQL 各有单测） |
| `validation/cross_user_access.py` | ≥ 90% |
| `validation/run_all.py` | ≥ 80% |

### 运行命令

```bash
# 单元测试
pytest tests/validation/ --cov=stock_trading_system/validation

# L3 集成
pytest tests/validation/test_l3_scenarios.py -v

# L5 越权
pytest tests/validation/test_cross_user.py -v

# Playwright E2E（L1 + L2 自动化部分）
npx playwright test tests/e2e/validation/
```

## 9. 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-24 | 164 | 初版：L0 冒烟 5 + L1 基础 33 + L2 功能 74 + L3 跨模块 20 + L4 数据 14 + L5 对抗性 18 |
