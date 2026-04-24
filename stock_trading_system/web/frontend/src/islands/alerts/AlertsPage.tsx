import { useEffect, useState } from "react"
import { Bell, Plus, Trash2, History as HistoryIcon } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { apiGet, apiPost, apiDel } from "@/lib/api"

interface AlertRule {
  id: string
  ticker: string
  condition: string
  threshold: number
  enabled: boolean
  created_at: string
}

interface AlertTrigger {
  id: string
  alert_id: string
  ticker: string
  condition: string
  triggered_at: string
  message: string
}

export function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertRule[]>([])
  const [triggers, setTriggers] = useState<AlertTrigger[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [a, h] = await Promise.all([
        apiGet<AlertRule[] | { alerts: AlertRule[] }>("/api/alerts").catch(
          () => [],
        ),
        apiGet<AlertTrigger[] | { history: AlertTrigger[] }>(
          "/api/alerts/history",
        ).catch(() => []),
      ])
      setAlerts(Array.isArray(a) ? a : (a as { alerts: AlertRule[] }).alerts ?? [])
      setTriggers(
        Array.isArray(h) ? h : (h as { history: AlertTrigger[] }).history ?? [],
      )
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load alerts")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleDelete = async (id: string) => {
    if (!confirm("确定删除该警报？")) return
    try {
      await apiDel(`/api/alerts/${id}`)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "删除失败")
    }
  }

  if (loading) {
    return (
      <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 md:grid-cols-2">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
        <Alert variant="destructive">
          <AlertTitle>错误</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={load}>
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bell className="h-5 w-5 text-[var(--color-accent-yellow)]" />
          <h1 className="text-xl font-bold">警报管理</h1>
        </div>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="w-4 h-4 mr-1" /> 新建警报
        </Button>
      </div>

      <Tabs defaultValue="active">
        <TabsList>
          <TabsTrigger value="active">
            活跃警报 ({alerts.length})
          </TabsTrigger>
          <TabsTrigger value="history">
            触发历史 ({triggers.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="active">
          <Card>
            <CardContent className="pt-4">
              {alerts.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  暂无活跃警报，点击「新建警报」开始
                </div>
              ) : (
                <div className="divide-y divide-border/50">
                  {alerts.map((a) => (
                    <div
                      key={a.id}
                      className="flex items-center gap-3 py-3 px-2"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-semibold">
                            {a.ticker}
                          </span>
                          <Badge
                            variant={a.enabled ? "success" : "muted"}
                          >
                            {a.enabled ? "启用" : "禁用"}
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground mt-0.5">
                          {a.condition} {a.threshold}
                        </p>
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {a.created_at?.slice(0, 10)}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-500 shrink-0"
                        onClick={() => handleDelete(a.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history">
          <Card>
            <CardContent className="pt-4">
              {triggers.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  暂无触发历史
                </div>
              ) : (
                <div className="divide-y divide-border/50">
                  {triggers.map((t) => (
                    <div key={t.id} className="py-3 px-2">
                      <div className="flex items-center gap-2">
                        <HistoryIcon className="h-4 w-4 text-muted-foreground" />
                        <span className="font-mono font-semibold text-sm">
                          {t.ticker}
                        </span>
                        <Badge variant="default">{t.condition}</Badge>
                        <span className="ml-auto text-xs text-muted-foreground">
                          {t.triggered_at?.slice(0, 19).replace("T", " ")}
                        </span>
                      </div>
                      {t.message && (
                        <p className="text-sm text-muted-foreground mt-1 pl-6">
                          {t.message}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <AddAlertDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSuccess={load}
      />
    </div>
  )
}

function AddAlertDialog({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [ticker, setTicker] = useState("")
  const [condition, setCondition] = useState("price_above")
  const [threshold, setThreshold] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!ticker || !threshold) return
    setSubmitting(true)
    setFormError(null)
    try {
      await apiPost("/api/alerts", {
        ticker: ticker.toUpperCase(),
        condition,
        threshold: parseFloat(threshold),
      })
      onSuccess()
      onClose()
      setTicker("")
      setThreshold("")
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "创建失败")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建警报</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Input
            placeholder="股票代码 (如 AAPL)"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
          />
          <Select value={condition} onValueChange={setCondition}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="price_above">价格高于</SelectItem>
              <SelectItem value="price_below">价格低于</SelectItem>
              <SelectItem value="volume_above">成交量高于</SelectItem>
              <SelectItem value="pct_change_above">涨幅超过 (%)</SelectItem>
              <SelectItem value="pct_change_below">跌幅超过 (%)</SelectItem>
            </SelectContent>
          </Select>
          <Input
            type="number"
            step="0.01"
            placeholder="阈值"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
          {formError && (
            <Alert variant="destructive">
              <AlertDescription>{formError}</AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? "创建中..." : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
