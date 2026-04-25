# PRD: 多租户（Multi-tenant）

| 项 | 值 |
|---|---|
| Feature | `multi-tenant` |
| 版本 | v1.0 |
| 日期 | 2026-04-19 |
| 关联技术方案 | [../design/multi-tenant.md](../design/multi-tenant.md) |
| 关联测试用例 | [../test-cases/multi-tenant.md](../test-cases/multi-tenant.md) |

## 1. 背景

### 1.1 现状

系统当前是**零 auth 单用户**形态：

- `portfolio.db` 里所有表无 `user_id` 列
- 没有 `users` 表、没有 Flask session、没有 login 路由
- 任何访问到 Web UI 的人都能看/改全部数据
- 最近加入的 [model-switch](../design/model-switch.md) 把 `llm_provider` 写在全局 `~/.stock_trading/config.yaml`，没有用户维度

### 1.2 问题

用户想把系统开放给几个朋友/家人一起用，且希望：

1. **持仓和预警是私人的**（别人看不到我买了什么、触发了什么预警）
2. **AI 分析、选股、报告、回测共享**（谁花了 token 跑的分析，所有人都能看）
3. **退出登录再回来，异步任务结果还能查看**（任务结果持久化，不依赖会话）

### 1.3 范围定位

**私人小圈（≤20 人，朋友家人）**：
- 邮箱 + 密码登录
- 不做邮件验证、不做 OAuth、不做计费
- 管理员发邀请码开户

## 2. 目标

让系统支持**多用户并存**，同时保持"分析/选股/报告共享"的协作价值。

### 2.1 成功指标

| 指标 | 目标 |
|---|---|
| 用户隔离 | 用户 A 无法通过任何 API / UI 路径看到用户 B 的持仓、预警、纸面交易 |
| 共享可见性 | 任一登录用户可以看到全部 analysis_history / screen_results / backtest_results |
| 旧数据零丢失 | 首次启动多租户版本后，老数据 100% 归属到 `admin` 用户，无损 |
| 会话持久化 | 用户登出/换浏览器/换设备后重新登录，能看到自己和别人触发的异步任务历史 |
| 注册门槛 | 新成员 ≤ 2 步完成注册（邀请码 + 设密码） |

## 3. 范围

### 3.1 In Scope（v1.0）

**认证**
- `users` 表：id / email / password_hash / display_name / role / created_at / last_login_at
- 注册：邀请码制（`invite_codes` 表，管理员生成、单次使用、可选过期）
- 登录：邮箱 + 密码，Flask session cookie（HttpOnly / SameSite=Lax / Secure in prod）
- 登出：清 session
- 修改密码：需旧密码
- 忘记密码：管理员在设置页生成一次性重置 token，邮件/复制链接给用户（不自动发邮件）

**授权**
- 全部 `/api/*`（除 login/register/health）必须认证
- 全部页面路由（除 /login, /register）必须认证
- 私有数据 API 强制 `WHERE user_id = current_user.id`
- 共享数据 API 无 user 过滤（所有登录用户可读）

**数据分区**

| 表 | 分类 | 迁移动作 |
|---|---|---|
| positions, transactions, daily_snapshots | 私有 | 加 `user_id` FK |
| alerts, alert_history | 私有 | 加 `user_id` FK |
| paper_trade_sessions（+5 个子表） | 私有 | sessions 加 `user_id`，子表通过 session_id 联动 |
| analysis_history | 共享 | 不动；新建 `analysis_bookmarks(user_id, analysis_id)` |
| screen_results_v2, backtest_results | 共享（含触发者审计） | `created_by` 从字符串升级为 user_id FK |
| agent_scorecards, prompt_versions | 共享 | 不动 |
| tasks | 审计 | `created_by` 升级为 user_id FK；可见性按 §3.1 任务中心规则 |
| kv_cache | 共享 | 不动（市场数据全局缓存） |

**用户级设置**
- 新建 `user_settings(user_id, llm_provider, ...)` 表
- `llm_provider` 解析优先级升级为：`env > user_settings > global yaml > legacy 自动探测`
- 每用户独立选择 Qwen / Gemini

