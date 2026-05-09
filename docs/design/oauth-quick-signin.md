# 设计方案：第三方快捷登录（Google + GitHub）v1.0

| 项 | 值 |
|---|---|
| Feature | `oauth-quick-signin` |
| 版本 | v1.0 |
| 日期 | 2026-05-09 |
| 关联 PRD | [../prd/oauth-quick-signin.md](../prd/oauth-quick-signin.md) |

---

## 1. 现状审计

### 1.1 用户表 schema（[`migrations/to_multi_tenant.py`](../../stock_trading_system/migrations/to_multi_tenant.py)）

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,            -- ⚠️ NOT NULL,OAuth 用户用占位
  display_name TEXT NOT NULL,
  role TEXT DEFAULT 'user',
  status TEXT DEFAULT 'active',
  created_at TEXT, last_login_at TEXT,
  password_reset_token TEXT,
  password_reset_expires_at TEXT
);
```

### 1.2 已有认证路由

| 端点 | 文件:行 | 行为 |
|---|---|---|
| `/api/auth/login` | [`web/app.py:683`](../../stock_trading_system/web/app.py) | email + password → `verify_password` → `session["user_id"]` |
| `/api/auth/register` | [`web/app.py:700`](../../stock_trading_system/web/app.py) | invite_code 校验 → `repo.create()` → `_invite_mgr.redeem()` |
| `/api/auth/logout` | [`web/app.py:732`](../../stock_trading_system/web/app.py) | session.clear() |
| `login_required` | [`auth/decorators.py:10`](../../stock_trading_system/auth/decorators.py) | 保护应用路由，未登录 → `/login?next=...` |

### 1.3 现成可复用的 OAuth pattern

[`/oauth/schwab/start`](../../stock_trading_system/web/app.py#L916) + [`/oauth/schwab/callback`](../../stock_trading_system/web/app.py) 已实装完整 OAuth 2.0 Authorization Code flow（[app.py:903-960](../../stock_trading_system/web/app.py)），含 magic-link guard / state / token 持久化。本期 OAuth-2 几乎同 flow，仅 provider 切换 + 多了 user 创建/绑定步骤。

### 1.4 已有依赖

- `flask>=3.0`, `flask-wtf>=1.2`（CSRF）, `bcrypt>=4.1`, `requests`（schwab-py 传递）
- TradingAgents 间接拉了 `cryptography`（fernet 可用）

**新增**：`authlib>=1.3`

---

## 2. Schema 升级

### 2.1 新增 `oauth_accounts` 表

```sql
CREATE TABLE IF NOT EXISTS oauth_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,                    -- 'google' | 'github'
  provider_user_id TEXT NOT NULL,            -- 厂商侧 sub / id
  email TEXT,                                -- 厂商返回的邮箱(可能 NULL on GitHub private)
  email_verified INTEGER NOT NULL DEFAULT 0, -- 0/1
  raw_profile_json TEXT,                     -- 完整 profile 留档(name/picture/etc)
  access_token_enc TEXT,                     -- fernet 加密
  refresh_token_enc TEXT,                    -- fernet 加密
  expires_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at TEXT,
  UNIQUE(provider, provider_user_id)
);
CREATE INDEX IF NOT EXISTS idx_oauth_user ON oauth_accounts(user_id);
```

**关键约束**：
- `(provider, provider_user_id) UNIQUE` 防止同一 OAuth 账户绑定到多个 user。
- `ON DELETE CASCADE` —— user 软删除时不动（status='deleted'），硬删除时级联（生产几乎不会用到）。

### 2.2 不动 users 表

OAuth-only 用户走 `repo.create(email, password=secrets.token_urlsafe(32), ...)`：
- `password_hash NOT NULL` 约束满足
- 用户用不到这个密码（直到主动设密码）
- 未来如要"OAuth-only 标志"可加 users 表布尔列，**v1.0 不做**

---

## 3. 模块结构

```
stock_trading_system/auth/
├── repository.py          # ← 已有，不动
├── invite.py              # ← 已有，不动
├── decorators.py          # ← 已有，不动
├── password.py            # ← 已有，不动
├── session.py             # ← 已有，不动
├── oauth_repository.py    # ← 新建
├── oauth_providers/
│   ├── __init__.py        # ← 新建：Protocol + factory
│   ├── google.py          # ← 新建
│   └── github.py          # ← 新建
└── oauth_crypto.py        # ← 新建：fernet token 加密
```

---

## 4. Provider 抽象

### 4.1 `OAuthProvider` Protocol（[`auth/oauth_providers/__init__.py`](../../stock_trading_system/auth/oauth_providers/__init__.py)）

```python
from typing import Protocol, NamedTuple

