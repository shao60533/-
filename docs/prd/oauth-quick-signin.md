# PRD: 第三方快捷登录（Google + GitHub）v1.0

| 项 | 值 |
|---|---|
| Feature | `oauth-quick-signin` |
| 版本 | v1.0 |
| 日期 | 2026-05-09 |
| 关联设计 | [../design/oauth-quick-signin.md](../design/oauth-quick-signin.md) |
| 关联 demo 区块 | [`demo_mobile_full_v1.html`](../../demo_mobile_full_v1.html) `data-view="auth"` |
| 范围 | 用户认证 / 注册 / 账号绑定 |
| 硬约束 | 不破坏邀请码多租户红线、不删除现有邮箱密码登录、不引入 SaaS 锁定 |

---

## 1. 背景

当前系统 ([`auth/repository.py`](../../stock_trading_system/auth/repository.py)) 仅支持邮箱密码登录 + 邀请码注册。对量化用户（多为 GitHub 活跃开发者）和海外用户（习惯 Google 一键登录）增加了首次注册摩擦。

OAuth 快捷登录可显著降低注册门槛同时保持现有多租户邀请码门，[`auth/bootstrap.py`](../../stock_trading_system/auth/bootstrap.py) 与 [Schwab OAuth 现成模式](../../stock_trading_system/web/app.py) (`/oauth/schwab/start` + `/oauth/schwab/callback`) 给本期实装提供了完整复用样板。

## 2. 目标

1. v1.0 接入 **Google** 和 **GitHub** 两个免费 OAuth provider（不需付费 dev account）。
2. 保留邀请码门——所有新用户注册必须经过邀请码，OAuth 不是绕过多租户的后门。
3. 同邮箱已验证的 provider（Google）首次登录自动合并到现有账户；未验证邮箱的 provider（GitHub）需二次确认。
4. 已登录用户可在 `/settings` 管理已绑定的登录方式（绑定 / 解绑），解绑前置检查至少保留一种登录方式。
5. 不删除邮箱密码登录路径，作为 OAuth 不可达时的 fallback。

### 2.1 成功指标

| 指标 | 目标 |
|---|---|
| 接入 provider | 2 个（Google + GitHub），可在不改代码的情况下加第 3 个 |
| 注册时间 | 已有 Google/GitHub 账户的新用户从落地页到登录完成 < 30s（含填邀请码） |
| 多租户隔离 | OAuth 注册创建的 user 与邮箱密码注册 user 在 [v1.18 R-fix-12](../design/analysis-inbox.md) 隔离规则下完全等价 |
| 邀请码绕过 | 0 路径可不通过邀请码完成新用户注册 |
| 账户合并 | 同邮箱（email_verified=true）首次 OAuth 登录自动合并 100% 命中 |
| 后端依赖 | 新增依赖 ≤ 2 个（authlib + 可选 PyJWT） |

## 3. 范围

### 3.1 In Scope

**新增能力**

- Google OAuth 2.0 / OIDC 登录（scope `openid email profile`，邮箱默认已验证）。
- GitHub OAuth 2.0 登录（scope `read:user user:email`，邮箱需通过 `/user/emails` 取 primary）。
- OAuth 账户与现有 user 的 N:1 绑定关系（一个 user 可绑定多个 provider，每个 provider 仅绑定一个 user）。
- 已登录用户在 `/settings` 主动绑定 / 解绑 OAuth provider。

**注册流程**

- 未登录用户在 `/login` 点 OAuth 按钮 → 厂商授权页 → 回调路径分两支：
  - 邮箱已存在 + 已绑定该 provider → 直接登录。
  - 邮箱已存在 + 未绑定该 provider + provider 已验证邮箱（Google） → 自动 link 到现有 user 并登录。
  - 邮箱已存在 + 未绑定该 provider + provider 未验证邮箱（GitHub） → 不自动 link，引导"先用邮箱密码登录后到设置主动绑定"。
  - 邮箱不存在（全新用户） → 重定向到 `/register?provider=<p>&pending=<signed_token>`，预填邮箱（readonly）+ 强制填邀请码 + 显示名 → 提交后才创建 user。

