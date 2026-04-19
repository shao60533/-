# 测试用例：多租户（Multi-tenant）

| 项 | 值 |
|---|---|
| Feature | `multi-tenant` |
| 版本 | v1.0 |
| 日期 | 2026-04-19 |
| 关联 PRD | [../prd/multi-tenant.md](../prd/multi-tenant.md) |
| 关联设计 | [../design/multi-tenant.md](../design/multi-tenant.md) |

## 汇总

| 分类 | 用例数 |
|---|---|
| 单元：auth 基础 | 14 |
| 单元：邀请码 | 8 |
| 单元：repository 层 | 10 |
| 集成：迁移脚本 | 9 |
| 集成：权限隔离 | 18 |
| 集成：共享数据可见性 | 6 |
| 集成：任务中心 | 7 |
| 集成：model-switch 用户级 | 6 |
| API：auth 端点 | 14 |
| API：admin 端点 | 6 |
| 前端：登录/注册/Nav/Task | 10 |
| 安全：Session / CSRF / 越权 | 10 |
| 回归（单用户模式兼容） | 5 |
| 性能 | 4 |
| 真机/多浏览器 | 3 |
| **总计** | **130** |

---

## 1. 单元：auth 基础（14）

### 1.1 密码（4）

**TC-MT-U1**：`hash_password` 产生不同的 salt（两次 hash 不等）

```python
def test_hash_different_salts():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2
```

**TC-MT-U2**：`verify_password` 正确匹配

**TC-MT-U3**：`verify_password` 错密码返回 False

**TC-MT-U4**：bcrypt rounds ≥ 12（检查 hash 前缀 `$2b$12$` 或更高）

### 1.2 Session（6）

**TC-MT-U5**：`login_user` 写入 SESSION_KEY + SESSION_VERSION_KEY

**TC-MT-U6**：`logout_user` 清空所有 session 键

**TC-MT-U7**：`load_current_user` 在 SESSION_VERSION 不匹配时 g.user = None

**TC-MT-U8**：`load_current_user` 在用户被软删除时 g.user = None

**TC-MT-U9**：`load_current_user` 正常登录态填充 g.user

**TC-MT-U10**：session cookie 属性：HttpOnly / SameSite=Lax / Secure(prod)

### 1.3 Decorators（4）

**TC-MT-U11**：`@login_required` 未登录返回 401（API） / redirect（页面）

**TC-MT-U12**：`@login_required` 已登录正常放行

**TC-MT-U13**：`@admin_required` 普通用户返回 403

**TC-MT-U14**：`@admin_required` admin 正常放行

---

## 2. 单元：邀请码（8）

### TC-MT-U15：`create_invite` 生成的 code 长度 12 字符

### TC-MT-U16：`create_invite` 生成的 code 在两次调用间不重复

### TC-MT-U17：`redeem_invite` 成功后 used_by / used_at 被设置

### TC-MT-U18：`redeem_invite` 二次兑换同一码返回 `invite_used`

### TC-MT-U19：`redeem_invite` 过期码返回 `invite_expired`

### TC-MT-U20：`revoke_invite` 后兑换返回 `invite_revoked`

### TC-MT-U21：`list_invites` 仅 admin 可调用（非 admin 抛 PermissionError）

### TC-MT-U22：并发兑换同一码（2 线程），只有 1 个成功（用 UNIQUE 或事务锁）

---

## 3. 单元：repository 层（10）

### TC-MT-U23：`UserRepository.find_by_email` 大小写归一化匹配

### TC-MT-U24：`UserRepository.create` 同邮箱第二次抛 `email_taken`

### TC-MT-U25：软删除后 `find_by_email(email)` 返回 None

### TC-MT-U26：软删除后同邮箱可重新注册

### TC-MT-U27：`PositionsRepo.list(user_id=A)` 不返回 user_id=B 的行

### TC-MT-U28：`AlertsRepo.list(user_id=A)` 不返回 user_id=B 的行

### TC-MT-U29：`PaperSessionsRepo.list(user_id=A)` JOIN 子表仅看自己

### TC-MT-U30：`AnalysisRepo.list()` 无 user_id 参数，返回所有（共享）

### TC-MT-U31：`TasksRepo.list(scope="my", user_id=A)` 仅返回自己

### TC-MT-U32：`TasksRepo.list(scope="all")` 返回所有用户任务

---

## 4. 集成：迁移脚本（9）

### TC-MT-I1：空 DB 运行迁移 → 仅建 users/invite_codes/user_settings 三表 + 建 admin

### TC-MT-I2：非空 DB（带老数据）运行 → admin 继承所有 positions/alerts/paper sessions

### TC-MT-I3：`--dry-run` 不修改 DB，只打印 SQL

### TC-MT-I4：迁移脚本幂等（第二次运行无操作，退出码 0）

### TC-MT-I5：迁移前自动生成 `.pre-mt.bak` 备份

### TC-MT-I6：迁移过程模拟中断（kill -9）→ DB 未部分修改（事务）

