import { useCallback, useEffect, useState } from "react"
import { Settings, Save, RefreshCw, Eye, EyeOff, Trash2, Clock, PlayCircle } from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Switch } from "@/components/ui/switch"
import { apiGet, apiPost } from "@/lib/api"

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
  const [clearing, setClearing] = useState<"gemini" | "qwen" | null>(null)

  // ── LLM section ────────────────────────────────────────────────────────
  const [geminiKey, setGeminiKey] = useState("")
  const [geminiModel, setGeminiModel] = useState("")
  const [qwenEnabled, setQwenEnabled] = useState(false)
  const [qwenKey, setQwenKey] = useState("")
  const [qwenModel, setQwenModel] = useState("")
  const [qwenBaseUrl, setQwenBaseUrl] = useState("")

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

  const clearProviderKey = async (provider: "gemini" | "qwen") => {
    const masked = provider === "gemini"
      ? snapshot?.gemini?.api_key_masked
      : snapshot?.qwen?.api_key_masked
    if (!masked) return  // nothing to clear
    const label = provider === "gemini" ? "Gemini" : "Qwen"
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
      "alerts.email.enabled": emailEnabled,
      "alerts.email.to_address": emailTo,
      "alerts.email.smtp_host": emailSmtpHost,
      "alerts.email.username": emailUsername,
      "alerts.telegram.enabled": telegramEnabled,
      "alerts.telegram.chat_id": telegramChatId,
    }
    if (geminiKey) payload["gemini.api_key"] = geminiKey
    if (qwenKey) payload["qwen.api_key"] = qwenKey
    try {
      await apiPost("/api/settings", payload)
      setSaveMsg("设置已保存")
      setGeminiKey("")
      setQwenKey("")
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
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Settings className="h-5 w-5 text-[var(--color-accent-blue)]" />
          <h1 className="text-xl font-bold">系统设置</h1>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? (
            <>
              <RefreshCw className="h-4 w-4 mr-1 animate-spin" />
              保存中...
            </>
          ) : (
            <>
              <Save className="h-4 w-4 mr-1" />
              保存设置
            </>
          )}
        </Button>
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
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>AI 模型</CardTitle>
              <CardDescription>
                配置 Gemini 与 Qwen API 密钥及模型
              </CardDescription>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowKeys(!showKeys)}
            >
              {showKeys ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-5">
            {/* Gemini */}
            <div className="space-y-3">
              <div className="text-sm font-semibold">Gemini</div>
              <div className="grid gap-3 sm:grid-cols-2 grid-collapse-mobile">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-xs text-muted-foreground">
                      API Key {snapshot?.gemini?.api_key_masked && (
                        <span className="ml-2 font-mono">已配置 {snapshot.gemini.api_key_masked}</span>
                      )}
                    </label>
                    {snapshot?.gemini?.api_key_masked && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-[var(--color-accent-red)] hover:text-[var(--color-accent-red)]"
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
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">Qwen (通义千问)</div>
                <Switch checked={qwenEnabled} onCheckedChange={setQwenEnabled} />
              </div>
              <div className="grid gap-3 sm:grid-cols-2 grid-collapse-mobile">
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-xs text-muted-foreground">
                      API Key {snapshot?.qwen?.api_key_masked && (
                        <span className="ml-2 font-mono">已配置 {snapshot.qwen.api_key_masked}</span>
                      )}
                    </label>
                    {snapshot?.qwen?.api_key_masked && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-[var(--color-accent-red)] hover:text-[var(--color-accent-red)]"
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
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">邮件</div>
                <Switch checked={emailEnabled} onCheckedChange={setEmailEnabled} />
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
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">Telegram</div>
                <Switch
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

      <SchedulerStatusCard />
    </div>
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
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>调度器</CardTitle>
            <CardDescription>每日 16:30 (America/New_York) 自动写入 daily_snapshots</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={reload} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && !status ? (
          <Skeleton className="h-20" />
        ) : (
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">运行状态</span>
              {status?.running ? (
                <span className="text-[var(--color-accent-green)]">✓ Running</span>
              ) : (
                <span className="text-[var(--color-accent-red)]">✗ Stopped</span>
              )}
              {status?.primary && (
                <span className="text-xs text-muted-foreground">(primary worker pid={status.pid})</span>
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
              <div className="flex items-center gap-3 pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRunNow}
                  disabled={running}
                >
                  {running ? (
                    <RefreshCw className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <PlayCircle className="h-3.5 w-3.5 mr-1" />
                  )}
                  立即跑一次
                </Button>
                {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
