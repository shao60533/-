import { useEffect, useState } from "react"
import { Bell, Plus, Trash2, History as HistoryIcon, Zap } from "lucide-react"
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
import { Chip, ChipRow } from "@/components/ui/chip"
import { apiGet, apiPost, apiDel } from "@/lib/api"

const ALERT_TEMPLATES = [
  { label: "向上突破+5%", condition: "pct_change_above", threshold: 5 },
  { label: "向下跌破-5%", condition: "pct_change_below", threshold: 5 },
  { label: "止损-10%", condition: "pct_change_below", threshold: 10 },
  { label: "止盈+20%", condition: "pct_change_above", threshold: 20 },
  { label: "日内涨跌±3%", condition: "pct_change_above", threshold: 3 },
] as const

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
  const [prefillCondition, setPrefillCondition] = useState("")
  const [prefillThreshold, setPrefillThreshold] = useState("")

  const handleTemplate = (tpl: typeof ALERT_TEMPLATES[number]) => {
    setPrefillCondition(tpl.condition)
    setPrefillThreshold(String(tpl.threshold))
    setAddOpen(true)
  }

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
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6 min-w-0">
      <div className="mobile-card-header">
        <div className="mc-title flex items-center gap-3 min-w-0">
          <Bell className="icon-fixed h-5 w-5 text-[var(--color-accent-yellow)]" />
          <h1 className="text-xl font-bold truncate">警报管理</h1>
        </div>
        <Button size="sm" onClick={() => setAddOpen(true)} className="mc-actions">
          <Plus className="icon-fixed mr-1" /> 新建警报
        </Button>
      </div>

      <ChipRow>
        {ALERT_TEMPLATES.map((tpl) => (
          <Chip
            key={tpl.label}
            size="sm"
            onClick={() => handleTemplate(tpl)}
          >
            <Zap className="h-3 w-3" />
            {tpl.label}
          </Chip>
        ))}
      </ChipRow>

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
                    // v1.6: mobile two-line layout. Outer wraps so on
                    // 320px the date + delete button drop to row 2 inside
                    // ``mobile-action-row`` instead of squeezing the
                    // ticker/condition column to 0px.
                    <div
                      key={a.id}
                      className="flex flex-wrap items-center gap-2 py-3 px-2 min-w-0"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono font-semibold">
                            {a.ticker}
                          </span>
                          <Badge
                            variant={a.enabled ? "success" : "muted"}
                          >
                            {a.enabled ? "启用" : "禁用"}
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground mt-0.5 break-words">
                          {a.condition} {a.threshold}
                        </p>
                      </div>
                      <div className="mobile-action-row sm:ml-auto items-center gap-2">
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
                    <div key={t.id} className="py-3 px-2 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 min-w-0">
                        <HistoryIcon className="icon-fixed text-muted-foreground" />
                        <span className="font-mono font-semibold text-sm shrink-0">
                          {t.ticker}
                        </span>
                        <Badge variant="default" className="shrink-0 max-w-full whitespace-normal text-left leading-snug">{t.condition}</Badge>
                        <span className="text-xs text-muted-foreground sm:ml-auto shrink-0">
                          {t.triggered_at?.slice(0, 19).replace("T", " ")}
                        </span>
                      </div>
                      {t.message && (
                        <p className="text-sm text-muted-foreground mt-1 pl-6 break-words">
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
        onClose={() => {
          setAddOpen(false)
          setPrefillCondition("")
          setPrefillThreshold("")
        }}
        onSuccess={load}
        initialCondition={prefillCondition}
        initialThreshold={prefillThreshold}
      />
    </div>
  )
}

function AddAlertDialog({
  open,
  onClose,
  onSuccess,
  initialCondition,
  initialThreshold,
}: {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  initialCondition?: string
  initialThreshold?: string
}) {
  const [ticker, setTicker] = useState("")
  const [condition, setCondition] = useState("price_above")
  const [threshold, setThreshold] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setCondition(initialCondition || "price_above")
      setThreshold(initialThreshold || "")
      setTicker("")
      setFormError(null)
    }
  }, [open, initialCondition, initialThreshold])

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