class OAuthProfile(NamedTuple):
    sub: str                        # 厂商唯一 ID
    email: str | None               # 可能 None(GitHub private email)
    email_verified: bool
    name: str | None
    raw: dict                       # 完整 profile 留档


class OAuthTokens(NamedTuple):
    access_token: str
    refresh_token: str | None
    expires_at: str | None          # ISO 时间字符串


class OAuthProvider(Protocol):
    name: str                       # 'google' | 'github'
    label: str                      # '用 Google 登录'

    def is_enabled(self) -> bool: ...

    def build_authorize_url(
        self, *, state: str, code_challenge: str, redirect_uri: str,
    ) -> str: ...

    def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str,
    ) -> tuple[OAuthProfile, OAuthTokens]: ...
```

### 4.2 `GoogleProvider`（[`auth/oauth_providers/google.py`](../../stock_trading_system/auth/oauth_providers/google.py)）

用 Authlib `OAuth2Session`，OIDC discovery URL：`https://accounts.google.com/.well-known/openid-configuration`。

- scope: `openid email profile`
- email_verified 直接读 ID Token 的 `email_verified` claim（永远是 bool）
- profile 字段：`sub / email / email_verified / name / picture / locale`

### 4.3 `GitHubProvider`（[`auth/oauth_providers/github.py`](../../stock_trading_system/auth/oauth_providers/github.py)）

GitHub 不是 OIDC，用 OAuth 2.0 Auth Code。

- scope: `read:user user:email`
- 流程：exchange code → 拿 access_token → `GET /user` 拿 sub/name → `GET /user/emails` 找 `primary && verified` 邮箱
- email_verified 来源：`/user/emails` 返回的 `verified=true`（GitHub 自己验证的）
- 重要：GitHub 邮箱可能 private，如 primary 邮箱 `verified=false` 视为 email_verified=False

### 4.4 Factory + Registry

```python
def get_enabled_providers(config: dict) -> dict[str, OAuthProvider]:
    """Return enabled providers. Empty dict if no env keys."""
    out = {}
    if os.environ.get("GOOGLE_OAUTH_CLIENT_ID"):
        out["google"] = GoogleProvider(config)
    if os.environ.get("GITHUB_OAUTH_CLIENT_ID"):
        out["github"] = GitHubProvider(config)
    return out
```

未配置 env 的 provider 不出现在 `/api/auth/providers` 响应里，前端按钮不渲染。

---

## 5. 新路由（6 个）

### 5.1 `GET /auth/oauth/<provider>/start?intent=login&next=/`

```python
def start(provider_name):
    provider = providers.get(provider_name)
    if not provider:
        return redirect("/login?error=unknown_provider")

    intent = request.args.get("intent", "login")  # 'login' | 'link'
    next_url = _safe_next(request.args.get("next", "/"))

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _pkce_challenge(code_verifier)

    session["oauth_state"] = state
    session["oauth_code_verifier"] = code_verifier
    session["oauth_intent"] = intent
    session["oauth_next"] = next_url
    session["oauth_provider"] = provider_name

    redirect_uri = url_for("oauth_callback", provider_name=provider_name, _external=True)
    return redirect(provider.build_authorize_url(
        state=state, code_challenge=code_challenge, redirect_uri=redirect_uri,
    ))
```

### 5.2 `GET /auth/oauth/<provider>/callback?code=...&state=...`

核心分支逻辑（**整个 OAuth 设计的关键**）：

