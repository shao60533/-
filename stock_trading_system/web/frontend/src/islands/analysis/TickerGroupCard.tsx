/**
 * analysis-inbox-group-by-ticker v1.0 — group card.
 *
 * Renders ONE ticker's collapsed analysis history with:
 *   - latest signal + drift summary across the visible history
 *   - per-record counter + provider / model / depth hint
 *   - primary CTA "打开最新分析" linking to /analysis/<latest_id>
 *   - expand → list every analysis row in chronological order
 *     (newest-first), each row a deep link to /analysis/<id>.
 *
 * On expand the card lazily fetches /api/history/timeline/<ticker>?limit=20
 * to surface records that aren't in the inbox window. Fetch failures
 * are scoped to this card — the inline error never bubbles.
 */
import { useEffect, useState } from "react"
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  ExternalLink,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

import { signalLabel, signalVariant } from "./AnalysisPage"
import {
  summarizeSignalDrift,
  type CompletedAnalysisRow,
  type TickerGroup,
} from "./groupAnalysisRowsByTicker"

interface TickerGroupCardProps {
  group: TickerGroup
}

interface TimelineEnvelope {
  ticker: string
  count: number
  records: TimelineRecord[]
}

/** Minimal subset of /api/history/timeline/<ticker> we render — full
 *  record carries the full structured analysis body but the list view
 *  only needs identity + signal + when. */
interface TimelineRecord {
  id: number
  ticker: string
  signal: string | null
  date: string | null
  created_at: string | null
}

function depthLabel(d: string | null | undefined): string {
  switch ((d || "").toLowerCase()) {
    case "deep": return "深度"
    case "standard": return "标准"
    case "quick": return "标准"  // legacy alias — see AnalysisPage.depthLabel
    default: return "标准"
  }
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return ""
  const t = Date.parse(iso.replace(" ", "T") + "Z")
  if (Number.isNaN(t)) return ""
  const dt = Date.now() - t
  if (dt < 60_000) return "刚刚"
  if (dt < 3_600_000) return `${Math.floor(dt / 60_000)} 分钟前`
  if (dt < 86_400_000) return `${Math.floor(dt / 3_600_000)} 小时前`
  return new Date(t).toLocaleDateString("zh-CN")
}

export function TickerGroupCard({ group }: TickerGroupCardProps) {
  const [open, setOpen] = useState(false)
  const [timeline, setTimeline] = useState<TimelineRecord[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { ticker, latestRow, count, rows } = group
  const drift = summarizeSignalDrift(rows)

  // Lazy fetch on first expand. Falls back silently to the inbox-known
  // ``rows`` if the network call fails.
  useEffect(() => {
    if (!open || timeline !== null || loading) return
    let cancelled = false
    setLoading(true)
    setError(null)
    apiGet<TimelineEnvelope>(
      `/api/history/timeline/${encodeURIComponent(ticker)}?limit=20`,
    )
      .then(data => {
        if (cancelled) return
        setTimeline(Array.isArray(data?.records) ? data.records : [])
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message =
          err instanceof Error && err.message ? err.message : "加载失败"
        setError(message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, ticker, timeline, loading])

  const historyRows: Array<
    TimelineRecord | CompletedAnalysisRow
  > = timeline ?? rows

  return (
    <Card
      data-ticker-group={ticker}
      data-expanded={open ? "true" : undefined}
      className="overflow-hidden border-border/60"
    >
      {/* Row A — header (always visible). Tap toggles expansion; the
           主 CTA anchor below sits outside the button so click-bubbling
           to /analysis/<id> never accidentally collapses the card. */}
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
        className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-accent/30 transition-colors min-w-0"
      >
        {open
          ? <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
          : <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />}
        <span className="font-mono font-semibold text-sm truncate">{ticker}</span>
        <Badge
          variant={signalVariant(latestRow.signal || "")}
          className="text-[10px] shrink-0"
        >
          {signalLabel(latestRow.signal)}
        </Badge>
        <span className="ml-auto text-[11px] text-muted-foreground shrink-0">
          共 {count} 次
        </span>
      </button>

      <CardContent className="pt-0 pb-3 px-3 space-y-2">
        {/* Row B — meta line: 最近一次 date + provider / model + drift. */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
          <span>{fmtRelative(latestRow.created_at)}</span>
          <span aria-hidden>·</span>
          <span>{depthLabel(latestRow.depth)}</span>
          {latestRow.provider && (
            <>
              <span aria-hidden>·</span>
              <span className="truncate max-w-[160px]">
                {latestRow.provider}
                {latestRow.model ? ` · ${latestRow.model}` : ""}
              </span>
            </>
          )}
          {drift.label && (
            <span
              className={cn(
                "ml-auto font-medium",
                drift.kind === "drift"
                  ? "text-amber-400"
                  : "text-muted-foreground/80",
              )}
            >
              {drift.kind === "drift" ? "信号变化 " : "信号稳定 "}
              {drift.label}
            </span>
          )}
        </div>

        {/* Row C — primary CTA + expand hint */}
        <div className="flex items-center gap-2 pt-1">
          <a
            href={`/analysis/${latestRow.id}`}
            className="inline-block flex-1"
            onClick={e => e.stopPropagation()}
          >
            <Button size="sm" className="w-full">
              打开最新分析
              <ArrowRight className="h-3.5 w-3.5 ml-1" />
            </Button>
          </a>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setOpen(v => !v)}
            aria-label={open ? "收起历史" : "展开历史"}
          >
            {open ? "收起" : "历史"}
          </Button>
        </div>

        {open && (
          <div
            className="rounded border border-border/40 bg-background/40 mt-1"
            data-ticker-group-history
          >
            {loading && timeline === null && (
              <p className="text-[11px] text-muted-foreground py-3 text-center">
                加载历史…
              </p>
            )}
            {error && (
              <p
                className="text-[11px] text-amber-300 py-2 px-3"
                role="alert"
              >
                历史加载失败：{error}
              </p>
            )}
            <ul className="divide-y divide-border/40">
              {historyRows.map(r => (
                <HistoryItem key={r.id} row={r} />
              ))}
              {historyRows.length === 0 && !loading && !error && (
                <li className="text-[11px] text-muted-foreground py-3 text-center">
                  暂无更早的分析记录
                </li>
              )}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

interface HistoryItemProps {
  row: TimelineRecord | CompletedAnalysisRow
}

function HistoryItem({ row }: HistoryItemProps) {
  return (
    <li>
      <a
        href={`/analysis/${row.id}`}
        className="flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/30 min-w-0"
      >
        <Badge
          variant={signalVariant(row.signal || "")}
          className="text-[9px] shrink-0"
        >
          {signalLabel(row.signal)}
        </Badge>
        <span className="text-muted-foreground truncate">
          {row.date || ""}
        </span>
        <span className="ml-auto text-muted-foreground shrink-0">
          {fmtRelative(row.created_at)}
        </span>
        <ExternalLink className="h-3 w-3 text-muted-foreground shrink-0" />
      </a>
    </li>
  )
}
