import { useCallback, useEffect, useState } from "react"
import { Settings, Save, RefreshCw, Eye, EyeOff, Trash2, Clock, PlayCircle, CheckCircle2, Link2, KeyRound } from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Switch } from "@/components/ui/switch"
import { apiGet, apiPost, ApiError } from "@/lib/api"
import { toast } from "@/components/ui/toaster"
import { useOnboardingState } from "@/components/shared/onboarding/useOnboardingState"

// Backend response shape from GET /api/settings (see web/app.py::api_settings).
interface SettingsResponse {
  gemini?: {
    model?: string
    deep_think_model?: string
    thinking_level?: string
    api_key_masked?: string
  }
  qwen?: {
    enabled?: boolean
    model?: string
    base_url?: string
    api_key_masked?: string
  }
  // v1.0 (llm-openrouter): aggregator slice surfaced by /api/settings.
  // presets[] / active{} are read here for the section's preset table;
  // mutations to active.{deep,quick} go through the dedicated
  // /api/settings/openrouter/active POST (the LLMSwitcher path), so
  // this slice is mostly a *display* surface plus the scalar fields
  // editable through WRITABLE_SETTING_PATHS.
  openrouter?: {
    enabled?: boolean
    active?: boolean    // computed: env or yaml api_key present
    base_url?: string
    http_referer?: string
    x_title?: string
    timeout?: number
    api_key_masked?: string
    presets?: Array<{
      id: string; label: string; model: string; role: string
      provider_order?: string[]; kwargs?: Record<string, unknown>
    }>
    active_pointers?: { deep?: string; quick?: string }
  }
  polygon?: { api_key_masked?: string }
  ib?: { host?: string; port?: string | number; client_id?: string | number; enabled?: boolean }
  telegram?: { bot_token_masked?: string; chat_id?: string }
  email?: {
    smtp_host?: string
    smtp_port?: string | number
    username?: string
    password_masked?: string
    to_address?: string
  }
  writable_paths?: string[]
}

// Whitelist mirrors WRITABLE_SETTING_PATHS in stock_trading_system/config/settings.py.
// Submitting any other key would be rejected by the backend with 400.
type DottedSettingsPayload = Record<string, string | number | boolean>