**老数据迁移**
- 首次启动多租户版本时，自动检测 `users` 表为空：
  1. 创建 `admin` 用户（邮箱由启动脚本或 env 指定，默认 `admin@local`）
  2. 给 `admin` 设一次性初始密码（写入日志 + stdout，要求首次登录改密）
  3. 把全部现有私有表的行批量 `UPDATE SET user_id = admin.id`
  4. `created_by` 字符串为 'user' 的 tasks 全部归 admin

**任务中心可见性**
- 默认"我的任务"tab：只看 `created_by = current_user.id` 的任务
- "全部任务"tab：所有用户的任务（包括他人的，脱敏 params 的敏感字段如 ticker，保留任务类型+时间）
- 结果可见性：共享结果所有人都能读；私有任务结果（如 portfolio 快照生成）仅触发者可读

**UI**
- `/login` 页：邮箱 + 密码 + "忘记密码联系管理员"提示
- `/register` 页：邀请码 + 邮箱 + 密码 + 确认密码
- Nav 顶部：当前用户头像/邮箱 + 下拉菜单（设置 / 登出）
- 设置页：改密码、Admin 专属"邀请码管理"tab
- 任务中心：「我的 / 全部」tab 切换
- 分析/选股结果页：展示"由 XX 在 YY 时间触发"（审计信息）+ 收藏按钮

**角色**
- `admin`（唯一）：可生成邀请码、可重置任意用户密码、可停用用户
- `user`（普通）：无管理权限

### 3.2 Out of Scope（v1.0 不做）

| 项 | 原因 | 后续 |
|---|---|---|
| 邮件验证 | 私人小圈邀请制即可信 | v1.1 可选 |
| OAuth / SSO | 规模小，收益低 | v2.0 |
| 配额 / 计费 | 成本由管理员承担 | v2.0 |
| 细粒度角色（只读 / 编辑者 / 所有者） | 规模小，admin/user 足够 | 不计划 |
| 多租户数据隔离（独立 DB schema） | 单 DB row-level 过滤足够 | 不计划 |
| 审计日志（操作全量录像） | 本地部署可用 SQLite + 日志文件代替 | 可选 |
| 共享结果的权限分级（部分公开） | "全部共享"是用户明确要求 | 不计划 |
| 移动端 app / API Token 认证 | 当前只有 Web UI | 未来 |

## 4. 用户故事

### US-MT-1：管理员首次启动

> **作为**管理员，首次启动多租户版本后，
> **希望**我能用自动生成的 admin 账号登录，看到全部历史数据完好，
> **并且**在设置页里能生成邀请码发给朋友。

**验收**：
- 启动日志打印：`Admin user created: admin@local, initial password: <RANDOM>`
- 用该密码可登录
- 登录后 dashboard 显示所有老数据（持仓、历史分析）
- 设置页有"邀请码管理"tab

### US-MT-2：朋友注册

> **作为**拿到邀请码的朋友，
> **希望**在 `/register` 页输入邀请码 + 邮箱 + 密码即可完成注册，
> **登录后**看到空的持仓页、空的预警页，但能看到 admin 之前跑过的所有 AI 分析和选股结果。

**验收**：
- 邀请码有效 → 注册成功 → 自动登录
- 我的持仓页：空列表
- 我的预警页：空列表
- 分析记录页：看到 admin 的全部历史
- 选股记录页：看到全部共享结果

### US-MT-3：数据隔离

> **作为**用户 A，
> **不希望**用户 B 看到我的持仓、我的预警、我的纸面交易。

**验收**：
- 用户 A 添加持仓 `AAPL 100 股`
- 用户 B 登录后查看持仓页 → 不含 `AAPL`
- 任何 API（包括 `/api/positions`、`/api/alerts`、`/api/paper/sessions`）路径下均无法越权访问

### US-MT-4：共享分析

> **作为**用户 B，
> **希望**能消费用户 A 花了 token 跑出的分析结果，
> **不必**自己重新跑一遍。

**验收**：
- 用户 A 对 `TSLA` 触发分析，15 分钟后完成
- 用户 B 在 `分析记录` 页看到这条 `TSLA` 结果
- 用户 B 点开可看全部报告（市场/情绪/新闻/基本面/辩论/风险/交易决策）
- 详情页显示"由 userA@example.com 在 2026-04-19 14:30 触发"

### US-MT-5：任务中心双视角

