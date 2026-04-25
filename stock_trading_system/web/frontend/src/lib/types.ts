/**
 * Shared API response types.
 */

export interface Guru {
  name: string
  display_name: string
  philosophy: string
  principles: string[]
  motto: string
  avatar_initials: string
  avatar_color: string
}

export interface Estimate {
  llm_calls: number
  duration_sec: number
  tokens_in: number
  tokens_out: number
  cost_cny: number
}

export interface Task {
  id: string
  type: string
  status: string
  progress: number
  title: string
  created_at: string
  completed_at: string | null
  params_json?: string
}

export interface GuruSignalResult {
  guru: string
  ticker: string
  signal: "bullish" | "bearish" | "neutral"
  confidence: number
  reasoning: string
  total_score: number
}

export interface ScreenV3Result {
  ticker: string
  final_score: number
  avg_confidence: number
  guru_signals: GuruSignalResult[]
  roundtable?: {
    consensus: string[]
    dissent: string[]
    split: boolean
  }
}