```python
def callback(provider_name):
    # —— state + PKCE 校验 ——
    if request.args.get("state") != session.pop("oauth_state", None):
        return redirect("/login?error=state_mismatch")
    code_verifier = session.pop("oauth_code_verifier", None)
    if not code_verifier:
        return redirect("/login?error=missing_verifier")
    intent = session.pop("oauth_intent", "login")
    next_url = session.pop("oauth_next", "/")
    session.pop("oauth_provider", None)

    provider = providers.get(provider_name)
    if not provider:
        return redirect("/login?error=unknown_provider")

    # —— exchange code ——
    redirect_uri = url_for("oauth_callback", provider_name=provider_name, _external=True)
    try:
        profile, tokens = provider.exchange_code(
            code=request.args["code"],
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    except OAuthExchangeError as e:
        logger.warning("oauth exchange failed: %s", e)
        return redirect("/login?error=exchange_failed")

    # —— 1. intent=link(已登录用户主动绑定) ——
    if intent == "link":
        if g.user is None:
            return redirect("/login?error=link_requires_login")
        existing = oauth_repo.find_by_provider_id(provider_name, profile.sub)
        if existing and existing.user_id != g.user.id:
            return redirect("/settings?error=oauth_taken")
        oauth_repo.upsert(
            user_id=g.user.id, provider=provider_name, profile=profile, tokens=tokens,
        )
        return redirect(next_url + "?linked=" + provider_name)

    # —— 2. intent=login: 已绑定该 OAuth → 直接登录 ——
    existing_oauth = oauth_repo.find_by_provider_id(provider_name, profile.sub)
    if existing_oauth:
        oauth_repo.update_last_login(existing_oauth.id, profile=profile, tokens=tokens)
        _login_session(existing_oauth.user_id)
        return redirect(next_url)

    # —— 3. intent=login: 邮箱已存在 ——
    if profile.email:
        existing_user = repo.find_by_email(profile.email)
        if existing_user:
            if profile.email_verified:
                # 3a. provider email 已验证 → 自动合并
                oauth_repo.upsert(
                    user_id=existing_user.id, provider=provider_name,
                    profile=profile, tokens=tokens,
                )
                _login_session(existing_user.id)
                logger.info("oauth auto-link: user=%d provider=%s", existing_user.id, provider_name)
                return redirect(next_url + "?linked=" + provider_name)
            else:
                # 3b. provider email 未验证(GitHub private/未验证) → 二次确认
                return redirect(
                    "/login?notice=email_unverified_link"
                    f"&provider={provider_name}&email={profile.email}"
                )

    # —— 4. intent=login + 邮箱不存在(全新用户) → 跳注册 ——
    pending = _make_pending_token({
        "provider": provider_name,
        "sub": profile.sub,
        "email": profile.email or "",
        "name": profile.name or "",
        "tokens": tokens._asdict(),
    })
    return redirect(
        f"/register?provider={provider_name}&pending={pending}"
        f"&email={profile.email or ''}&name={profile.name or ''}"
    )
```

### 5.3 `POST /api/auth/oauth/register`（新用户最终注册）

```python
def oauth_register():
    body = request.get_json() or {}
    pending = body.get("pending", "")
    invite_code = body.get("invite_code", "")
    display_name = body.get("display_name", "")

    payload = _verify_pending_token(pending)
    if not payload:
        return jsonify({"reason": "pending_invalid"}), 400

    err = _invite_mgr.validate(invite_code)
    if err:
        return jsonify({"reason": err}), 400

    email = payload["email"]
    if not email:
        # GitHub 没返回邮箱时,前端必填,这里再校一遍
        email = (body.get("email") or "").strip().lower()
        if not email:
            return jsonify({"reason": "email_required"}), 400

    if repo.find_by_email(email):
        return jsonify({"reason": "email_exists"}), 400

    new_user = repo.create(
        email=email,
        password=secrets.token_urlsafe(32),  # 占位 hash
        display_name=display_name or payload["name"] or email.split("@")[0],
    )
    oauth_repo.upsert(
        user_id=new_user.id,
        provider=payload["provider"],
        profile=OAuthProfile(
            sub=payload["sub"], email=email, email_verified=True,
            name=payload["name"], raw={},
        ),
        tokens=OAuthTokens(**payload["tokens"]),
    )
    _invite_mgr.redeem(invite_code, new_user.id)
    _login_session(new_user.id)
    return jsonify({"ok": True, "user_id": new_user.id})
```

### 5.4 `GET /api/auth/oauth/linked`（已登录用户的绑定列表）

```python
@login_required
def linked():
    rows = oauth_repo.list_by_user(g.user.id)
    return jsonify({
        "providers": [
            {"provider": r.provider, "email": r.email,
             "linked_at": r.created_at, "last_login_at": r.last_login_at}
            for r in rows
        ],
        "has_password": True,  # v1.0 永远 true,因为创建 user 必有占位 hash
    })
```

### 5.5 `POST /api/auth/oauth/<provider>/unlink`

```python
@login_required
def unlink(provider_name):
    rows = oauth_repo.list_by_user(g.user.id)
    has_password = True  # 占位 hash 不算真密码,但 v1.0 简化为永远 true
    other_oauth_count = sum(1 for r in rows if r.provider != provider_name)

    # 至少保留一种登录方式
    if not has_password and other_oauth_count == 0:
        return jsonify({"reason": "last_method"}), 400

    oauth_repo.delete_by_user_provider(g.user.id, provider_name)
    return jsonify({"ok": True})
```