> **作为**用户，
> **希望**任务中心默认展示我自己触发的任务，
> **但**能切到"全部"tab 看别人最近跑了啥。

**验收**：
- 任务中心顶部有 `我的 | 全部` tab
- "我的"只展示 `created_by = current_user.id`
- "全部"包含所有用户的任务，但其他用户的 `params` 中敏感字段（如特定 ticker）可完整展示（我们认为选股查询不敏感），时间/类型/状态全部可见
- 完成的任务任意用户点开可看共享结果

### US-MT-6：登出持久化

> **作为**用户，
> **希望**我触发的任务在我登出、关掉浏览器、第二天重新登录后依然能查到结果。

**验收**：
- 触发一个 analysis 任务（预计 15 分钟）
- 立刻登出
- 1 小时后在另一台设备重新登录
- 任务中心 `我的` tab 看到该任务状态为 `success` + 可查看结果

### US-MT-7：Model-switch 用户级

> **作为**用户，
> **希望**我选 Qwen 还是 Gemini 只影响我自己触发的分析，
> **不影响**其他用户。

**验收**：
- 用户 A 设置 provider = Qwen
- 用户 B 设置 provider = Gemini
- A 触发的分析日志显示 `Using Qwen`
- B 触发的分析日志显示 `Using Gemini`
- 对方的选择在自己 UI 下拉中不可见

### US-MT-8：忘记密码

> **作为**忘记密码的用户，
> **希望**联系管理员后拿到一个一次性链接重置密码。

**验收**：
- 管理员在设置页 → 用户管理 → 点击某用户 → "生成重置链接"
- 系统生成形如 `https://app/reset?token=<uuid>` 的链接（token 24h 过期）
- 用户点链接 → 设新密码 → token 失效
- 登录页"忘记密码"按钮只显示一句提示：`请联系管理员`（不自助）

## 5. 需求矩阵

### 5.1 P0 —— 必须上线

| 需求 ID | 描述 | 验收 |
|---|---|---|
| R-MT-1 | `users` / `invite_codes` / `user_settings` 三张新表 | Schema |
| R-MT-2 | 密码用 bcrypt 存储，cost ≥ 12 | 单测 |
| R-MT-3 | Flask session cookie 配置 HttpOnly + SameSite + CSRF | 集成测 |
| R-MT-4 | `@login_required` 装饰器覆盖所有私有路由 | 黑盒测 |
| R-MT-5 | 私有表 6 类 + paper 子表 FK 迁移 | 迁移脚本 |
| R-MT-6 | 首次启动自动创建 admin + 老数据归属 | 集成测 |
| R-MT-7 | 任务中心 `我的 / 全部` tab | UI 测 |
| R-MT-8 | `llm_provider` 支持用户级覆盖 | 集成测 |
| R-MT-9 | 登录 / 登出 / 注册 / 改密 四路由 | API 测 |
| R-MT-10 | 邀请码生成 / 兑换 / 吊销 | API 测 |
| R-MT-11 | 分析/选股/回测结果页展示触发者 | UI 测 |
| R-MT-12 | 管理员密码重置（生成 token） | API 测 |

### 5.2 P1 —— 可选

| 需求 ID | 描述 |
|---|---|
| R-MT-13 | 登录失败限流（5 次/分钟） |
| R-MT-14 | 会话超时（30 天滑动过期） |
| R-MT-15 | 用户停用 / 删除（软删除） |
| R-MT-16 | "我的最近活动"时间线 |

### 5.3 P2 —— 未来

| 需求 ID | 描述 |
|---|---|
| R-MT-17 | 邮件验证注册 |
| R-MT-18 | OAuth / Google 登录 |
| R-MT-19 | API Token（给 CLI / 手机用） |
| R-MT-20 | 配额（每日分析次数上限） |

## 6. 权限矩阵

