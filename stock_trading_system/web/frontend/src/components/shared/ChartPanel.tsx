import { useEffect, useRef } from "react"
import { echarts } from "@/lib/echarts"
import type { EChartsOption } from "@/lib/echarts"
import { Skeleton } from "@/components/ui/skeleton"

interface ChartPanelProps {
  option: EChartsOption | null
  loading?: boolean
  height?: number
  theme?: "dark" | "light"
  className?: string
  onReady?: (chart: ReturnType<typeof echarts.init>) => void
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
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null)

  // Init + dispose
  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current, theme, { renderer: "canvas" })
    chartRef.current = chart
    onReady?.(chart)

    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme])

  // Update option
  useEffect(() => {
    if (!chartRef.current || !option) return
    chartRef.current.setOption(option, { notMerge: true })
  }, [option])

  // Loading state
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
  }, [loading])

  if (loading && !chartRef.current) {
    return <Skeleton className={className} style={{ height }} />
  }

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ height, width: "100%" }}
    />
  )
}