### TC-MT-I7：迁移后 `SELECT COUNT(*) FROM positions WHERE user_id IS NULL` == 0

### TC-MT-I8：`tasks.created_by_legacy` = 'user' 全部被映射为 admin.id

### TC-MT-I9：迁移后启动 Flask 可登录 admin 账号，看到老持仓

---

## 5. 集成：权限隔离（18）

两用户 fixture：`alice` 和 `bob`，均为普通用户。每个资源一对"自己可读"+"他人不可读"测试。

### 持仓（3）

**TC-MT-I10**：alice 添加 AAPL 持仓 → GET /api/portfolio 返回 AAPL

**TC-MT-I11**：bob 登录后 GET /api/portfolio → 不含 AAPL

**TC-MT-I12**：bob 构造 `DELETE /api/portfolio/AAPL`（假设 ID 猜中）→ 404（或 403）

### 预警（3）

**TC-MT-I13**：alice 创建 AAPL 预警规则

**TC-MT-I14**：bob 看不到 alice 的预警

**TC-MT-I15**：alerts.alert_history 也按 user_id 隔离（JOIN alerts）

### 纸面交易（3）

**TC-MT-I16**：alice 创建 paper session

**TC-MT-I17**：bob 看不到 alice 的 sessions / trades / equity

**TC-MT-I18**：bob 直接访问 `/api/paper/sessions/<alice_session_id>/trades` → 404

### 持仓快照（2）

**TC-MT-I19**：alice 的 daily_snapshots 仅 alice 可读

**TC-MT-I20**：快照生成任务 created_by 正确

### 跨表级（3）

**TC-MT-I21**：用 SQL 直查 `SELECT user_id, COUNT(*) FROM positions GROUP BY user_id` → 每 user 独立聚合

### 只读 admin（4）

**TC-MT-I22**：admin `GET /api/portfolio?user_id=<alice_id>` → 返回 alice 数据（审计用）

**TC-MT-I23**：admin `POST /api/portfolio`（不带 user_id）→ 写到 admin 自己

**TC-MT-I24**：admin 无法通过 API 给 bob 写入持仓（需 bob 主动操作）

**TC-MT-I25**：admin `/api/admin/users/<id>/positions` 只读端点返回

---

## 6. 集成：共享数据可见性（6）

### TC-MT-I26：alice 触发 AAPL 分析 → bob 在分析记录页看到该行

### TC-MT-I27：bob 点开分析详情 → 看到全部 6 份报告

### TC-MT-I28：详情页 audit 区显示 "由 alice@... 在 ... 触发"

### TC-MT-I29：bob 给 alice 的分析加 bookmark → `analysis_bookmarks` 表新行

### TC-MT-I30：bob 的 bookmark 对 alice 不可见（私人笔记）

### TC-MT-I31：选股结果共享可见；backtest 结果共享可见；agent_scorecards 共享可见

---

## 7. 集成：任务中心（7）

### TC-MT-I32：默认 tab="my" → 只显示 alice 触发的任务

### TC-MT-I33：切换 tab="all" → 显示 alice + bob + admin 的任务

### TC-MT-I34：alice 尝试取消 bob 的任务 → 403

### TC-MT-I35：admin 可取消任何人的任务

### TC-MT-I36：任务完成后，alice 登出再登录 → "my" tab 仍可见该任务 + 结果

### TC-MT-I37：任务 params_json snapshot 了 user_id，worker 执行时 provider 用 alice 的选择

### TC-MT-I38：任务列表分页（每页 50）工作正确

---

## 8. 集成：model-switch 用户级（6）

### TC-MT-I39：alice 设 provider=qwen, bob 设 provider=gemini → 各自触发分析使用各自 provider

### TC-MT-I40：`user_settings.llm_provider` 为 NULL → 回落全局 yaml

### TC-MT-I41：env `LLM_PROVIDER=qwen` 锁定 → alice 设置 gemini 不生效（env 优先）

### TC-MT-I42：GET /api/settings/llm-provider 返回 `scope: "user"` 当用户设置存在

### TC-MT-I43：GET 返回 `scope: "global_yaml"` 当用户 NULL 但 yaml 有

### TC-MT-I44：GET 返回 `scope: "legacy"` 当所有层都 NULL

---

## 9. API：auth 端点（14）

### 注册（4）

**TC-MT-A1**：合法邀请码 + 新邮箱 + 合规密码 → 200 + 自动登录

**TC-MT-A2**：非法邀请码 → 400 `invite_invalid`

**TC-MT-A3**：已用邀请码 → 400 `invite_used`

**TC-MT-A4**：弱密码（<8 字符）→ 400 `password_weak`

### 登录（4）

**TC-MT-A5**：正确凭证 → 200 + Set-Cookie

**TC-MT-A6**：错密码 → 401 `invalid_credentials`

**TC-MT-A7**：不存在邮箱 → 401 `invalid_credentials`（与错密码同文案，防枚举）

**TC-MT-A8**：软删除用户 → 401

### 登出 / 改密（3）

