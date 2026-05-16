import { useState } from 'react'
import {
  ComposedChart, Area, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import type { ForecastPoint, ActualPoint } from '../types'
import { useT, type Locale } from '../i18n'
import { formatPowerDisplayValue, powerAxisStep, powerDisplayValue, powerUnit } from '../units'

interface Props {
  forecast: ForecastPoint[]
  actual?: ActualPoint[]
  showBands?: boolean
}

interface ChartRow {
  hour: string
  forecast: number
  actual: number | null
  tepcoForecast: number | null
  supply: number | null
  usagePct: number | null
  usageSource: 'reported' | 'model_forecast' | null
  p95Base: number
  p95Fill: number
}

function buildChartData(forecast: ForecastPoint[], locale: Locale, actual?: ActualPoint[]): ChartRow[] {
  return forecast.map(f => {
    const h = f.ts.substring(11, 13)
    const act = actual?.find(a => a.ts.substring(11, 13) === h)
    const p95Lower = Math.min(f.p95LowerMw, f.p95UpperMw, f.forecastMw)
    const p95Upper = Math.max(f.p95LowerMw, f.p95UpperMw, f.forecastMw)
    const estimatedUsagePct = act?.supplyMw != null && act.supplyMw > 0
      ? ((act.actualMw ?? f.forecastMw) / act.supplyMw) * 100
      : null
    const usagePct = act?.usagePct ?? estimatedUsagePct
    return {
      hour: `${h}:00`,
      forecast: powerDisplayValue(f.forecastMw, locale),
      actual: act?.actualMw != null ? powerDisplayValue(act.actualMw, locale) : null,
      tepcoForecast: act?.tepcoForecastMw != null ? powerDisplayValue(act.tepcoForecastMw, locale) : null,
      supply: act?.supplyMw != null ? powerDisplayValue(act.supplyMw, locale) : null,
      usagePct,
      usageSource: act?.usagePct != null ? 'reported' : usagePct != null ? 'model_forecast' : null,
      p95Base: powerDisplayValue(p95Lower, locale),
      p95Fill: powerDisplayValue(p95Upper, locale) - powerDisplayValue(p95Lower, locale),
    }
  })
}

function yDomain(
  rows: ChartRow[],
  hasActual: boolean,
  showBands: boolean,
  showModelLine: boolean,
  step: number,
): [number, number] {
  const vals: number[] = rows.flatMap(r => [
    ...(showModelLine ? [r.forecast] : []),
    ...(showBands ? [r.p95Base, r.p95Base + r.p95Fill] : []),
    ...(hasActual && r.actual != null ? [r.actual] : []),
    ...(r.tepcoForecast != null ? [r.tepcoForecast] : []),
  ])
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const pad = (hi - lo) * 0.06
  return [
    Math.floor((lo - pad) / step) * step,
    Math.ceil((hi + pad) / step) * step,
  ]
}

function fmtPct(value: number): string {
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`
}

function metricLabels(locale: Locale) {
  if (locale === 'en') {
    return {
      estimatedUsage: 'Estimated usage rate',
    }
  }
  if (locale === 'ja') {
    return {
      estimatedUsage: '予測使用率',
    }
  }
  return {
    estimatedUsage: '예상 사용률',
  }
}

function CustomTooltip({ active, payload, label, labels, locale }: {
  active?: boolean
  payload?: Array<{ dataKey: string; value: number; payload?: ChartRow }>
  label?: string
  labels: {
    modelForecast: string
    actual: string
    tepcoForecast: string
    forecastRange: string
    supply: string
    usageRate: string
    estimatedUsageRate: string
  }
  locale: Locale
}) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  const row: Record<string, number> = {}
  for (const p of payload) row[p.dataKey] = p.value

  const fmt = (v: number) => `${formatPowerDisplayValue(v, locale)} ${powerUnit(locale)}`

  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', padding: '8px 12px', borderRadius: 6, fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {row.tepcoForecast != null && (
        <div style={{ color: '#7c3aed' }}>{labels.tepcoForecast}: {fmt(row.tepcoForecast)}</div>
      )}
      {row.actual != null && (
        <div style={{ color: '#ea580c' }}>{labels.actual}: {fmt(row.actual)}</div>
      )}
      {point?.supply != null && (
        <div style={{ color: '#0f766e' }}>{labels.supply}: {fmt(point.supply)}</div>
      )}
      {point?.usagePct != null && (
        <div style={{ color: '#dc2626' }}>
          {point.usageSource === 'reported' ? labels.usageRate : labels.estimatedUsageRate}: {fmtPct(point.usagePct)}
        </div>
      )}
      {row.forecast != null && (
        <div style={{ color: '#2563eb' }}>{labels.modelForecast}: {fmt(row.forecast)}</div>
      )}
      {row.p95Base != null && (
        <div style={{ color: '#93c5fd' }}>
          {labels.forecastRange}: [{formatPowerDisplayValue(row.p95Base, locale)}, {formatPowerDisplayValue(row.p95Base + row.p95Fill, locale)}] {powerUnit(locale)}
        </div>
      )}
    </div>
  )
}

export function ForecastChart({ forecast, actual, showBands = true }: Props) {
  const { t, locale } = useT()
  const [showModelForecast, setShowModelForecast] = useState(false)
  if (forecast.length === 0) return null

  const data = buildChartData(forecast, locale, actual)
  const hasActual = data.some(r => r.actual != null)
  const hasTepcoFc = data.some(r => r.tepcoForecast != null)
  const showModelLine = !hasTepcoFc || showModelForecast
  const domain = yDomain(data, hasActual, showBands, showModelLine, powerAxisStep(locale))
  const fmtAxis = (v: number) => formatPowerDisplayValue(v, locale)
  const labels = metricLabels(locale)
  const tooltipLabels = {
    modelForecast: t.modelForecast,
    actual: t.actual,
    tepcoForecast: t.tepcoForecast,
    forecastRange: t.forecastRange,
    supply: t.supply,
    usageRate: t.metricUsagePct,
    estimatedUsageRate: labels.estimatedUsage,
  }

  return (
    <div className="card chart-container">
      <div className="chart-legend">
        {hasActual && (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#ea580c', height: 3 }} />
            <span>{t.actual}</span>
          </div>
        )}
        {hasTepcoFc && (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#7c3aed', height: 3 }} />
            <span>{t.tepcoForecast}</span>
          </div>
        )}
        {hasTepcoFc ? (
          <button
            type="button"
            className={`legend-toggle${showModelForecast ? ' active' : ''}`}
            onClick={() => setShowModelForecast(v => !v)}
            aria-pressed={showModelForecast}
          >
            <div className="legend-dot" style={{ background: '#2563eb', height: 3 }} />
            <span>{t.modelForecast}</span>
          </button>
        ) : (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#2563eb', height: 3 }} />
            <span>{t.modelForecast}</span>
          </div>
        )}
        {showBands && (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#93c5fd', height: 8, borderRadius: 2 }} />
            <span>{t.forecastRange}</span>
          </div>
        )}
      </div>

      <div className="chart-frame">
        <div className="chart-unit-label">{powerUnit(locale)}</div>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="hour" tick={{ fontSize: 11 }} interval={5} />
            <YAxis
              yAxisId="power"
              tickFormatter={fmtAxis}
              tick={{ fontSize: 11 }}
              tickMargin={4}
              domain={domain}
              width={40}
            />
            <Tooltip content={<CustomTooltip labels={tooltipLabels} locale={locale} />} />

            {showBands && (
              <>
                <Area yAxisId="power" type="monotone" dataKey="p95Base" stackId="p95" stroke="none" fill="transparent" legendType="none" isAnimationActive={false} />
                <Area yAxisId="power" type="monotone" dataKey="p95Fill" stackId="p95" stroke="none" fill="#93c5fd" fillOpacity={0.5} legendType="none" isAnimationActive={false} />
              </>
            )}

            {showModelLine && (
              <Line yAxisId="power" type="monotone" dataKey="forecast" stroke="#2563eb" strokeWidth={2} dot={false} legendType="none" isAnimationActive={false} />
            )}

            {hasTepcoFc && (
              <Line yAxisId="power" type="monotone" dataKey="tepcoForecast" stroke="#7c3aed" strokeWidth={2} dot={false} legendType="none" isAnimationActive={false} connectNulls={false} />
            )}

            {hasActual && (
              <Line yAxisId="power" type="monotone" dataKey="actual" stroke="#ea580c" strokeWidth={2} dot={false} legendType="none" isAnimationActive={false} connectNulls={false} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
