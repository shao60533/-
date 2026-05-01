import { useEffect, useRef, useState } from "react"
import type { EChartsOption } from "echarts"
import { Skeleton } from "@/components/ui/skeleton"

// Type-only import — does not pull the runtime module into the bundle.
// Concrete echarts code is loaded on demand via the lazy loader below
// so non-chart islands (settings, alerts, screener-v2 form, etc.)
// never end up importing the ~700kB echarts-vendor chunk.
type EChartsModule = typeof import("@/lib/echarts")["echarts"]

let _echartsPromise: Promise<EChartsModule> | null = null

/** Load the tree-shaken echarts bundle once per page. Idempotent. */
function loadECharts(): Promise<EChartsModule> {
  if (_echartsPromise === null) {
    _echartsPromise = import("@/lib/echarts").then(m => m.echarts)
  }
  return _echartsPromise
}

interface ChartPanelProps {
  option: EChartsOption | null
  loading?: boolean
  height?: number
  theme?: "dark" | "light"
  className?: string
  // Note: signature stays compatible with the old call sites — chart
  // is only handed off after the dynamic import resolves.
  onReady?: (chart: ReturnType<EChartsModule["init"]>) => void
}

export function ChartPanel({
  option,
  loading = false,
  height = 320,
  theme = "dark",
  className = "",
  onReady,
}: ChartPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ReturnType<EChartsModule["init"]> | null>(null)
  // Track when echarts is ready so option/loading effects can apply.
  // Rendered as the "is the runtime loaded" gate, not a "is the chart
  // initialised" gate (the chart is initialised inside this same effect).
  const [echartsReady, setEchartsReady] = useState(false)

  // Init + dispose. We always render the container <div> so the ref is
  // guaranteed to be attached when the dynamic import resolves; the
  // skeleton sits on top via absolute positioning until echarts boots.
  useEffect(() => {
    let cancelled = false
    let ro: ResizeObserver | null = null
    const node = containerRef.current
    if (!node) return

    loadECharts().then(echarts => {
      if (cancelled || !node.isConnected) return
      const chart = echarts.init(node, theme, { renderer: "canvas" })
      chartRef.current = chart
      setEchartsReady(true)
      onReady?.(chart)
      ro = new ResizeObserver(() => chart.resize())
      ro.observe(node)
    })

    return () => {
      cancelled = true
      ro?.disconnect()
      chartRef.current?.dispose()
      chartRef.current = null
      setEchartsReady(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme])

  // Update option once both option AND chart instance exist.
  useEffect(() => {
    if (!chartRef.current || !option) return
    chartRef.current.setOption(option, { notMerge: true })
  }, [option, echartsReady])

  // Loading overlay — only meaningful after echarts has booted.
  useEffect(() => {
    if (!chartRef.current) return
    if (loading) {
      chartRef.current.showLoading("default", {
        text: "",
        maskColor: "rgba(0,0,0,0.1)",
        spinnerRadius: 14,
        lineWidth: 2,
      })
    } else {
      chartRef.current.hideLoading()
    }
  }, [loading, echartsReady])

  // Show a skeleton until we either (a) the echarts runtime hasn't
  // arrived yet, or (b) the parent hasn't produced an option yet. We
  // render the container <div> behind the skeleton so the ref is set
  // and ready to receive echarts.init the moment the runtime resolves.
  const showSkeleton = !echartsReady || (loading && !option)

  return (
    <div
      className={className}
      style={{ position: "relative", height, width: "100%" }}
    >
      <div
        ref={containerRef}
        style={{ height: "100%", width: "100%" }}
      />
      {showSkeleton && (
        <Skeleton
          style={{
            position: "absolute", inset: 0,
            height: "100%", width: "100%",
          }}
        />
      )}
    </div>
  )
}
