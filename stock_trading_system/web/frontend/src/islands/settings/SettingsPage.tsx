import { useEffect, useState } from "react"
import { Settings, Save, RefreshCw, Eye, EyeOff } from "lucide-react"
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

  useEffect(() => {
    setLoading(true)
    setError(null)
    apiGet<SettingsResponse>("/api/settings")
      .then((res) => {
        setSnapshot(res)
        setGeminiModel(res.gemini?.model ?? "")
        setQwenEnabled(Boolean(res.qwen?.enabled))
        setQwenModel(res.qwen?.model ?? "")
        setQwenBaseUrl(res.qwen?.base_url ?? "")
        setEmailTo(res.email?.to_address ?? "")
        setEmailSmtpHost(res.email?.smtp_host ?? "")
        setEmailUsername(res.email?.username ?? "")
        setTelegramChatId(res.telegram?.chat_id ?? "")
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load settings"),
      )
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg(null)
    setError(null)
    // Only emit dotted-path keys the backend whitelists. Empty strings are
    // intentional — they let the user clear a bad credential.
    const payload: DottedSettingsPayload = {
      "gemini.api_key": geminiKey,
      "gemini.model": geminiModel,
      "qwen.enabled": qwenEnabled,
      "qwen.api_key": qwenKey,
      "qwen.model": qwenModel,
      "qwen.base_url": qwenBaseUrl,
      "alerts.email.enabled": emailEnabled,
      "alerts.email.to_address": emailTo,
      "alerts.email.smtp_host": emailSmtpHost,
      "alerts.email.username": emailUsername,
      "alerts.telegram.enabled": telegramEnabled,
      "alerts.telegram.chat_id": telegramChatId,
    }
    // Drop unset secrets so we don't overwrite a stored key with empty string
    // unless the user explicitly typed something. (api_key fields specifically
    // — model/base_url remain even when blank because the user may want to
    // reset to defaults.)
    if (!geminiKey) delete payload["gemini.api_key"]
    if (!qwenKey) delete payload["qwen.api_key"]
    try {
      await apiPost("/api/settings", payload)
      setSaveMsg("设置已保存")
      setGeminiKey("")
      setQwenKey("")
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
                  <label className="text-xs text-muted-foreground">
                    API Key {snapshot?.gemini?.api_key_masked && (
                      <span className="ml-2 font-mono">已配置 {snapshot.gemini.api_key_masked}</span>
                    )}
                  </label>
                  <Input
                    type={showKeys ? "text" : "password"}
                    placeholder="留空保留现有密钥"
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
                  <label className="text-xs text-muted-foreground">
                    API Key {snapshot?.qwen?.api_key_masked && (
                      <span className="ml-2 font-mono">已配置 {snapshot.qwen.api_key_masked}</span>
                    )}
                  </label>
                  <Input
                    type={showKeys ? "text" : "password"}
                    placeholder="sk-..."
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
    </div>
  )
}
