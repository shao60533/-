import { useEffect, useRef } from "react"
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  ColorType,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts"
import { Skeleton } from "@/components/ui/skeleton"

interface OHLCVRow {
  date: string; open: number; high: number; low: number; close: number; volume: number
}

interface TVChartProps {
  data: OHLCVRow[]
  height?: number
  loading?: boolean
  className?: string
}

export function TVChart({ data, height = 380, loading = false, className = "" }: TVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null)
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null)

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
    }
  }, [height])

  // Update data
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

  if (loading && data.length === 0) {
    return <Skeleton className={className} style={{ height }} />
  }

  return <div ref={containerRef} className={className} />
}