**登录流程**

- 已注册用户在 `/login` 点 OAuth 按钮 → 厂商授权 → 回调直接 login，更新 `last_login_at`。

**已登录用户的账号管理**

- `/settings` 新增"登录方式"section，展示当前已绑定的所有登录方式（邮箱密码 + N 个 OAuth），每行可解绑（如不是最后一种登录方式）。
- 用户可点 `+ 关联 Google` / `+ 关联 GitHub` 主动添加新 provider。

**安全**

- OAuth state 参数（CSRF 防护）+ PKCE（公开客户端代码拦截防护）。
- redirect_uri 服务端二次校验 path 同源。
- email_verified=true 才接受作为账户合并依据。
- session 登录成功后旋转。
- `next` 参数白名单（仅同域相对路径）。
- access_token / refresh_token 加密落库（fernet，密钥放 env）。

### 3.2 Out of Scope

| 不做 | 原因 |
|---|---|
| Apple Sign In | 需 Apple Developer $99/年；v1.0 先跑通免费 provider，v1.1 评估 |
| 微信扫码 | 需企业认证 + 80 元/年；v1.2 评估，目标国内 C 端时再做 |
| Microsoft / QQ / Twitter | 用户覆盖低，v1.0 不做 |
| 跳过邀请码注册 | 多租户红线（[multi-tenant.md](multi-tenant.md)）不允许 |
| 删除邮箱密码登录 | 必须保留作为 OAuth 不可达 fallback |
| 短信 / 手机号登录 | 需短信网关，与 OAuth 正交，单独 PRD |
| 改 users 表 schema | password_hash 仍 NOT NULL，OAuth 用户用占位 hash |
| OAuth token 调用第三方 API | v1.0 仅做认证，access_token 落库留口子但不消费 |

## 4. 需求矩阵

### 4.1 P0 必须完成

| ID | 需求 | 验收 |
|---|---|---|
| R-OAUTH-01 | 新建 `oauth_accounts` 表（idempotent migration） | `pytest tests/auth/test_oauth_repository.py` 全绿 |
| R-OAUTH-02 | `OAuthProvider` Protocol + `GoogleProvider` + `GitHubProvider` 实现 | 单测覆盖 authorize URL 构造 + code exchange + profile 解析 |
| R-OAUTH-03 | `/auth/oauth/<p>/start` 路由（state + PKCE + intent 写 session） | 单测：state 写入 session、authorize URL 含 state + code_challenge |
| R-OAUTH-04 | `/auth/oauth/<p>/callback` 路由 5 路径分支全部覆盖 | 单测：老 OAuth 用户 / 自动合并（Google）/ 二次确认（GitHub）/ 新用户跳注册 / state 不匹配拒绝 |
| R-OAUTH-05 | `/register?provider=<p>&pending=<token>` 完整新用户注册流程 | E2E：新邮箱 + Google 授权 + 邀请码 → 创建 user + 绑定 oauth + redeem invite |
| R-OAUTH-06 | 邀请码门：所有新用户注册路径必检 invite_code | 单测：无邀请码 / 无效邀请码 / 已用邀请码 三态拒绝 |
| R-OAUTH-07 | 同邮箱已验证 provider 自动 link | 单测：Google 回调 + email_verified=true + 邮箱已存在 → 直接登录 + oauth_accounts 新行 |
| R-OAUTH-08 | 同邮箱未验证 provider 二次确认 | 单测：GitHub 回调 + 邮箱已存在但未在该用户的 oauth_accounts → 不自动 link，flash 引导 |
| R-OAUTH-09 | `/api/auth/oauth/linked` GET 返回当前用户已绑定列表 | E2E + 多租户隔离：bob 看不到 alice 的绑定 |
| R-OAUTH-10 | `/api/auth/oauth/<p>/unlink` POST 解绑 | 单测：解绑前置检查至少保留一种登录方式（密码 OR 至少一个其他 OAuth）；最后一种登录方式拒绝解绑 |
| R-OAUTH-11 | `/login` 页加 Google + GitHub 按钮 | 视觉对齐 demo `data-view="auth"` |
| R-OAUTH-11a | OAuth 按钮位置：在邮箱密码 form **下方**（用户 2026-05-11 反馈）| 主登录路径仍是邮箱密码（高频），OAuth 是次选；DOM 顺序：邮箱密码 form → divider `或使用` → OAuth 按钮区 |
| R-OAUTH-11b | 按钮带品牌 logo：Google 多色 G + GitHub 黑色 mark | 资产位于 `/static/icons/google.svg` + `/static/icons/github.svg`，官方品牌合规版本 |
| R-OAUTH-12 | `/register` 页支持 `?provider=<p>&pending=<token>` 预填 | 邮箱字段预填 readonly + 邀请码 + 显示名输入 + 提交按钮 |
| R-OAUTH-13 | `/settings` 加"登录方式"section | 列表 + 解绑按钮 + 关联新 provider 按钮 |
| R-OAUTH-14 | env 配置：4 个 OAuth env | `GOOGLE_OAUTH_CLIENT_ID/SECRET` + `GITHUB_OAUTH_CLIENT_ID/SECRET` |

