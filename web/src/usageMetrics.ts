import type { ActualPoint, ForecastPoint } from './types'

export interface UsageMetric {
  usagePct: number
  supplyMw: number | null
  at: string
}

export interface PeakUsageMetrics {
  observed: UsageMetric | null
  tepco: UsageMetric | null
  model: UsageMetric | null
}

function nonnegative(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value) && value >= 0
}

export function isObservedActual(point: ActualPoint): boolean {
  // Legacy finalized CSV rows omit actualSource; explicit substitutes do not qualify.
  return nonnegative(point.actualMw) && point.actualSource !== 'tepco_forecast_fallback'
}

function peak(rows: UsageMetric[]): UsageMetric | null {
  return rows.reduce<UsageMetric | null>((best, row) => (
    !best || row.usagePct > best.usagePct
      || (row.usagePct === best.usagePct && row.at < best.at) ? row : best
  ), null)
}

export function peakUsageMetrics(
  date: string,
  forecast: ForecastPoint[] = [],
  actual: ActualPoint[] = [],
): PeakUsageMetrics {
  const sameDay = (ts: string) => ts.startsWith(`${date}T`) && Number.isFinite(Date.parse(ts))
  const forecasts = new Map(forecast.filter(p => sameDay(p.ts)).map(p => [Date.parse(p.ts), p]))
  const observed: UsageMetric[] = []
  const tepco: UsageMetric[] = []
  const model: UsageMetric[] = []

  for (const row of actual.filter(p => sameDay(p.ts))) {
    const supply = nonnegative(row.supplyMw) && row.supplyMw > 0 ? row.supplyMw : null
    if (isObservedActual(row)) {
      const pct = nonnegative(row.usagePct) ? row.usagePct
        : supply != null ? row.actualMw! / supply * 100 : null
      if (pct != null) observed.push({ usagePct: pct, supplyMw: supply, at: row.ts })
    }
    if (supply == null) continue
    if (nonnegative(row.tepcoForecastMw)) {
      tepco.push({ usagePct: row.tepcoForecastMw / supply * 100, supplyMw: supply, at: row.ts })
    }
    const predicted = forecasts.get(Date.parse(row.ts))?.forecastMw
    if (nonnegative(predicted)) {
      model.push({ usagePct: predicted / supply * 100, supplyMw: supply, at: row.ts })
    }
  }
  return { observed: peak(observed), tepco: peak(tepco), model: peak(model) }
}