export function SettingsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [showKeys, setShowKeys] = useState(false)
  const [snapshot, setSnapshot] = useState<SettingsResponse | null>(null)
  // Tracks which provider's "清空" button is currently in flight so we can
  // show a spinner without freezing the rest of the form.
  const [clearing, setClearing] = useState<"gemini" | "qwen" | "openrouter" | null>(null)

  // ── LLM section ────────────────────────────────────────────────────────
  const [geminiKey, setGeminiKey] = useState("")
  const [geminiModel, setGeminiModel] = useState("")
  const [qwenEnabled, setQwenEnabled] = useState(false)
  const [qwenKey, setQwenKey] = useState("")
  const [qwenModel, setQwenModel] = useState("")
  const [qwenBaseUrl, setQwenBaseUrl] = useState("")

  // ── OpenRouter section (v1.0) ──────────────────────────────────────────
  // Form state mirrors the editable scalars in WRITABLE_SETTING_PATHS;
  // presets[] / active{} surface as read-only blocks because edits go
  // through the dedicated /openrouter/active endpoint (or yaml hand-edit
  // for the v1.0 'add preset' path which the UI doesn't yet expose).
  const [orEnabled, setOrEnabled] = useState(false)
  const [orKey, setOrKey] = useState("")
  const [orBaseUrl, setOrBaseUrl] = useState("")
  const [orReferer, setOrReferer] = useState("")
  const [orTitle, setOrTitle] = useState("")
  const [orTimeout, setOrTimeout] = useState<number>(120)

  // ── Notification section ───────────────────────────────────────────────
  const [emailEnabled, setEmailEnabled] = useState(false)
  const [emailTo, setEmailTo] = useState("")
  const [emailSmtpHost, setEmailSmtpHost] = useState("")
  const [emailUsername, setEmailUsername] = useState("")
  const [telegramEnabled, setTelegramEnabled] = useState(false)
  const [telegramChatId, setTelegramChatId] = useState("")

  const refreshSnapshot = useCallback(async (initial = false) => {
    if (initial) setLoading(true)
    setError(null)
    try {
      const res = await apiGet<SettingsResponse>("/api/settings")
      setSnapshot(res)
      setGeminiModel(res.gemini?.model ?? "")
      setQwenEnabled(Boolean(res.qwen?.enabled))
      setQwenModel(res.qwen?.model ?? "")
      setQwenBaseUrl(res.qwen?.base_url ?? "")
      // OR scalars
      setOrEnabled(Boolean(res.openrouter?.enabled))
      setOrBaseUrl(res.openrouter?.base_url ?? "https://openrouter.ai/api/v1")
      setOrReferer(res.openrouter?.http_referer ?? "")
      setOrTitle(res.openrouter?.x_title ?? "StockAI Terminal")
      setOrTimeout(Number(res.openrouter?.timeout ?? 120))
      setEmailTo(res.email?.to_address ?? "")
      setEmailSmtpHost(res.email?.smtp_host ?? "")
      setEmailUsername(res.email?.username ?? "")
      setTelegramChatId(res.telegram?.chat_id ?? "")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load settings")
    } finally {
      if (initial) setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshSnapshot(true)
  }, [refreshSnapshot])

  const clearProviderKey = async (provider: "gemini" | "qwen" | "openrouter") => {
    const masked = provider === "gemini"
      ? snapshot?.gemini?.api_key_masked
      : provider === "qwen"
        ? snapshot?.qwen?.api_key_masked
        : snapshot?.openrouter?.api_key_masked
    if (!masked) return  // nothing to clear
    const label = provider === "gemini" ? "Gemini" : provider === "qwen" ? "Qwen" : "OpenRouter"
    if (!window.confirm(`确定清空已保存的 ${label} API Key？此操作会立即生效，下一次分析将无法使用 ${label}。`)) {
      return
    }
    setClearing(provider)
    setSaveMsg(null)
    setError(null)
    try {
      // Submit the empty string explicitly — backend update_user_config
      // (config/settings.py) writes the empty string through, which is the
      // documented way to clear a saved credential.
      await apiPost("/api/settings", { [`${provider}.api_key`]: "" })
      // Mirror immediately in local state so the masked indicator vanishes
      // before the GET resolves.
      if (provider === "gemini") setGeminiKey("")
      if (provider === "qwen") setQwenKey("")
      if (provider === "openrouter") setOrKey("")
      await refreshSnapshot()
      setSaveMsg(`${label} API Key 已清空`)
      setTimeout(() => setSaveMsg(null), 3000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `${label} API Key 清空失败`)
    } finally {
      setClearing(null)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg(null)
    setError(null)
    // Only emit dotted-path keys the backend whitelists. Empty input on the
    // api_key fields means "leave whatever is on disk alone" — to actually
    // wipe a saved key, the user clicks the dedicated "清空" button which
    // POSTs the explicit empty string. We drop the api_key keys here so a
    // routine save never accidentally overwrites a stored credential.
    const payload: DottedSettingsPayload = {
      "gemini.model": geminiModel,
      "qwen.enabled": qwenEnabled,
      "qwen.model": qwenModel,
      "qwen.base_url": qwenBaseUrl,
      // OpenRouter scalars (presets[]/active{} go through the
      // dedicated /api/settings/openrouter/active endpoint).
      "openrouter.enabled":      orEnabled,
      "openrouter.base_url":     orBaseUrl,
      "openrouter.http_referer": orReferer,
      "openrouter.x_title":      orTitle,
      "openrouter.timeout":      orTimeout,
      "alerts.email.enabled": emailEnabled,
      "alerts.email.to_address": emailTo,
      "alerts.email.smtp_host": emailSmtpHost,
      "alerts.email.username": emailUsername,
      "alerts.telegram.enabled": telegramEnabled,
      "alerts.telegram.chat_id": telegramChatId,
    }
    if (geminiKey) payload["gemini.api_key"] = geminiKey
    if (qwenKey) payload["qwen.api_key"] = qwenKey
    if (orKey) payload["openrouter.api_key"] = orKey
    try {
      await apiPost("/api/settings", payload)
      setSaveMsg("设置已保存")
      setGeminiKey("")
      setQwenKey("")
      setOrKey("")
      await refreshSnapshot()
      setTimeout(() => setSaveMsg(null), 3000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    )
  }

  if (error && !snapshot) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <Alert variant="destructive">
          <AlertTitle>加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => window.location.reload()}>
          <RefreshCw className="h-4 w-4 mr-1" />
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6 min-w-0">
      <div className="mobile-card-header">
        <div className="mc-title flex items-center gap-3 min-w-0">
          <Settings className="icon-fixed text-[var(--color-accent-blue)] h-5 w-5" />
          <h1 className="text-xl font-bold truncate">系统设置</h1>
        </div>
        <div className="mc-actions">
          <Button onClick={handleSave} disabled={saving}>
            {saving ? (
              <>
                <RefreshCw className="icon-fixed mr-1 animate-spin" />
                保存中...
              </>
            ) : (
              <>
                <Save className="icon-fixed mr-1" />
                保存设置
              </>
            )}
          </Button>
        </div>
      </div>

      {saveMsg && (
        <Alert variant="success">
          <AlertDescription>{saveMsg}</AlertDescription>
        </Alert>
      )}
      {error && snapshot && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* AI 模型 */}
      <Card>
        <CardHeader>
          <div className="mobile-card-header">
            <div className="mc-title min-w-0">
              <CardTitle>AI 模型</CardTitle>
              <CardDescription>
                配置 Gemini 与 Qwen API 密钥及模型
              </CardDescription>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="mc-actions"
              onClick={() => setShowKeys(!showKeys)}
            >
              {showKeys ? <EyeOff className="icon-fixed" /> : <Eye className="icon-fixed" />}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-5">
            {/* Gemini */}
            <div className="space-y-3">
              <div className="text-sm font-semibold">Gemini</div>
              <div className="grid gap-3 sm:grid-cols-2 grid-collapse-mobile">
                <div className="space-y-1.5 min-w-0">
                  <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
                    <label className="text-xs text-muted-foreground min-w-0 flex-1 truncate">
                      API Key {snapshot?.gemini?.api_key_masked && (
                        <span className="ml-2 font-mono">已配置 <span className="text-safe inline-block max-w-[12rem] align-bottom">{snapshot.gemini.api_key_masked}</span></span>
                      )}
                    </label>
                    {snapshot?.gemini?.api_key_masked && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 shrink-0 text-[var(--color-accent-red)] hover:text-[var(--color-accent-red)]"
                        onClick={() => clearProviderKey("gemini")}
                        disabled={clearing !== null || saving}
                        aria-label="清空 Gemini API Key"
                      >
                        {clearing === "gemini"
                          ? <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                          : <Trash2 className="h-3.5 w-3.5 mr-1" />}
                        清空
                      </Button>
                    )}
                  </div>
                  <Input
                    type={showKeys ? "text" : "password"}
                    placeholder="留空保留现有密钥（清空请用右上按钮）"
                    value={geminiKey}
                    onChange={(e) => setGeminiKey(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">模型</label>
                  <Input
                    placeholder="gemini-2.5-flash"
                    value={geminiModel}
                    onChange={(e) => setGeminiModel(e.target.value)}
                  />
                </div>
              </div>
            </div>

            {/* Qwen */}
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="text-sm font-semibold truncate">Qwen (通义千问)</div>
                <Switch className="shrink-0" checked={qwenEnabled} onCheckedChange={setQwenEnabled} />
              </div>
              <div className="grid gap-3 sm:grid-cols-2 grid-collapse-mobile">
                <div className="space-y-1.5 min-w-0">
                  <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
                    <label className="text-xs text-muted-foreground min-w-0 flex-1 truncate">
                      API Key {snapshot?.qwen?.api_key_masked && (
                        <span className="ml-2 font-mono">已配置 <span className="text-safe inline-block max-w-[12rem] align-bottom">{snapshot.qwen.api_key_masked}</span></span>
                      )}
                    </label>
                    {snapshot?.qwen?.api_key_masked && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 shrink-0 text-[var(--color-accent-red)] hover:text-[var(--color-accent-red)]"
                        onClick={() => clearProviderKey("qwen")}
                        disabled={clearing !== null || saving}
                        aria-label="清空 Qwen API Key"
                      >
                        {clearing === "qwen"
                          ? <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                          : <Trash2 className="h-3.5 w-3.5 mr-1" />}
                        清空
                      </Button>
                    )}
                  </div>
                  <Input
                    type={showKeys ? "text" : "password"}
                    placeholder="sk-...（留空保留现有，清空请用右上按钮）"
                    value={qwenKey}
                    onChange={(e) => setQwenKey(e.target.value)}
                    disabled={!qwenEnabled}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">模型</label>
                  <Input
                    placeholder="qwen-plus"
                    value={qwenModel}
                    onChange={(e) => setQwenModel(e.target.value)}
                    disabled={!qwenEnabled}
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs text-muted-foreground">Base URL</label>
                  <Input
                    placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                    value={qwenBaseUrl}
                    onChange={(e) => setQwenBaseUrl(e.target.value)}
                    disabled={!qwenEnabled}
                  />
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* OpenRouter 聚合层（v1.0 — llm-openrouter） */}
      <Card id="openrouter">
        <CardHeader>
          <div className="mobile-card-header">
            <div className="mc-title min-w-0">
              <CardTitle>OpenRouter (聚合层)</CardTitle>
              <CardDescription className="break-words">
                一个 key 解锁 100+ 模型；可在 Header 模型菜单中切换 deep / quick 预设。
                设置 OPENROUTER_API_KEY 环境变量可在云部署中自动启用（覆盖 yaml）。
              </CardDescription>
            </div>
            <div className="mc-actions">
              <Switch
                className="shrink-0"
                checked={orEnabled}
                onCheckedChange={setOrEnabled}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-5">
            {/* API key + base config row */}
            <div className="grid gap-3 sm:grid-cols-2 grid-collapse-mobile">
              <div className="space-y-1.5 min-w-0">
                <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
                  <label className="text-xs text-muted-foreground min-w-0 flex-1 truncate">
                    API Key {snapshot?.openrouter?.api_key_masked && (
                      <span className="ml-2 font-mono">已配置 <span className="text-safe inline-block max-w-[12rem] align-bottom">{snapshot.openrouter.api_key_masked}</span></span>
                    )}
                  </label>
                  {snapshot?.openrouter?.api_key_masked && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 shrink-0 text-[var(--color-accent-red)] hover:text-[var(--color-accent-red)]"
                      onClick={() => clearProviderKey("openrouter")}
                      disabled={clearing !== null || saving}
                      aria-label="清空 OpenRouter API Key"
                    >
                      {clearing === "openrouter"
                        ? <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        : <Trash2 className="h-3.5 w-3.5 mr-1" />}
                      清空
                    </Button>
                  )}
                </div>
                <Input
                  type={showKeys ? "text" : "password"}
                  placeholder="sk-or-v1-...（或设 OPENROUTER_API_KEY 环境变量）"
                  value={orKey}
                  onChange={(e) => setOrKey(e.target.value)}
                  disabled={!orEnabled && !snapshot?.openrouter?.active}
                />
              </div>
              <div className="space-y-1.5 min-w-0">
                <label className="text-xs text-muted-foreground">Base URL</label>
                <Input
                  placeholder="https://openrouter.ai/api/v1"
                  value={orBaseUrl}
                  onChange={(e) => setOrBaseUrl(e.target.value)}
                />
              </div>
              <div className="space-y-1.5 min-w-0">
                <label className="text-xs text-muted-foreground">HTTP-Referer (用于 OR 仪表盘归因)</label>
                <Input
                  placeholder="https://stockai.example.com"
                  value={orReferer}
                  onChange={(e) => setOrReferer(e.target.value)}
                />
              </div>
              <div className="space-y-1.5 min-w-0">
                <label className="text-xs text-muted-foreground">X-Title</label>
                <Input
                  placeholder="StockAI Terminal"
                  value={orTitle}
                  onChange={(e) => setOrTitle(e.target.value)}
                />
              </div>
              <div className="space-y-1.5 min-w-0">
                <label className="text-xs text-muted-foreground">Timeout (秒)</label>
                <Input
                  type="number"
                  min={30}
                  max={600}
                  placeholder="120"
                  value={orTimeout}
                  onChange={(e) => setOrTimeout(Number(e.target.value) || 120)}
                />
              </div>
            </div>

            {/* Preset registry — read-only display. Active deep / quick
                marked with ★. Edits via Header LLMSwitcher (active swap)
                or yaml hand-edit (add/remove). v1.0 doesn't ship the
                'add preset' dialog — adding a preset requires editing
                ~/.stock_trading/config.yaml directly. Documented as a
                deferred v1.1 feature. */}
            <div className="space-y-2 min-w-0">
              <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
                <div className="text-sm font-semibold">
                  预设池 (presets) <span className="text-[10px] text-muted-foreground font-normal ml-1">只读 · v1.0</span>
                </div>
                <span className="text-xs text-muted-foreground shrink-0">
                  {snapshot?.openrouter?.presets?.length ?? 0} 个预设
                </span>
              </div>
              {(snapshot?.openrouter?.presets ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground py-3 text-center border border-dashed rounded">
                  暂无预设。请编辑 <code className="font-mono">~/.stock_trading/config.yaml</code> 添加，或保留默认 yaml 中的 3 条预设。
                </p>
              ) : (
                <div className="space-y-1.5">
                  {(snapshot?.openrouter?.presets ?? []).map(p => {
                    const isDeepActive  = p.id === snapshot?.openrouter?.active_pointers?.deep
                    const isQuickActive = p.id === snapshot?.openrouter?.active_pointers?.quick
                    const star = isDeepActive ? "★ deep" : isQuickActive ? "★ quick" : ""
                    return (
                      <div
                        key={p.id}
                        className="flex flex-wrap items-center gap-2 px-3 py-2 rounded border border-border/60 bg-card/30 min-w-0"
                      >
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted shrink-0 uppercase tracking-wider">
                          {p.role}
                        </span>
                        <span className="font-medium truncate min-w-0 flex-1">
                          {p.label}
                        </span>
                        <span className="text-xs font-mono text-muted-foreground text-safe text-safe--wrap min-w-0 hidden sm:inline">
                          {p.model}
                        </span>
                        {star && (
                          <span className="text-[10px] text-amber-400 shrink-0">{star}</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
              {/* v1.0.1 — explicit read-only scope so users don't keep
                  hunting for non-existent CRUD buttons. v1.1 roadmap
                  will add POST/DELETE /openrouter/presets endpoints +
                  add/edit/test-ping UI. */}
              <div className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 space-y-1 text-[11px]">
                <div className="text-amber-400 font-medium">
                  ⓘ 此区为只读视图（v1.0）
                </div>
                <div className="text-muted-foreground">
                  v1.0 只支持<b>切换</b>已有预设的 active deep / quick 指针（在右上角「模型」菜单中操作）。
                  <b>新增 / 编辑 / 删除</b>预设请编辑 <code className="font-mono">~/.stock_trading/config.yaml</code> 中
                  的 <code className="font-mono">openrouter.presets</code> 数组，重启服务后生效。
                </div>
                <div className="text-muted-foreground">
                  v1.1 路线：UI 编辑入口（添加预设 dialog / 测试 ping / 删除按钮）+ 后端
                  <code className="font-mono"> POST/DELETE /api/settings/openrouter/presets</code>。
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 通知 */}
      <Card>
        <CardHeader>
          <CardTitle>通知</CardTitle>
          <CardDescription>
            配置邮件 / Telegram 通知触发条件
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-5">
            {/* Email */}
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="text-sm font-semibold truncate">邮件</div>
                <Switch className="shrink-0" checked={emailEnabled} onCheckedChange={setEmailEnabled} />
              </div>
              <div className="grid gap-3 sm:grid-cols-2 grid-collapse-mobile">
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">收件邮箱</label>
                  <Input
                    type="email"
                    placeholder="your@email.com"
                    value={emailTo}
                    onChange={(e) => setEmailTo(e.target.value)}
                    disabled={!emailEnabled}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">SMTP Host</label>
                  <Input
                    placeholder="smtp.gmail.com"
                    value={emailSmtpHost}
                    onChange={(e) => setEmailSmtpHost(e.target.value)}
                    disabled={!emailEnabled}
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs text-muted-foreground">SMTP 用户名</label>
                  <Input
                    placeholder="user@smtp.example.com"
                    value={emailUsername}
                    onChange={(e) => setEmailUsername(e.target.value)}
                    disabled={!emailEnabled}
                  />
                </div>
              </div>
            </div>

            {/* Telegram */}
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="text-sm font-semibold truncate">Telegram</div>
                <Switch
                  className="shrink-0"
                  checked={telegramEnabled}
                  onCheckedChange={setTelegramEnabled}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs text-muted-foreground">Chat ID</label>
                <Input
                  placeholder="123456789"
                  value={telegramChatId}
                  onChange={(e) => setTelegramChatId(e.target.value)}
                  disabled={!telegramEnabled}
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <LoginMethodsSection />

      <SchedulerStatusCard />

      <OnboardingSection />
    </div>
  )
}

/**
 * "新手引导" section — single reset button hooked into
 * /api/onboarding/reset. After reset the user is invited to return
 * to the dashboard where the welcome modal re-fires.
 *
 * Spec: docs/design/onboarding.md §4.9.
 */
function OnboardingSection() {
  const { reset } = useOnboardingState()
  const [busy, setBusy] = useState(false)
  return (
    <Card>
      <CardHeader>
        <CardTitle>新手引导</CardTitle>
        <CardDescription>
          重新观看欢迎导览与 4 项上手任务清单（仅移动端可见）。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await reset()
              toast.success("已重置，回首页即可重新查看引导")
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? "重置中..." : "重新观看引导"}
        </Button>
      </CardContent>
    </Card>
  )
}

interface SchedulerStatusResponse {
  running: boolean
  jobs: { id: string; next_run_time: string | null; trigger: string }[]
  last_run: string | null
  primary?: boolean
  pid?: number | null
}

interface MeResponse {
  user?: { id: number; email: string; role?: string } | null
}

function SchedulerStatusCard() {
  const [status, setStatus] = useState<SchedulerStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [isAdmin, setIsAdmin] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const s = await apiGet<SchedulerStatusResponse>("/api/scheduler/status")
      setStatus(s)
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
    apiGet<MeResponse>("/api/auth/me")
      .then((r) => setIsAdmin(r.user?.role === "admin"))
      .catch(() => setIsAdmin(false))
  }, [reload])

  const handleRunNow = async () => {
    setRunning(true)
    setMsg(null)
    try {
      await apiPost("/api/scheduler/run-now")
      setMsg("✓ 已触发一次快照")
      await reload()
      setTimeout(() => setMsg(null), 3000)
    } catch (err: unknown) {
      setMsg(err instanceof Error ? `失败：${err.message}` : "失败")
      setTimeout(() => setMsg(null), 5000)
    } finally {
      setRunning(false)
    }
  }

  const dailyJob = status?.jobs?.find((j) => j.id === "daily_snapshot")

  return (
    <Card>
      <CardHeader>
        <div className="mobile-card-header">
          <div className="mc-title min-w-0">
            <CardTitle>调度器</CardTitle>
            <CardDescription className="break-words">每日 16:30 (America/New_York) 自动写入 daily_snapshots</CardDescription>
          </div>
          <Button variant="ghost" size="sm" className="mc-actions" onClick={reload} disabled={loading}>
            <RefreshCw className={`icon-fixed ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && !status ? (
          <Skeleton className="h-20" />
        ) : (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2 min-w-0">
              <span className="text-muted-foreground shrink-0">运行状态</span>
              {status?.running ? (
                <span className="text-[var(--color-accent-green)] shrink-0">✓ Running</span>
              ) : (
                <span className="text-[var(--color-accent-red)] shrink-0">✗ Stopped</span>
              )}
              {status?.primary && (
                <span className="text-xs text-muted-foreground text-safe text-safe--wrap min-w-0">(primary worker pid={status.pid})</span>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
              <div>
                <Clock className="inline h-3.5 w-3.5 mr-1 text-muted-foreground" />
                <span className="text-muted-foreground mr-2">上次快照</span>
                <span className="font-mono">{status?.last_run ?? "—"}</span>
              </div>
              <div>
                <Clock className="inline h-3.5 w-3.5 mr-1 text-muted-foreground" />
                <span className="text-muted-foreground mr-2">下次快照</span>
                <span className="font-mono">{dailyJob?.next_run_time ?? "—"}</span>
              </div>
            </div>
            {status?.jobs && status.jobs.length > 0 && (
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">已注册作业 ({status.jobs.length})</summary>
                <ul className="mt-1 space-y-1 font-mono">
                  {status.jobs.map((j) => (
                    <li key={j.id}>
                      <span className="text-foreground">{j.id}</span> · {j.trigger}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {isAdmin && (
              <div className="mobile-action-row pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRunNow}
                  disabled={running}
                >
                  {running ? (
                    <RefreshCw className="icon-fixed mr-1 animate-spin h-3.5 w-3.5" />
                  ) : (
                    <PlayCircle className="icon-fixed mr-1 h-3.5 w-3.5" />
                  )}
                  立即跑一次
                </Button>
                {msg && <span className="text-xs text-muted-foreground text-safe text-safe--wrap min-w-0 flex-1 sm:flex-none">{msg}</span>}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─── OAuth quick sign-in: linked-providers + link/unlink controls ─────
// Mirrors GET /api/auth/oauth/linked + the per-provider unlink endpoint.
// Always includes a "邮箱密码" row to make the placeholder password fact
// visible — matches the v1.0 backend invariant that every user has a
// fallback password_hash.

interface LinkedProviderRow {
  provider: string
  email: string | null
  email_verified: boolean
  linked_at: string
  last_login_at: string | null
}

interface LinkedProvidersResponse {
  providers: LinkedProviderRow[]
  has_password: boolean
}

interface AvailableProvider {
  name: string
  label: string
  icon: string
}

interface AvailableProvidersResponse {
  providers: AvailableProvider[]
}

const PROVIDER_LABELS: Record<string, string> = {
  google: "Google",
  github: "GitHub",
}

function formatProviderLabel(name: string): string {
  return PROVIDER_LABELS[name] ?? name
}

function LoginMethodsSection() {
  const [linked, setLinked] = useState<LinkedProvidersResponse | null>(null)
  const [available, setAvailable] = useState<AvailableProvider[]>([])
  const [busyProvider, setBusyProvider] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const [l, a] = await Promise.all([
        apiGet<LinkedProvidersResponse>("/api/auth/oauth/linked"),
        apiGet<AvailableProvidersResponse>("/api/auth/providers"),
      ])
      setLinked(l)
      setAvailable(a.providers ?? [])
    } catch {
      // 401 or network failure → keep section hidden by leaving linked=null.
      setLinked(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const unlink = useCallback(async (provider: string) => {
    if (!window.confirm(`确定解绑 ${formatProviderLabel(provider)}?`)) return
    setBusyProvider(provider)
    try {
      await apiPost(`/api/auth/oauth/${encodeURIComponent(provider)}/unlink`, {})
      await refresh()
      toast.success(`已解绑 ${formatProviderLabel(provider)}`)
    } catch (err: unknown) {
      if (err instanceof ApiError && (err.body as { error?: string })?.error === "last_method") {
        toast.error("不能解绑：这是您唯一的登录方式")
      } else {
        toast.error("解绑失败")
      }
    } finally {
      setBusyProvider(null)
    }
  }, [refresh])

  if (loading) {
    return null
  }
  if (linked === null) {
    // /api/auth/oauth/linked failed (likely 401) — section hidden.
    return null
  }

  const linkedNames = new Set(linked.providers.map((p) => p.provider))
  const unlinkedAvailable = available.filter((p) => !linkedNames.has(p.name))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="h-4 w-4" /> 登录方式
        </CardTitle>
        <CardDescription>
          已绑定的登录方式可独立用于下次登录；至少保留一种以避免锁死账号。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-1.5">
        <div className="flex items-center justify-between text-sm py-1.5 px-1">
          <span className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            邮箱密码
          </span>
          <span className="text-xs text-muted-foreground">默认</span>
        </div>

        {linked.providers.map((p) => (
          <div
            key={p.provider}
            className="flex items-center justify-between text-sm py-1.5 px-1"
          >
            <span className="flex items-center gap-2 min-w-0">
              <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
              <span className="truncate">
                {formatProviderLabel(p.provider)}
                {p.email ? ` · ${p.email}` : ""}
              </span>
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="text-[var(--color-accent-red)] hover:text-[var(--color-accent-red)]"
              disabled={busyProvider !== null}
              onClick={() => unlink(p.provider)}
              aria-label={`解绑 ${formatProviderLabel(p.provider)}`}
            >
              {busyProvider === p.provider ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              ) : (
                "解绑"
              )}
            </Button>
          </div>
        ))}

        {unlinkedAvailable.map((p) => (
          <a
            key={p.name}
            href={`/auth/oauth/${encodeURIComponent(p.name)}/start?intent=link&next=/settings`}
            className="flex items-center justify-between text-sm py-1.5 px-1 rounded hover:bg-accent transition-colors"
          >
            <span className="flex items-center gap-2 text-muted-foreground">
              <Link2 className="h-4 w-4" />
              关联 {p.label}
            </span>
            <span className="text-xs text-[var(--color-accent-blue)]">前往</span>
          </a>
        ))}
      </CardContent>
    </Card>
  )
}