> v1.0 说明：因为占位密码方案，`has_password` 永远 true，所以 `last_method` 检查实际只在用户设了真密码后才有意义。当前简化为永远允许解绑（前提是用户至少还有一种 OAuth 或密码登录方式）。

### 5.6 `GET /api/auth/providers`

```python
def list_providers():
    enabled = get_enabled_providers(get_config())
    return jsonify({
        "providers": [
            {"name": p.name, "label": p.label, "icon": f"/static/icons/{p.name}.svg"}
            for p in enabled.values()
        ],
    })
```

---

## 6. PKCE 与 pending token

### 6.1 PKCE

```python
def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
```

verifier 写入 session，callback 时取出送给 provider 换 token，Authlib 自动校验。

### 6.2 Pending token（新用户跨页面状态）

回调到 `/register` 时不能直接传 sub/email 明文（攻击者可伪造），用 itsdangerous 签名 token：

```python
from itsdangerous import URLSafeTimedSerializer

def _make_pending_token(payload: dict) -> str:
    s = URLSafeTimedSerializer(app.secret_key, salt="oauth-pending")
    return s.dumps(payload)

def _verify_pending_token(token: str, max_age=600) -> dict | None:
    s = URLSafeTimedSerializer(app.secret_key, salt="oauth-pending")
    try:
        return s.loads(token, max_age=max_age)
    except Exception:
        return None
```

10 分钟过期。

---

## 7. Token 加密（[`auth/oauth_crypto.py`](../../stock_trading_system/auth/oauth_crypto.py)）

```python
from cryptography.fernet import Fernet
import os

def _key() -> bytes:
    raw = os.environ.get("OAUTH_ENCRYPT_KEY")
    if not raw:
        raise RuntimeError("OAUTH_ENCRYPT_KEY env not set (generate via Fernet.generate_key())")
    return raw.encode() if isinstance(raw, str) else raw

def encrypt_token(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return Fernet(_key()).encrypt(plaintext.encode()).decode()

def decrypt_token(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    return Fernet(_key()).decrypt(ciphertext.encode()).decode()
```

启动时校验 `OAUTH_ENCRYPT_KEY` 在场，不在场则启动失败（fail-fast，避免半天后才发现 token 没加密）。

生成密钥（一次性）：
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

---

## 8. 前端集成

### 8.1 `/login` 页（[`templates/login.html`](../../stock_trading_system/web/templates/login.html)）

加 OAuth 按钮区（位于邮箱密码 form 上方）：

```html
<div id="oauth-buttons" style="display: none">
  <!-- JS 根据 /api/auth/providers 渲染 -->
</div>
<div class="divider">或使用邮箱密码</div>
<!-- 现有 form 不动 -->

<script>
  fetch("/api/auth/providers").then(r => r.json()).then(({providers}) => {
    if (providers.length === 0) return;
    const root = document.getElementById("oauth-buttons");
    root.style.display = "block";
    root.innerHTML = providers.map(p => `
      <a href="/auth/oauth/${p.name}/start?next=/" class="oauth-btn">
        <img src="${p.icon}" /> ${p.label}
      </a>
    `).join("");
  });

  // 大陆访问探测(可选 v1.0):Google 探测,5xx/timeout 隐藏 Google 按钮
  // 实装放在 R-OAUTH-16 P1
</script>
```

### 8.2 `/register` 页（[`templates/register.html`](../../stock_trading_system/web/templates/register.html)）

接收 `?provider=google&pending=<token>&email=...&name=...`：

```html
{% if request.args.get('provider') %}
<div class="alert alert-info">
   已通过 {{ request.args.get('provider') | title }} 验证身份
  邮箱: <strong>{{ request.args.get('email') }}</strong>
</div>
{% endif %}

<form id="oauth-register-form" {% if request.args.get('provider') %}data-mode="oauth"{% endif %}>
  <input name="email" value="{{ request.args.get('email', '') }}"
         {% if request.args.get('provider') %}readonly{% endif %} required>
  <input name="display_name" value="{{ request.args.get('name', '') }}" required>
  <input name="invite_code" required placeholder="邀请码">
  {% if request.args.get('provider') %}
    <input type="hidden" name="pending" value="{{ request.args.get('pending') }}">
  {% else %}
    <input name="password" type="password" required>
  {% endif %}
  <button type="submit">注册</button>
</form>

<script>
  document.getElementById("oauth-register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const isOAuth = form.dataset.mode === "oauth";
    const url = isOAuth ? "/api/auth/oauth/register" : "/api/auth/register";
    const body = Object.fromEntries(new FormData(form));
    const res = await fetch(url, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) location.href = "/";
    else alert(data.reason || "注册失败");
  });
</script>
```

