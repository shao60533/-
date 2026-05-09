# OAuth 快捷登录 — 环境变量配置

> 适用于 v1.0 (`docs/prd/oauth-quick-signin.md` + `docs/design/oauth-quick-signin.md`)。
> 涉及 Google + GitHub 两个 provider，token 通过 Fernet 对称加密落库到 `oauth_accounts.access_token_enc`。

## 概览

| 变量 | 必填 | 用途 |
|------|------|------|
| `OAUTH_ENCRYPT_KEY` | 启用任一 provider 必填 | Fernet 密钥，加密 oauth_accounts 表内 token |
| `GOOGLE_OAUTH_CLIENT_ID` | 启用 Google 必填 | Google Cloud Console OAuth 2.0 Client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | 启用 Google 必填 | 同上 secret |
| `GITHUB_OAUTH_CLIENT_ID` | 启用 GitHub 必填 | GitHub OAuth App Client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | 启用 GitHub 必填 | 同上 secret |

未配置任一 provider 时，登录页隐藏 OAuth 按钮，应用照常启动；`/api/auth/providers` 返回空列表，`/api/diagnostics/providers` 内 `oauth.encrypt_key_set=false`。

## 1. 生成 Fernet 加密密钥（一次性）

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

输出形如 `n7N-2vP_J3...XYZ=`（44 字符 url-safe base64）。
设入 env：

```bash
export OAUTH_ENCRYPT_KEY="<上面输出>"
```

> **重要**
> - 此密钥用于加密 `oauth_accounts.access_token_enc` / `refresh_token_enc`。
> - 丢失密钥后历史 token 无法解密。v1.0 不在运行时消费 access_token，丢失只影响审计与未来扩展（OAuth 续期、provider API 调用）。
> - 生产建议：云 KMS / 持久化 Volume / 密钥管理器。**不要**写入 git。
> - 启动时 `assert_key_configured()` 校验：缺失或格式错误 → fail-fast 拒绝启动，避免后续写入未加密 token。

## 2. Google OAuth Client

1. 访问 https://console.cloud.google.com → 创建 / 选择项目。
2. APIs & Services → Credentials → **Create OAuth client ID**。
3. Application type: **Web application**。
4. Authorized redirect URIs（每行一条，按部署环境追加）：

   ```
   https://<your-domain>/auth/oauth/google/callback
   http://localhost:5000/auth/oauth/google/callback   # 本地开发
   ```

   > 路径前缀必须是 `/auth/oauth/google/callback`，**不要**与 Schwab OAuth 的 `/oauth/schwab/callback` 混用。

5. 复制 Client ID 与 Client Secret：

   ```bash
   export GOOGLE_OAUTH_CLIENT_ID="...-...apps.googleusercontent.com"
   export GOOGLE_OAUTH_CLIENT_SECRET="GOCSPX-..."
   ```

### Google 行为说明

- v1.0 走 OIDC：scope `openid email profile`，授权后 Google 返回 id_token；后端用 Google JWKS 验证签名 + iss/aud/exp。
- `email_verified` 来自 id_token claim，Google 永远验证用户邮箱所有权 → 已存在邮箱可**自动合并**。
- 启用 `access_type=offline + prompt=consent` 拿 refresh_token，加密存储但 v1.0 不消费。

## 3. GitHub OAuth App

1. 访问 https://github.com/settings/developers → **New OAuth App**。
2. Authorization callback URL：

   ```
   https://<your-domain>/auth/oauth/github/callback
   ```

   开发本地用：`http://localhost:5000/auth/oauth/github/callback`。

3. 生成 Client Secret 后写入 env：

   ```bash
   export GITHUB_OAUTH_CLIENT_ID="Ov23li..."
   export GITHUB_OAUTH_CLIENT_SECRET="..."
   ```

### GitHub 行为说明

- GitHub 不实现 OIDC，没有 id_token：后端走 `/user` + `/user/emails` 获取 primary 邮箱及其 verified 状态。
- 仅当 `primary && verified=true` 时才允许**自动合并**到已存在邮箱；否则跳转 `/login?notice=email_unverified_link` 让用户走"先密码登录、再到 /settings 绑定"路径。
- GitHub 不支持 PKCE：authorize URL 会带 `code_challenge` 但被服务端忽略，不影响安全性（state 仍强校验）。
- scope `read:user user:email` 仅用于读取身份，不获取仓库权限。

## 4. 启动校验

应用启动时，`stock_trading_system/web/app.py::create_app` 在 `_user_repo` 初始化后立刻：

1. `add_oauth_accounts(db_path)`：幂等创建 oauth_accounts 表（已存在跳过）。
2. 检查 `GOOGLE_OAUTH_CLIENT_ID` 或 `GITHUB_OAUTH_CLIENT_ID` 是否配置。任一存在 → `assert_key_configured()` 强制校验 `OAUTH_ENCRYPT_KEY` 在场且格式合法，否则 fail-fast。

> Schwab OAuth 的 `/oauth/schwab/...` 路由前缀错开，不会冲突，且仍由 magic-link secret 保护。

## 5. 大陆访问可达性（可选）

`accounts.google.com` 在大陆部分 ISP 不可达，用户点击 Google 按钮会跳转超时。v1.0 行为：

- 不在前端做可达性探测，超时由用户感知后回退到邮箱密码登录。
- 后续 P1（R-OAUTH-16）规划：前端启动时做一次 `accounts.google.com` HEAD 探测，不可达自动隐藏 Google 按钮。

GitHub 在大陆访问相对稳定，无需额外处理。

## 6. 验证

部署后通过：

```bash
curl -s https://<your-domain>/api/diagnostics/providers | jq .oauth
```

期望输出形如：

```json
{
  "google":          { "configured": true },
  "github":          { "configured": true },
  "encrypt_key_set": true
}
```

`/api/auth/providers` 返回的 `providers` 数组应包含已配置的 provider。