### 4.2 P1 可并行

| ID | 需求 | 验收 |
|---|---|---|
| R-OAUTH-15 | OAuth token 加密存（fernet） | 单测：DB 内 access_token 列非明文；`OAUTH_ENCRYPT_KEY` env 缺失启动报错 |
| R-OAUTH-16 | 大陆访问探测：Google 不可达时前端隐藏按钮 | 前端 fetch `accounts.google.com/.well-known/openid-configuration` 1.5s timeout |
| R-OAUTH-17 | `/api/auth/providers` 返回启用的 provider 列表给前端 | 前端读此 API 渲染按钮，不硬编码 |
| R-OAUTH-18 | demo `data-view="auth"` 同步加 OAuth 按钮 | 视觉对齐 |

## 5. 用户故事与验收

### US-OAUTH-1：开发者用 GitHub 一键登录

> 作为开发者用户，我希望在落地页直接点 GitHub 登录，避免再注册一遍。

**验收**：
- `/login` 显示 `用 GitHub 登录` 按钮。
- 点击 → GitHub 授权页（含 `read:user user:email` scope）。
- 授权后回调 → 邮箱已存在则登录，邮箱不存在则跳 `/register` 预填。
- 邀请码必填。

### US-OAUTH-2：海外用户用 Google 一键登录

> 作为海外用户，我希望用 Google 一键登录，无需记新密码。

**验收**：
- `/login` 显示 `用 Google 登录` 按钮。
- 点击 → Google 授权页。
- 授权后回调，如果之前用 Gmail 邮箱注册过 → 自动合并并登录（无须二次操作）。
- 大陆用户 Google 不可达时按钮自动隐藏（不让用户点了等超时）。

### US-OAUTH-3：已注册用户绑定 Google 加快下次登录

> 作为已用邮箱密码注册的用户，我希望在设置里绑定 Google 账户，下次直接 Google 登录。

**验收**：
- `/settings` 显示 `+ 关联 Google` 按钮。
- 点击 → Google 授权 → 回调成功后 settings 显示 `✓ Google alice@gmail.com [解绑]`。
- 下次 `/login` 点 Google 直接登录。

### US-OAUTH-4：解绑前必须保留至少一种登录方式

> 作为用户，我希望系统阻止我解绑掉最后一种登录方式（防止把自己锁外面）。

**验收**：
- 用户已绑定密码 + Google + GitHub → 可解绑任意一个。
- 用户只有 Google + GitHub（无密码）→ 解绑 Google 时仍保留 GitHub，可解绑。
- 用户只剩一种登录方式 → 解绑接口返回 400 `last_method` 错误。

### US-OAUTH-5：邀请码门不被绕过

> 作为运维管理员，我希望保证 OAuth 注册仍受邀请码控制，新用户必须有有效邀请码才能进系统。

