import { useEffect, useState } from "react"
import { History, Search, ChevronDown, ChevronRight, TrendingUp } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

interface AnalysisRecord {
  id: string
  ticker: string
  signal: string
  date: string
  created_at: string
  summary?: string
  confidence?: number
  analysts?: Record<string, unknown>
}

function signalVariant(signal: string): "buy" | "sell" | "hold" | "default" {
  const s = signal?.toLowerCase() ?? ""
  if (s.includes("buy") || s.includes("bullish")) return "buy"
  if (s.includes("sell") || s.includes("bearish")) return "sell"
  if (s.includes("hold") || s.includes("neutral")) return "hold"
  return "default"
}

export function HistoryPage() {
  const [records, setRecords] = useState<AnalysisRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    apiGet<AnalysisRecord[] | { records: AnalysisRecord[] }>("/api/history")
      .then((res) => {
        const list = Array.isArray(res) ? res : res.records ?? []
        setRecords(list)
      })
      .catch((err) => setError(err.message ?? "Failed to load history"))
      .finally(() => setLoading(false))
  }, [])

  const filtered = search
    ? records.filter((r) =>
        r.ticker.toLowerCase().includes(search.toLowerCase()),
      )
    : records

  if (loading) {
    return (
      <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-10 w-full max-w-xs" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 md:p-6 max-w-5xl mx-auto">
        <Alert variant="destructive">
          <AlertTitle>加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <History className="h-5 w-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">分析历史</h1>
        <Badge variant="muted" className="ml-auto">
          {records.length} 条记录
        </Badge>
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          placeholder="按股票代码搜索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      <Card>
        <CardContent className="pt-4">
          {filtered.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {records.length === 0
                ? "暂无分析记录，前往「分析」页面开始"
                : "无匹配结果"}
            </div>
          ) : (
            <div className="divide-y divide-border/50">
              {filtered.map((r) => {
                const isExpanded = expandedId === r.id
                return (
                  <div key={r.id}>
                    <button
                      type="button"
                      className="w-full flex items-center gap-3 py-3 px-2 text-left hover:bg-muted/30 transition-colors rounded"
                      onClick={() =>
                        setExpandedId(isExpanded ? null : r.id)
                      }
                    >
                      {isExpanded ? (
                        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                      <span className="font-mono font-semibold min-w-[5rem]">
                        {r.ticker}
                      </span>
                      <Badge variant={signalVariant(r.signal)}>
                        {r.signal || "N/A"}
                      </Badge>
                      {r.confidence != null && (
                        <span className="text-xs text-muted-foreground">
                          {(r.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                      <span className="ml-auto text-xs text-muted-foreground whitespace-nowrap">
                        {r.date || r.created_at?.slice(0, 10)}
                      </span>
                    </button>

                    {isExpanded && (
                      <div className="pl-11 pr-2 pb-4 space-y-2">
                        {r.summary && (
                          <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
                            {r.summary}
                          </p>
                        )}
                        {r.analysts && (
                          <pre className="text-xs bg-[var(--color-bg-secondary)] rounded p-3 overflow-x-auto max-h-60">
                            {JSON.stringify(r.analysts, null, 2)}
                          </pre>
                        )}
                        <a
                          href={`/app/analysis/${r.id}`}
                          className="inline-flex items-center gap-1 text-xs text-[var(--color-accent-blue)] hover:underline"
                        >
                          <TrendingUp className="h-3 w-3" />
                          查看完整分析
                        </a>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
