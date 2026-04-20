import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(v: number, prefix = "$") {
  return `${prefix}${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatPct(v: number, digits = 1) {
  const s = v >= 0 ? "+" : ""
  return `${s}${v.toFixed(digits)}%`
}