**验收**：
- 全新邮箱用 Google 登录 → 跳到 `/register?provider=google&pending=<token>`，邮箱预填 readonly。
- 不填邀请码提交 → 400 `invite_code_required`。
- 填错邀请码提交 → 400 `invite_invalid`。
- 填对邀请码提交 → 创建 user + 绑定 oauth + redeem invite + 登录。

## 6. 实装约束

1. 不删除现有邮箱密码登录路径（[`/api/auth/login`](../../stock_trading_system/web/app.py)）。
2. 不修改 `users` 表 schema（OAuth 注册时塞 `bcrypt(secrets.token_urlsafe(32))` 占位 password_hash）。
3. 不绕过邀请码门：所有新 user 创建路径必经 `_invite_mgr.validate()` + `redeem()`。
4. 不引入 SaaS 锁定（Auth0 / Clerk / Supabase Auth 均不引入）。
5. 不删除 [Schwab OAuth 现有路由](../../stock_trading_system/web/app.py)（与本期 OAuth 路由前缀错开 `/oauth/schwab/...` vs `/auth/oauth/...`）。
6. 不改变 `login_required` decorator 行为，OAuth 登录后 `session["user_id"]` 与密码登录路径完全等价。
7. OAuth 仅用于认证，access_token 不主动消费第三方 API。
8. 必须复用 [Schwab OAuth state 机制](../../stock_trading_system/web/app.py:903) 与 [`flask-wtf`](../../requirements.txt) CSRF 配置。
9. 新增依赖严格控制：authlib（必须）+ PyJWT（如 GitHub 不需要可省）+ cryptography（fernet，已通过 schwab-py 间接引入）。
10. demo gap-note 必须同步：v1.0 落地后从 demo 移除"OAuth 待实装"标注。

## 7. 验收清单

### 7.1 功能正确

- 用 Google 注册 + 登录可用。
- 用 GitHub 注册 + 登录可用。
- 同邮箱已验证 provider 自动合并。
- 同邮箱未验证 provider 二次确认。
- 邀请码门 0 绕过路径。
- 解绑保留至少一种登录方式。
- 现有邮箱密码登录与 OAuth 登录完全等价（任意一种登录后 [v1.18 R-fix-12 多租户隔离](../design/analysis-inbox.md) 行为相同）。

### 7.2 安全

- state + PKCE 全启。
- redirect_uri 服务端二次校验。
- session 登录后旋转。
- `next` 仅允许同域相对路径。
- email_verified=true 才作合并依据。
- access_token 加密存。

### 7.3 可观测

- 登录失败有 [`logger.warning`](../../stock_trading_system/utils/__init__.py) 记录原因（state 不匹配 / code exchange 失败 / 邀请码无效 / 二次确认拒绝）。
- 成功登录写 `last_login_at`。
- `/api/diagnostics/providers` 加 OAuth provider 项（client_id 在场 + redirect_uri 配置 + 最近一次成功登录时间）。

## 8. 风险与处理

| 风险 | 影响 | 处理 |
|---|---|---|
| Google 大陆访问失败 | 国内用户登录跳转 timeout | 前端探测自动隐藏；邮箱密码 fallback 始终可用 |
| 邮箱劫持（attacker 抢注后被自动合并） | 账户被盗 | email_verified=true 才合并；GitHub 走二次确认；自动合并时记 audit log |
| Apple/微信未支持 | 部分用户覆盖不到 | 文档明确 v1.1/v1.2 排期；当前邮箱密码可保底 |
| OAuth 厂商接口变更 | 登录失败 | provider 抽象层 + Authlib 屏蔽差异；监控登录成功率 |
| Schema migration 在生产失败 | 老用户登录失败 | migration 用 `CREATE TABLE IF NOT EXISTS` + 不动 users 表，幂等可回滚 |
| 解绑掉最后一种登录方式 | 用户锁死 | 解绑 endpoint 必检 |
| OAuth 回调被中间人拦截 | 账户被盗 | state + PKCE + redirect_uri 三重校验 |

## 9. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-05-09 | 初版：Google + GitHub 双 provider，保留邀请码，自动合并 + 二次确认双策略，~5h 实装 |
