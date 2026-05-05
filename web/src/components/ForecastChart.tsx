import {
  ComposedChart, Area, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import type { ForecastPoint, ActualPoint } from '../types'
import { useT } from '../i18n'

interface Props {
  forecast: ForecastPoint[]
  actual?: ActualPoint[]
  showBands?: boolean   // false for yesterday/today (TEPCO data), true for tomorrow (baseline)
}

const MW_TO_MANKW = 10

interface ChartRow {
  hour: string
  forecast: number
  actual: number | null
  tepcoForecast: number | null
  p95Base: number
  p95Fill: number
}

function mw(v: number) { return v / MW_TO_MANKW }

function buildChartData(forecast: ForecastPoint[], actual?: ActualPoint[]): ChartRow[] {
  return forecast.map(f => {
    const h = f.ts.substring(11, 13)
    const act = actual?.find(a => a.ts.substring(11, 13) === h)
    return {
      hour: `${h}:00`,
      forecast: mw(f.forecastMw),
      actual: act?.actualMw != null ? mw(act.actualMw) : null,
      tepcoForecast: act?.tepcoForecastMw != null ? mw(act.tepcoForecastMw) : null,
      p95Base: mw(f.p95LowerMw),
      p95Fill: Math.max(0, mw(f.p95UpperMw) - mw(f.p95LowerMw)),
    }
  })
}

function yDomain(rows: ChartRow[], hasActual: boolean, showBands: boolean): [number, number] {
  const vals: number[] = rows.flatMap(r => [
    r.forecast,
    ...(showBands ? [r.p95Base, r.p95Base + r.p95Fill] : []),
    ...(hasActual && r.actual != null ? [r.actual] : []),
    ...(r.tepcoForecast != null ? [r.tepcoForecast] : []),
  ])
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const pad = (hi - lo) * 0.06
  return [
    Math.floor((lo - pad) / 200) * 200,
    Math.ceil((hi + pad) / 200) * 200,
  ]
}

function CustomTooltip({ active, payload, label, labels }: {
  active?: boolean
  payload?: Array<{ dataKey: string; value: number }>
  label?: string
  labels: { forecast: string; actual: string; tepcoForecast: string; forecastRange: string }
}) {
  if (!active || !payload?.length) return null
  const row: Record<string, number> = {}
  for (const p of payload) row[p.dataKey] = p.value

  const fmt = (v: number) => `${Math.round(v).toLocaleString()} 万kW`

  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', padding: '8px 12px', borderRadius: 6, fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {row.tepcoForecast != null && (
        <div style={{ color: '#7c3aed' }}>{labels.tepcoForecast}: {fmt(row.tepcoForecast)}</div>
      )}
      {row.actual != null && (
        <div style={{ color: '#ea580c' }}>{labels.actual}: {fmt(row.actual)}</div>
      )}
      {row.forecast != null && row.tepcoForecast == null && (
        <div style={{ color: '#2563eb' }}>{labels.forecast}: {fmt(row.forecast)}</div>
      )}
      {row.p95Base != null && (
        <div style={{ color: '#93c5fd' }}>
          {labels.forecastRange}: [{Math.round(row.p95Base).toLocaleString()}, {Math.round(row.p95Base + row.p95Fill).toLocaleString()}] 万kW
        </div>
      )}
    </div>
  )
}

export function ForecastChart({ forecast, actual, showBands = true }: Props) {
  const { t } = useT()
  if (forecast.length === 0) return null

  const data = buildChartData(forecast, actual)
  const hasActual = data.some(r => r.actual != null)
  const hasTepcoFc = data.some(r => r.tepcoForecast != null)
  const domain = yDomain(data, hasActual, showBands)
  const fmtAxis = (v: number) => `${v.toLocaleString()}`
  const tooltipLabels = {
    forecast: t.forecast,
    actual: t.actual,
    tepcoForecast: t.tepcoForecast,
    forecastRange: t.forecastRange,
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
        {!hasTepcoFc && (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#2563eb', height: 3 }} />
            <span>{t.forecast}</span>
          </div>
        )}
        {showBands && (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#93c5fd', height: 8, borderRadius: 2 }} />
            <span>{t.forecastRange}</span>
          </div>
        )}
      </div>

      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 48 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="hour" tick={{ fontSize: 11 }} interval={5} />
          <YAxis
            tickFormatter={fmtAxis}
            tick={{ fontSize: 11 }}
            domain={domain}
            width={52}
            label={{ value: '万kW', angle: -90, position: 'insideLeft', offset: 12, style: { fontSize: 10, fill: '#94a3b8' } }}
          />
          <Tooltip content={<CustomTooltip labels={tooltipLabels} />} />

          {showBands && (
            <>
              <Area type="monotone" dataKey="p95Base" stackId="p95" stroke="none" fill="transparent" legendType="none" isAnimationActive={false} />
              <Area type="monotone" dataKey="p95Fill" stackId="p95" stroke="none" fill="#93c5fd" fillOpacity={0.5} legendType="none" isAnimationActive={false} />
            </>
          )}

          {/* baseline 예측선: TEPCO 예측 없을 때만 표시 (= 내일 탭) */}
          {!hasTepcoFc && (
            <Line type="monotone" dataKey="forecast" stroke="#2563eb" strokeWidth={2} dot={false} legendType="none" isAnimationActive={false} />
          )}

          {hasTepcoFc && (
            <Line type="monotone" dataKey="tepcoForecast" stroke="#7c3aed" strokeWidth={2} dot={false} legendType="none" isAnimationActive={false} connectNulls={false} />
          )}

          {hasActual && (
            <Line type="monotone" dataKey="actual" stroke="#ea580c" strokeWidth={2} dot={false} legendType="none" isAnimationActive={false} connectNulls={false} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
