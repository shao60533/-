import { useEffect, useState } from "react"
import { Settings, Save, RefreshCw, Eye, EyeOff } from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiGet, apiPost } from "@/lib/api"

interface SystemSettings {
  provider?: string
  model?: string
  api_keys?: Record<string, string>
  alerts?: AlertSettings
  [key: string]: unknown
}

interface AlertSettings {
  enabled?: boolean
  email?: string
  webhook_url?: string
  check_interval?: number
}

const LLM_PROVIDERS = [
  { value: "qwen", label: "Qwen (通义千问)" },
  { value: "gemini", label: "Gemini" },
] as const

export function SettingsPage() {
  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [showKeys, setShowKeys] = useState(false)

  const [provider, setProvider] = useState("")
  const [model, setModel] = useState("")
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({})
  const [alertsEnabled, setAlertsEnabled] = useState(false)
  const [alertEmail, setAlertEmail] = useState("")
  const [webhookUrl, setWebhookUrl] = useState("")
  const [checkInterval, setCheckInterval] = useState("300")

  useEffect(() => {
    setLoading(true)
    setError(null)
    apiGet<SystemSettings>("/api/settings")
      .then((res) => {
        setSettings(res)
        setProvider(res.provider ?? "openai")
        setModel(res.model ?? "")
        setApiKeys(res.api_keys ?? {})
        setAlertsEnabled(res.alerts?.enabled ?? false)
        setAlertEmail(res.alerts?.email ?? "")
        setWebhookUrl(res.alerts?.webhook_url ?? "")
        setCheckInterval(String(res.alerts?.check_interval ?? 300))
      })
      .catch((err) =>
        setError(err.message ?? "Failed to load settings"),
      )
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg(null)
    setError(null)
    try {
      await apiPost("/api/settings", {
        provider,
        model,
        api_keys: apiKeys,
        alerts: {
          enabled: alertsEnabled,
          email: alertEmail,
          webhook_url: webhookUrl,
          check_interval: parseInt(checkInterval, 10) || 300,
        },
      })
      setSaveMsg("设置已保存")
      setTimeout(() => setSaveMsg(null), 3000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const updateApiKey = (key: string, value: string): void => {
    setApiKeys({ ...apiKeys, [key]: value })
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

  if (error && !settings) {
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
      {error && settings && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Provider Config */}
      <Card>
        <CardHeader>
          <CardTitle>LLM 提供商</CardTitle>
          <CardDescription>
            选择 AI 模型提供商及模型名称
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 grid-collapse-mobile">
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">提供商</label>
              <Select value={provider} onValueChange={setProvider}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LLM_PROVIDERS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">模型名称</label>
              <Input
                placeholder="如 gpt-4o, claude-sonnet-4-20250514"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>API 密钥</CardTitle>
              <CardDescription>
                配置各服务的 API 密钥
              </CardDescription>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowKeys(!showKeys)}
            >
              {showKeys ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[
              { key: "OPENAI_API_KEY",     label: "OpenAI API Key" },
              { key: "ANTHROPIC_API_KEY",  label: "Anthropic API Key" },
              { key: "DEEPSEEK_API_KEY",   label: "DeepSeek API Key" },
              { key: "DASHSCOPE_API_KEY",  label: "Qwen API Key (DashScope)" },
              { key: "GEMINI_API_KEY",     label: "Gemini API Key" },
              { key: "QWEN_API_KEY",       label: "Qwen API Key (备用)" },
            ].map(({ key: keyName, label }) => (
                <div key={keyName} className="space-y-1.5">
                  <label className="text-xs font-mono text-muted-foreground">
                    {label}
                  </label>
                  <Input
                    type={showKeys ? "text" : "password"}
                    placeholder="sk-..."
                    value={apiKeys[keyName] ?? ""}
                    onChange={(e) => updateApiKey(keyName, e.target.value)}
                  />
                </div>
              ),
            )}
          </div>
        </CardContent>
      </Card>

      {/* Alerts Config */}
      <Card>
        <CardHeader>
          <CardTitle>警报配置</CardTitle>
          <CardDescription>
            配置警报通知方式和检查间隔
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <label className="text-sm">启用警报</label>
              <Switch
                checked={alertsEnabled}
                onCheckedChange={setAlertsEnabled}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">
                通知邮箱
              </label>
              <Input
                type="email"
                placeholder="your@email.com"
                value={alertEmail}
                onChange={(e) => setAlertEmail(e.target.value)}
                disabled={!alertsEnabled}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">
                Webhook URL
              </label>
              <Input
                placeholder="https://hooks.example.com/..."
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                disabled={!alertsEnabled}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">
                检查间隔 (秒)
              </label>
              <Input
                type="number"
                min="60"
                step="60"
                value={checkInterval}
                onChange={(e) => setCheckInterval(e.target.value)}
                disabled={!alertsEnabled}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
