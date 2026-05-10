import { useMemo } from "react"

interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  positive?: boolean
  className?: string
}

export function Sparkline({
  values,
  width = 320,
  height = 40,
  positive,
  className,
}: SparklineProps) {
  const path = useMemo(() => {
    const cleanValues = values.filter(Number.isFinite)
    if (cleanValues.length < 2) return null

    const min = Math.min(...cleanValues)
    const max = Math.max(...cleanValues)
    const range = max - min || 1
    const stepX = width / (cleanValues.length - 1)

    return cleanValues
      .map((value, index) => {
        const x = index * stepX
        const y = height - ((value - min) / range) * height
        return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
      })
      .join(" ")
  }, [height, values, width])

  if (!path) return null

  const first = values.find(Number.isFinite) ?? 0
  const last = [...values].reverse().find(Number.isFinite) ?? first
  const isUp = positive ?? last >= first
  const stroke = isUp ? "var(--color-accent-green)" : "var(--color-accent-red)"
  const fill = isUp
    ? "color-mix(in srgb, var(--color-accent-green) 16%, transparent)"
    : "color-mix(in srgb, var(--color-accent-red) 16%, transparent)"
  const fillPath = `${path} L${width},${height} L0,${height} Z`

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      preserveAspectRatio="none"
      style={{ width: "100%", height }}
      aria-hidden="true"
      data-sparkline=""
    >
      <path d={fillPath} fill={fill} />
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}