### 8.3 `/settings` 加"登录方式" section（[`SettingsPage.tsx`](../../stock_trading_system/web/frontend/src/islands/settings/SettingsPage.tsx)）

```tsx
function LoginMethodsSection() {
  const [data, setData] = useState<{providers: LinkedProvider[]} | null>(null);
  const [enabled, setEnabled] = useState<EnabledProvider[]>([]);

  useEffect(() => {
    apiGet("/api/auth/oauth/linked").then(setData);
    apiGet<{providers: EnabledProvider[]}>("/api/auth/providers").then(r => setEnabled(r.providers));
  }, []);

  if (!data) return null;
  const linkedNames = new Set(data.providers.map(p => p.provider));

  return (
    <Card>
      <CardHeader><CardTitle>登录方式</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        <div className="flex justify-between">
          <span>✓ 邮箱密码</span>
          <Button variant="ghost" onClick={() => navigate("/settings/password")}>修改密码</Button>
        </div>
        {data.providers.map(p => (
          <div key={p.provider} className="flex justify-between">
            <span>✓ {p.provider} {p.email}</span>
            <Button variant="ghost" onClick={() => unlink(p.provider)}>解绑</Button>
          </div>
        ))}
        {enabled.filter(e => !linkedNames.has(e.name)).map(e => (
          <div key={e.name} className="flex justify-between">
            <a href={`/auth/oauth/${e.name}/start?intent=link&next=/settings`}>
              + 关联 {e.label}
            </a>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
```

---

## 9. 测试

### 9.1 后端单测

`tests/auth/test_oauth_repository.py` —— 6 case：upsert / find_by_provider_id / list_by_user / delete / UNIQUE 约束 / 多租户隔离

`tests/auth/test_oauth_providers.py` —— 8 case（mock requests）：
- Google authorize URL 含 `code_challenge` + state
- Google exchange code 解析 ID Token 拿到 email_verified
- GitHub authorize URL 含 `read:user user:email` scope
- GitHub exchange code 后调 `/user/emails` 取 primary
- GitHub primary email verified=false → email_verified=False
- 各 provider `is_enabled()` 反映 env

`tests/auth/test_oauth_callback.py` —— 5 路径分支 + 边界 ~12 case：
- state 不匹配拒绝
- code exchange 失败重定向 error
- 已绑定 provider 直接登录
- 自动合并（Google + email_verified=true + 邮箱已存在）
- 二次确认（GitHub + email_verified=false + 邮箱已存在）
- 全新用户跳 `/register?pending=<token>`
- intent=link 已登录绑定
- intent=link OAuth 已被其他用户占用 → error
- 多租户：bob 不能 link 到 alice 的 oauth_account

`tests/auth/test_oauth_register.py` —— 6 case：
- 有效 pending + 有效 invite_code → 创建 user + 绑 oauth + redeem
- 无效 pending → 400
- pending 过期（>10min）→ 400
- 无邀请码 → 400
- 邀请码已用 → 400
- email 已存在 → 400

`tests/auth/test_oauth_unlink.py` —— 4 case：解绑成功 / 跨用户 404 / last_method 拒绝 / 不存在的绑定 404

`tests/auth/test_oauth_crypto.py` —— 3 case：encrypt 后非明文 / decrypt 还原 / 无 KEY env 时启动 fail

### 9.2 前端单测

`tests/frontend/auth/oauth-buttons.test.tsx` —— `/api/auth/providers` 返回空时不渲染按钮区 / 返回 google+github 时渲染两按钮 / 按钮 href 正确

`tests/frontend/settings/login-methods.test.tsx` —— 已绑定 + 未绑定混合渲染 / 解绑调 unlink API / 关联跳 start

### 9.3 E2E（手动 / 半自动）

1. 全新邮箱用 Google 登录 → /register 预填 → 填邀请码 → 创建账户 + 登录 ✓
2. 邮箱已存在 + Google 首次登录 → 自动合并 + 登录 ✓
3. 邮箱已存在 + GitHub 首次登录（primary email verified=false）→ 二次确认提示 ✓
4. 已登录用户在 settings 关联 GitHub → settings 显示已绑定 ✓
5. 解绑 Google（仍有密码 + GitHub）→ 成功 ✓
6. 跨用户尝试绑定别人的 Google → error ✓
7. 大陆环境（无梯子）打开 /login → Google 按钮探测后隐藏（v1.0 P1）