| 资源 | 普通用户看自己 | 普通用户看他人 | Admin 看所有 |
|---|---|---|---|
| positions | ✅ R/W | ❌ | ✅ R, ❌ W |
| transactions | ✅ R/W | ❌ | ✅ R, ❌ W |
| alerts | ✅ R/W | ❌ | ✅ R, ❌ W |
| paper_trade_sessions | ✅ R/W | ❌ | ✅ R, ❌ W |
| analysis_history | ✅ R | ✅ R | ✅ R/W |
| screen_results_v2 | ✅ R | ✅ R | ✅ R/W |
| backtest_results | ✅ R | ✅ R | ✅ R/W |
| tasks（my tab） | ✅ R/cancel | ❌ | ✅ R/cancel |
| tasks（all tab） | ✅ R 元数据 | ✅ R 元数据 | ✅ R/cancel |
| user_settings（llm_provider） | ✅ R/W 自己 | ❌ | ✅ R 所有, W 自己 |
| invite_codes | ❌ | ❌ | ✅ R/W |
| users | ✅ R 自己 | ❌（可见邮箱/display 用于审计展示） | ✅ R/W/停用/改密 |

注：Admin 对他人私有数据也**不可写**（避免误触），需要时可临时用被重置密码登录。

## 7. 非功能需求

### 7.1 安全

- 密码 bcrypt `rounds ≥ 12`
- Session cookie：`HttpOnly=True`, `SameSite=Lax`, `Secure=True`（仅 prod）
- CSRF：所有 POST/PUT/DELETE 需要 CSRF token（Flask-WTF 或自实现）
- 敏感字段不进日志：password、token 全部脱敏
- 邀请码 / 重置 token：UUID v4，不复用

### 7.2 性能

- login 响应 ≤ 500ms（含 bcrypt）
- 任何私有数据 query 的 `WHERE user_id` 必须落索引（全部私有表加复合索引 `(user_id, ...)`）
- 任务中心"全部"tab 分页（每页 50 条）

### 7.3 可观测性

- 登录成功/失败各打 INFO/WARN 日志
- 每次创建用户、生成邀请码、重置密码打 AUDIT 日志到独立文件
- 老数据迁移过程打详细 INFO（每张表 migrated N rows）

### 7.4 兼容性

- 部署时迁移一次性完成：`python -m stock_trading_system.migrations.to_multi_tenant`
- 迁移脚本幂等（多次运行安全）
- 旧环境变量（如 `DASHSCOPE_API_KEY`）继续工作；但用户级 `user_settings.llm_provider` 优先
- 迁移前自动备份 `portfolio.db → portfolio.db.pre-mt.bak`

## 8. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 迁移脚本中途失败导致 DB 半残 | 高 | 迁移前自动备份 + 脚本原子化（每张表单独事务，失败回滚） |
| 忘记给某个 API 加 `@login_required` 导致越权 | 高 | 统一 `before_request` 白名单校验（默认要求登录，只有白名单路由跳过） |
| 老 session 在多租户版本上来后仍可访问 | 低 | cookie key 升级（SECRET_KEY 轮换 = 老 session 自动失效） |
| 跨用户数据泄露（ORM 误用） | 高 | 单元测试覆盖每个私有表的 "用户 A 查不到用户 B 数据" |
| Admin 权限被盗 | 极高 | 初始密码强制首次登录改密 + 支持手动停用 admin 生成新 admin（维护命令）|
| 邀请码外泄被滥注册 | 中 | 码单次使用 + 可设过期 + Admin 可吊销 |
| 用户误删自己账号后数据恢复难 | 中 | 删除 = 软删（user.status=deleted）+ 保留数据 30 天 |

## 9. 与已有模块的关系

| 模块 | 关系 |
|---|---|
| [model-switch](../design/model-switch.md) v1.0 | `llm_provider` 解析顺序升级：env > **user_settings** > global yaml > legacy |
| [mobile-optimization](../design/mobile-optimization.md) v1.0 | 新增的 login/register/settings 三页沿用移动端 tokens + 通用组件 |
| [self-iterating-agents](../design/self-iterating-agents.md) v3.0 | 自我迭代模块全系统级（admin 配置），不分用户；`agent_scorecards` 不加 user_id |
| [paper-trade](../design/paper-trade.md) v1.2 | 全量自动追踪语义不变；但 sessions 加 user_id，各用户独立自己的追踪 |
| [batch-analyze-holdings](../design/batch-analyze-holdings.md) v1.0 | 批量分析基于"我的持仓"，自动变成用户级 |

## 10. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-19 | 初版：邀请码 + 邮箱密码 + 私有/共享/审计三类数据分区 + admin 首启迁移 + 用户级 model-switch |
