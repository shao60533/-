import { useEffect, useRef, type ReactNode } from "react"
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  ColorType,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts"
import { Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"

interface OHLCVRow {
  date: string; open: number; high: number; low: number; close: number; volume: number
}

export type TVChartState = "loading" | "ok" | "empty" | "error"

interface TVChartProps {
  data: OHLCVRow[]
  height?: number
  state?: TVChartState
  onRetry?: () => void
  className?: string
}

/**
 * TVChart never unmounts its container — the chart always initializes once
 * the component mounts, and incoming data flows into the same Series refs
 * that init created. The previous "if loading return Skeleton" path swapped
 * the container out, leaving candleRef/volumeRef null when data arrived and
 * silently dropping the update.
 *
 * The visual state (loading / empty / error) is rendered as an absolute
 * overlay on top of the live container.
 */
export function TVChart({
  data,
  height = 380,
  state = "ok",
  onRetry,
  className = "",
}: TVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null)
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null)

  // ── Init: depends only on height so we don't tear the chart down on
  // every data refresh. Container is always mounted, so this useEffect
  // always runs on first render and the series refs are populated before
  // the data-update effect ever fires.
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9ca3af",
        fontSize: 11,
        fontFamily: "JetBrains Mono, monospace",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: "#333" },
      timeScale: { borderColor: "#333", timeVisible: false },
    })
    chartRef.current = chart

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: "#00ff88",
      downColor: "#ff3860",
      borderUpColor: "#00ff88",
      borderDownColor: "#ff3860",
      wickUpColor: "#00ff88",
      wickDownColor: "#ff3860",
    })
    candleRef.current = candle

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    })
    volumeRef.current = volume

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect?.width
      if (w) chart.applyOptions({ width: w })
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volumeRef.current = null
    }
  }, [height])

  // ── Update data ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!candleRef.current || !volumeRef.current || data.length === 0) return

    const candleData = data.map(d => ({
      time: d.date as string,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }))
    const volumeData = data.map(d => ({
      time: d.date as string,
      value: d.volume,
      color: d.close >= d.open ? "rgba(0,255,136,0.3)" : "rgba(255,56,96,0.3)",
    }))

    candleRef.current.setData(candleData as any)
    volumeRef.current.setData(volumeData as any)
    chartRef.current?.timeScale().fitContent()
  }, [data])

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ height, position: "relative" }}
    >
      {state === "loading" && (
        <Overlay>
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="text-xs text-muted-foreground">加载 K 线…</span>
        </Overlay>
      )}
      {state === "empty" && (
        <Overlay>
          <span className="text-sm text-muted-foreground">暂无 K 线数据</span>
          {onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry} className="h-7 px-2 text-xs">
              <RefreshCw className="h-3.5 w-3.5 mr-1" />重试
            </Button>
          )}
        </Overlay>
      )}
      {state === "error" && (
        <Overlay>
          <span className="text-sm text-[var(--color-accent-red)]">K 线加载失败</span>
          {onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry} className="h-7 px-2 text-xs">
              <RefreshCw className="h-3.5 w-3.5 mr-1" />重试
            </Button>
          )}
        </Overlay>
      )}
    </div>
  )
}

function Overlay({ children }: { children: ReactNode }) {
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center gap-2 z-10 pointer-events-none"
      style={{ background: "rgba(17, 26, 46, 0.65)" }}
    >
      {/* The button inside needs pointer events */}
      <div className="flex flex-col items-center gap-2 pointer-events-auto">
        {children}
      </div>
    </div>
  )
}