---

## 10. 实施顺序

| 步骤 | 工作 | 文件 | LOC |
|---|---|---|---|
| 1 | `oauth_accounts` 表 migration（idempotent） | `migrations/add_oauth_accounts.py` | ~30 |
| 2 | `OAuthAccountRepository` + 单测 | `auth/oauth_repository.py`, tests | ~150 |
| 3 | `oauth_crypto.py` fernet + 单测 + env 启动校验 | `auth/oauth_crypto.py`, `web/app.py` startup | ~50 |
| 4 | `OAuthProvider` Protocol + Google + GitHub + 单测 | `auth/oauth_providers/*.py`, tests | ~250 |
| 5 | `_make/_verify_pending_token` 工具 + `_pkce_challenge` + `_safe_next` + `_login_session` | `auth/oauth_session.py` | ~80 |
| 6 | 6 个新路由 + callback 5 路径分支 + 单测 | `web/app.py` (新 ~200 行), tests | ~350 |
| 7 | requirements.txt 加 `authlib>=1.3` + 必要时 `itsdangerous`（已被 Flask 拉入） | requirements.txt | +1 行 |
| 8 | env 文档：`docs/deployment/oauth-env.md` 写 4 个 env + 生成 fernet key 步骤 | docs | ~80 行 |
| 9 | 前端 login.html / register.html 模板加 OAuth 按钮 + form mode 切换 | templates | ~80 |
| 10 | SettingsPage.tsx 加 LoginMethodsSection | `islands/settings/SettingsPage.tsx`, tests | ~150 |
| 11 | `/api/diagnostics/providers` 加 OAuth 项 | `web/app.py` | ~20 |
| 12 | 手动回归 7 项 | — | — |
| **合计** | | | **~1240 LOC** + ~80 行文档 |

每步独立 commit。预估总工时 ~5h（不含 OAuth client 的 GCP/GitHub 控制台配置）。

---

## 11. 严格不动清单

- [`/oauth/schwab/start`](../../stock_trading_system/web/app.py#L916) 路由（Schwab 数据源 OAuth，前缀错开）
- `users` 表 schema（OAuth 用户用占位 password_hash）
- `_invite_mgr.validate / redeem` 邀请码逻辑（[v1.18 R-fix-12](analysis-inbox.md) 多租户红线）
- `login_required` decorator
- 现有 `/api/auth/login` `/api/auth/register` `/api/auth/logout` 路由
- `verify_password` / `hash_password` 函数
- session 结构（`session["user_id"]` 仍是唯一登录态标志）
- shadcn UI primitives
- TradingAgents / 数据层 / LLM / screener 等业务逻辑

---

## 12. 风险

| 风险 | 影响 | 处理 |
|---|---|---|
| Google 大陆访问失败 | 用户登录跳转超时 | R-OAUTH-16 前端探测自动隐藏；邮箱密码 fallback 永在 |
| 邮箱劫持 | attacker 抢注后被自动合并 | email_verified=true 才合并；GitHub 走二次确认；audit log 记录所有 auto-link 事件 |
| OAUTH_ENCRYPT_KEY 丢失 | 历史 oauth_accounts 行的 token 无法解密 | v1.0 access_token 不消费，丢失只影响审计；启动时 fail-fast 至少阻止后续写入坏数据；建议密钥用云 KMS / Volume 持久化 |
| pending token 过期（10min） | 用户填到一半超时 | error 提示重新走 OAuth 流程；不可延长太久（攻击窗口）|
| state / PKCE session 丢失（用户清 cookie） | 回调 state 不匹配 → 500 | 友好 error 页 "登录会话丢失，请重新发起" |
| OAuth provider 接口变更 | 登录失败 | provider 抽象层 + Authlib 屏蔽差异；监控登录失败率 + alert |
| 解绑后丢失登录方式 | 用户被锁外面 | unlink 必检至少保留一种 |
| 用户用 Google 邮箱注册后改邮箱 | 邮箱与 oauth_accounts.email 不一致 | oauth_accounts.email 仅作展示；登录依赖 (provider, sub) UNIQUE 不依赖 email |

---

*v1.0 设计稿 — 等待确认后开始实施*
