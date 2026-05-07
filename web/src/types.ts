export type Severity = 'info' | 'warning' | 'critical'
export type Availability = 'ok' | 'failed' | 'not_yet_available' | 'missing'

export interface LatestSummary {
  date: string
  peakActualMw: number | null
  peakActualAt: string | null
  peakUsagePct: number | null
  peakSupplyMw: number | null
}

export interface ForecastSummary {
  date: string
  peakForecastMw: number | null
  peakForecastAt: string | null
  severity: Severity
}

export interface StatusJSON {
  project: string
  schemaVersion: string
  timezone: string
  lastUpdatedAt: string
  coverageTo: string | null
  availability: Availability
  missingDays: string[]
  failedDays: string[]
  latest: LatestSummary | null
  yesterday: string | null
  today: ForecastSummary | null
  tomorrow: ForecastSummary | null
}

export interface ForecastPoint {
  ts: string
  forecastMw: number
  p95LowerMw: number
  p95UpperMw: number
  p99LowerMw: number
  p99UpperMw: number
}

export interface ForecastJSON {
  date: string
  timezone: string
  availability: Availability
  model?: { name: string; version: string; nWeeks: number }
  peak?: {
    forecastMw: number
    at: string
    interval: { p95Lower: number; p95Upper: number }
  }
  series: ForecastPoint[]
  message?: string
}

export interface AlertEvent {
  id: string
  type: string
  severity: Severity
  startAt: string
  endAt: string
  metric: string
  reason: string
  tags: string[]
}

export interface AlertsJSON {
  date: string
  timezone: string
  availability: Availability
  summary: { critical: number; warning: number; info: number }
  events: AlertEvent[]
}

export interface ActualPoint {
  ts: string
  actualMw: number | null
  tepcoForecastMw: number | null
  usagePct: number | null
  supplyMw: number | null
}

export interface ActualJSON {
  date: string
  timezone: string
  availability: Availability
  series: ActualPoint[]
}