**TC-MT-A9**：登出后 session cookie 失效

**TC-MT-A10**：改密旧密码错 → 401

**TC-MT-A11**：改密成功后旧 session 仍有效（本次不需 re-login）

### 重置 token（3）

**TC-MT-A12**：admin 生成 token 后用户凭 token 可设新密码

**TC-MT-A13**：同一 token 用两次第二次 400 `reset_invalid`

**TC-MT-A14**：过期 token → 400 `reset_invalid`

---

## 10. API：admin 端点（6）

### TC-MT-A15：非 admin 请 /api/admin/* → 403

### TC-MT-A16：admin 生成邀请码 → 返回 code，列表可见

### TC-MT-A17：admin 吊销邀请码 → 兑换时 400 `invite_revoked`

### TC-MT-A18：admin 列出所有用户（包括软删除）

### TC-MT-A19：admin 软删除用户 → 用户登录 401

### TC-MT-A20：admin 生成重置 token → 返回可用链接

---

## 11. 前端：登录/注册/Nav/Task（10）

Playwright E2E。

### TC-MT-E1：未登录访问 `/` → 重定向 /login

### TC-MT-E2：登录页输入正确 → 重定向 /（dashboard）

### TC-MT-E3：注册页邀请码无效 → 页面内错误提示

### TC-MT-E4：注册成功自动登录并重定向 /

### TC-MT-E5：Nav 显示当前用户邮箱 + 头像首字母

### TC-MT-E6：Nav 下拉菜单 "登出" 清 session 回 login

### TC-MT-E7：admin 用户 Nav 下拉多一项"邀请码管理"

### TC-MT-E8：任务中心 tab 切换（my / all）API 参数正确

### TC-MT-E9：分析详情页顶部显示 audit 信息条

### TC-MT-E10：移动端（375px）登录/注册页布局无横滑，控件 ≥44 高

---

## 12. 安全（10）

### TC-MT-S1：CSRF：POST /api/portfolio 缺 CSRF header → 403

### TC-MT-S2：CSRF：带伪造 token → 403

### TC-MT-S3：Session cookie HttpOnly（JS 无法读 document.cookie）

### TC-MT-S4：Session cookie SameSite=Lax（跨域 POST 不带）

### TC-MT-S5：密码不出现在日志（grep 测试日志输出）

### TC-MT-S6：重置 token 不出现在日志

### TC-MT-S7：SQL 注入：邮箱字段含单引号 → 参数化查询处理正常

### TC-MT-S8：XSS：display_name 含 `<script>` → 前端转义显示

### TC-MT-S9：IDOR：alice 猜 bob 的 position_id → 404

### TC-MT-S10：SECRET_KEY 未设启动拒绝启动（或安全自动生成）

---

## 13. 回归（兼容单用户模式，5）

### TC-MT-R1：迁移前已存在的 positions 数据量、金额、ticker 列表与迁移后完全一致

### TC-MT-R2：已存在的 analysis_history 全部可查，内容不变

### TC-MT-R3：已有 paper_trade_sessions 追踪不断链

### TC-MT-R4：已配置的全局 `~/.stock_trading/config.yaml` llm_provider 在用户未设置时仍生效

### TC-MT-R5：现有 Python + Node 自动化测试在多租户模式下全部绿

---

## 14. 性能（4）

### TC-MT-P1：登录端到端 ≤ 500ms（含 bcrypt）

### TC-MT-P2：私有表 `WHERE user_id` 查询走索引（EXPLAIN 不 full scan）

### TC-MT-P3：任务中心 "全部" tab 1000 任务分页响应 ≤ 200ms

### TC-MT-P4：bcrypt cost=12 单次 hash 时间 < 400ms（Railway 环境）

---

## 15. 真机/多浏览器（3）

### TC-MT-M1：Chrome + Safari + Firefox 各跑登录/登出/注册/改密流程

### TC-MT-M2：iOS Safari 15+ cookie 持久化（关闭 Safari 再开仍登录）

### TC-MT-M3：隐私模式下登录成功且功能可用

---

## 覆盖要求

| 模块 | 目标 |
|---|---|
| `stock_trading_system/auth/` | 行覆盖 ≥ 95% |
| `stock_trading_system/migrations/to_multi_tenant.py` | 行覆盖 ≥ 90% |
| 路由改造（web/app.py diff 行） | ≥ 90% |
| 前端 login/register JS | ≥ 80% |

### 运行命令

```bash
# 单元 + 集成
pytest tests/auth/ tests/migrations/ tests/integration/test_multi_tenant_*.py \
       --cov=stock_trading_system/auth \
       --cov=stock_trading_system/migrations \
       --cov-report=term-missing

# 前端 E2E
npx playwright test tests/frontend/test_multi_tenant_*.spec.js

# 安全扫描
bandit -r stock_trading_system/auth/
```

## 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-19 | 130 | 初版：单元 32 + 集成 55 + API 20 + 前端 10 + 安全 10 + 回归 5 + 性能 4 + 真机 3 + 共享可见性 6 |
