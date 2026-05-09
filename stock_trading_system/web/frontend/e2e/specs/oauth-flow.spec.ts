import { test, expect } from "@playwright/test"

/**
 * OAuth quick sign-in (v1.0) — front-end e2e for the login-page button
 * rendering logic and querystring-error/notice surfacing.
 *
 * The login HTML is server-rendered Jinja, so this spec uses
 * `page.setContent()` with a hand-curated harness mirroring the exact
 * `<script>` block in `templates/login.html`. The `/api/auth/providers`
 * endpoint is mocked via `page.route()` so no Flask backend is needed.
 *
 * What this protects:
 *   1. Empty providers list → no OAuth buttons, no divider, only the
 *      email/password form is visible.
 *   2. One provider → one OAuth button rendered, divider visible, href
 *      forwards `?next=`.
 *   3. Two providers → both rendered, divider visible.
 *   4. `?error=state_mismatch` querystring → friendly localized message
 *      shown, raw error code surfaced as a fallback.
 *   5. `?notice=email_unverified_link` → notice surface shows the
 *      provider + email pair instead of the generic error path.
 *
 * Replaces a vitest harness (which the project does not configure) with
 * a single Playwright spec whose mocking surface mirrors the production
 * fetch call exactly.
 */

const HARNESS_HTML = `<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8" /><title>oauth harness</title></head>
<body>
  <div class="auth-card">
    <div class="auth-notice" id="login-notice" style="display:none"></div>
    <div class="auth-error"  id="login-error"  style="display:none"></div>
    <div class="oauth-list"  id="oauth-list"></div>
    <div class="oauth-divider" id="oauth-divider" style="display:none">或使用邮箱密码</div>
    <input id="login-email"    type="email" />
    <input id="login-password" type="password" />
  </div>
  <script>
    // ─── Copy of the login.html script block under test ───────────────
    (function showOAuthMessages() {
      const params = new URLSearchParams(location.search);
      const err = params.get('error');
      const notice = params.get('notice');
      const errEl = document.getElementById('login-error');
      const noticeEl = document.getElementById('login-notice');
      const ERROR_MESSAGES = {
        state_mismatch: 'OAuth state 校验失败，请重试',
        missing_verifier: 'PKCE verifier 丢失，请重新登录',
        no_code: '授权未完成',
        unknown_provider: '未知的 OAuth 提供方',
        exchange_failed: '与 OAuth 提供方通信失败',
        link_requires_login: '请先登录后再绑定 OAuth',
      };
      if (err) {
        errEl.textContent = ERROR_MESSAGES[err] || ('登录失败: ' + err);
        errEl.style.display = 'block';
      }
      if (notice === 'email_unverified_link') {
        const provider = params.get('provider') || '';
        const email = params.get('email') || '';
        noticeEl.textContent =
          provider + ' 账户的邮箱 ' + email +
          ' 未验证，请先用邮箱密码登录后到设置中绑定';
        noticeEl.style.display = 'block';
      }
    })();
    (async function renderOAuthButtons() {
      try {
        const res = await fetch('/api/auth/providers', { credentials: 'same-origin' });
        if (!res.ok) return;
        const { providers } = await res.json();
        if (!providers || providers.length === 0) return;
        const list = document.getElementById('oauth-list');
        const divider = document.getElementById('oauth-divider');
        const params = new URLSearchParams(location.search);
        const next = params.get('next') || '/';
        list.innerHTML = providers.map(function (p) {
          const startUrl = '/auth/oauth/' + encodeURIComponent(p.name) +
                           '/start?next=' + encodeURIComponent(next);
          return '<a class="oauth-btn" href="' + startUrl + '">' +
                 '<img src="' + p.icon + '" width="20" height="20" alt="" />' +
                 '<span>' + p.label + '</span></a>';
        }).join('');
        divider.style.display = 'flex';
      } catch (_) { /* network failure: silently fall back */ }
    })();
  </script>
</body>
</html>`

/**
 * Serve the harness via route interception so `page.goto()` can carry
 * a real querystring — the inline script reads `location.search` to
 * decide which error/notice block to show, and `page.setContent()`
 * does not preserve a navigated URL.
 */
async function loadHarness(
  page: import("@playwright/test").Page,
  providers: Array<{ name: string; label: string; icon: string }>,
  opts: { search?: string } = {},
) {
  await page.route("**/api/auth/providers", async (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ providers }),
    }),
  )
  await page.route("**/oauth-harness*", async (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html; charset=utf-8",
      body: HARNESS_HTML,
    }),
  )
  await page.goto(
    "http://oauth-harness.test/oauth-harness" + (opts.search ?? ""),
    { waitUntil: "domcontentloaded" },
  )
}


test.describe("OAuth login button rendering", () => {

  test("empty providers list → no buttons, no divider", async ({ page }) => {
    await loadHarness(page, [])
    await page.waitForTimeout(100)  // allow async IIFE to settle
    await expect(page.locator(".oauth-btn")).toHaveCount(0)
    await expect(page.locator("#oauth-divider")).toBeHidden()
  })

  test("single provider → one button rendered with start URL", async ({ page }) => {
    await loadHarness(page, [
      { name: "google", label: "用 Google 登录", icon: "/static/icons/google.svg" },
    ])
    await expect(page.locator(".oauth-btn")).toHaveCount(1)
    const link = page.locator(".oauth-btn").first()
    await expect(link).toContainText("用 Google 登录")
    await expect(link).toHaveAttribute(
      "href",
      "/auth/oauth/google/start?next=%2F",
    )
    await expect(page.locator("#oauth-divider")).toBeVisible()
  })

  test("two providers → both buttons rendered, divider visible", async ({ page }) => {
    await loadHarness(page, [
      { name: "google", label: "用 Google 登录", icon: "/static/icons/google.svg" },
      { name: "github", label: "用 GitHub 登录", icon: "/static/icons/github.svg" },
    ])
    await expect(page.locator(".oauth-btn")).toHaveCount(2)
    await expect(page.locator("#oauth-divider")).toBeVisible()
  })

})


test.describe("OAuth login error/notice surfacing", () => {

  test("?error=state_mismatch → localized error visible", async ({ page }) => {
    await loadHarness(page, [], { search: "?error=state_mismatch" })
    await expect(page.locator("#login-error"))
      .toContainText("OAuth state 校验失败")
  })

  test("?error=unknown_code → fallback to raw error", async ({ page }) => {
    await loadHarness(page, [], { search: "?error=mystery_code" })
    await expect(page.locator("#login-error"))
      .toContainText("登录失败: mystery_code")
  })

  test("?notice=email_unverified_link → notice with provider+email", async ({ page }) => {
    await loadHarness(page, [], {
      search: "?notice=email_unverified_link&provider=github&email=alice%40x.com",
    })
    const text = await page.locator("#login-notice").textContent()
    expect(text).toContain("github")
    expect(text).toContain("alice@x.com")
  })

})
