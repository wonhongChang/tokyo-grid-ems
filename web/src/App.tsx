import { useState } from 'react'
import { useFetch } from './hooks/useFetch'
import { StatusBar } from './components/StatusBar'
import { ForecastChart } from './components/ForecastChart'
import { AlertsList } from './components/AlertsList'
import { ValidationPanel } from './components/ValidationPanel'
import { useT, LOCALE_LABELS, type Locale } from './i18n'
import { formatPowerParts } from './units'
import type {
  StatusJSON, ForecastJSON, AlertsJSON, ActualJSON,
  LatestSummary, ForecastSummary, Severity, ForecastPoint, ActualPoint,
} from './types'

const BASE = import.meta.env.BASE_URL
const USAGE_WARNING_PCT = 92
const USAGE_CRITICAL_PCT = 97

type TabId = 'yesterday' | 'today' | 'tomorrow' | 'validation'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(iso: string) { return iso.substring(11, 16) }

function fmtPct(value: number): string {
  return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)
}

type UsageMetricSource = 'reported' | 'model_forecast'

interface UsageMetric {
  usagePct: number
  supplyMw: number
  at: string
  source: UsageMetricSource
}

function usageMetricLabels(locale: Locale) {
  if (locale === 'en') return { estimatedPeakUsage: 'Estimated Peak Usage' }
  if (locale === 'ja') return { estimatedPeakUsage: '予測最大使用率' }
  return { estimatedPeakUsage: '예상 최대 사용률' }
}

function peakUsageMetric(forecast?: ForecastPoint[] | null, actual?: ActualPoint[] | null): UsageMetric | null {
  if (!forecast?.length || !actual?.length) return null

  const candidates = forecast.flatMap(f => {
    const hour = f.ts.substring(11, 13)
    const act = actual.find(a => a.ts.substring(11, 13) === hour)
    if (act?.supplyMw == null || act.supplyMw <= 0) return []

    const observedUsagePct = act.usagePct ?? (act.actualMw != null ? (act.actualMw / act.supplyMw) * 100 : null)
    const source: UsageMetricSource = observedUsagePct != null ? 'reported' : 'model_forecast'
    const usagePct = observedUsagePct ?? (f.forecastMw / act.supplyMw) * 100

    return [{
      usagePct,
      supplyMw: act.supplyMw,
      at: f.ts,
      source,
    }]
  })

  if (candidates.length === 0) return null
  return candidates.reduce((best, row) => row.usagePct > best.usagePct ? row : best)
}

function usageSeverity(pct: number | null | undefined): Severity | null {
  if (pct == null) return null
  if (pct >= USAGE_CRITICAL_PCT) return 'critical'
  if (pct >= USAGE_WARNING_PCT) return 'warning'
  return null
}

function PowerStatValue({ mw }: { mw: number }) {
  const { locale } = useT()
  const parts = formatPowerParts(mw, locale)
  return (
    <>
      <span className="peak-stat-value">{parts.value}</span>
      <span className="peak-stat-unit"> {parts.unit}</span>
    </>
  )
}

function SeverityBadge({ sev }: { sev: Severity }) {
  const { t } = useT()
  const label = sev === 'critical' ? t.criticalBadge : sev === 'warning' ? t.warningBadge : t.infoBadge
  return <span className={`badge ${sev}`}>{label}</span>
}

function UsageMetricStats({ metric }: { metric: UsageMetric | null }) {
  const { t, locale } = useT()
  if (!metric) return null

  const labels = usageMetricLabels(locale)
  const usageLabel = metric.source === 'model_forecast' ? labels.estimatedPeakUsage : t.peakUsage

  return (
    <>
      <div className="peak-stat">
        <div className="peak-stat-label">{usageLabel}</div>
        <div>
          <span className="peak-stat-value">{fmtPct(metric.usagePct)}</span>
          <span className="peak-stat-unit"> %</span>
        </div>
        <div className="peak-stat-sub">@ {fmtTime(metric.at)}</div>
      </div>
      <div className="peak-stat">
        <div className="peak-stat-label">{t.supply}</div>
        <div>
          <PowerStatValue mw={metric.supplyMw} />
        </div>
        <div className="peak-stat-sub">@ {fmtTime(metric.at)}</div>
      </div>
    </>
  )
}

// ── Peak Cards ────────────────────────────────────────────────────────────────

function ActualPeakCard({ s }: { s: LatestSummary }) {
  const { t } = useT()
  const sev = usageSeverity(s.peakUsagePct)
  return (
    <div className="card">
      {sev && <div className="card-title"><SeverityBadge sev={sev} /></div>}
      <div className="peak-grid">
        {s.peakActualMw != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakActual}</div>
            <div>
              <PowerStatValue mw={s.peakActualMw} />
            </div>
            {s.peakActualAt && <div className="peak-stat-sub">@ {fmtTime(s.peakActualAt)}</div>}
          </div>
        )}
        {s.peakUsagePct != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakUsage}</div>
            <div>
              <span className="peak-stat-value">{s.peakUsagePct}</span>
              <span className="peak-stat-unit"> %</span>
            </div>
          </div>
        )}
        {s.peakSupplyMw != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.supply}</div>
            <div>
              <PowerStatValue mw={s.peakSupplyMw} />
            </div>
          </div>
        )}
        {s.peakTempC != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakTemp}</div>
            <div>
              <span className="peak-stat-value">{s.peakTempC}</span>
              <span className="peak-stat-unit"> °C</span>
            </div>
            <div className="peak-stat-sub peak-stat-source">Open-Meteo</div>
          </div>
        )}
      </div>
    </div>
  )
}

function ForecastPeakCard({ s, forecast, actual }: {
  s: ForecastSummary
  forecast?: ForecastPoint[]
  actual?: ActualPoint[]
}) {
  const { t } = useT()
  const usageMetric = peakUsageMetric(forecast, actual)
  return (
    <div className="card">
      {s.severity !== 'info' && <div className="card-title"><SeverityBadge sev={s.severity} /></div>}
      <div className="peak-grid">
        {s.peakForecastMw != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakForecast}</div>
            <div>
              <PowerStatValue mw={s.peakForecastMw} />
            </div>
            {s.peakForecastAt && <div className="peak-stat-sub">@ {fmtTime(s.peakForecastAt)}</div>}
          </div>
        )}
        <UsageMetricStats metric={usageMetric} />
        {s.peakTempC != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakTemp}</div>
            <div>
              <span className="peak-stat-value">{s.peakTempC}</span>
              <span className="peak-stat-unit"> °C</span>
            </div>
            <div className="peak-stat-sub peak-stat-source">Open-Meteo</div>
          </div>
        )}
      </div>
    </div>
  )
}

function TodayPeakCard({ actual, forecast, severity, peakTempC }: {
  actual: ActualJSON
  forecast?: ForecastPoint[]
  severity: Severity
  peakTempC?: number
}) {
  const { t } = useT()
  const usageMetric = peakUsageMetric(forecast, actual.series)
  const tepcoPoints = actual.series.filter(p => p.tepcoForecastMw != null)
  const tPeak = tepcoPoints.length > 0
    ? tepcoPoints.reduce((a, b) => b.tepcoForecastMw! > a.tepcoForecastMw! ? b : a)
    : null
  const actualPoints = actual.series.filter(p => p.actualMw != null)
  const aPeak = actualPoints.length > 0
    ? actualPoints.reduce((a, b) => b.actualMw! > a.actualMw! ? b : a)
    : null
  return (
    <div className="card">
      {severity !== 'info' && <div className="card-title"><SeverityBadge sev={severity} /></div>}
      <div className="peak-grid">
        {tPeak && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakTepcoForecast}</div>
            <div>
              <PowerStatValue mw={tPeak.tepcoForecastMw!} />
            </div>
            <div className="peak-stat-sub">@ {fmtTime(tPeak.ts)}</div>
          </div>
        )}
        {aPeak && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakActual}</div>
            <div>
              <PowerStatValue mw={aPeak.actualMw!} />
            </div>
            <div className="peak-stat-sub">@ {fmtTime(aPeak.ts)}</div>
          </div>
        )}
        <UsageMetricStats metric={usageMetric} />
        {peakTempC != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakTemp}</div>
            <div>
              <span className="peak-stat-value">{peakTempC}</span>
              <span className="peak-stat-unit"> °C</span>
            </div>
            <div className="peak-stat-sub peak-stat-source">Open-Meteo</div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Yesterday Tab ─────────────────────────────────────────────────────────────

function YesterdayTab({ date, latest }: { date: string; latest: LatestSummary | null }) {
  const { t, fmtDate } = useT()
  const forecast = useFetch<ForecastJSON>(`${BASE}forecast/${date}.json`)
  const alerts   = useFetch<AlertsJSON>(`${BASE}alerts/${date}.json`)
  const actual   = useFetch<ActualJSON>(`${BASE}actual/${date}.json`)

  const loading = forecast.loading || alerts.loading || actual.loading

  return (
    <div className="tab-content">
      <div className="date-header">
        <h2>{fmtDate(date)}</h2>
        <p>{t.latestDataSubtitle}</p>
      </div>

      {loading && <div className="loading">{t.loading}</div>}

      {!loading && (
        <>
          {latest && <ActualPeakCard s={latest} />}
          {alerts.data && <AlertsList alerts={alerts.data} />}

          {forecast.data?.availability === 'not_yet_available' && (
            <div className="card"><span className="badge info">{t.insufficientData}</span></div>
          )}

          {forecast.data && forecast.data.series.length > 0 && (
            <ForecastChart forecast={forecast.data.series} actual={actual.data?.series} showBands={true} />
          )}

          {!forecast.data && (
            <div className="card empty-msg">{t.noForecastData}</div>
          )}
        </>
      )}
    </div>
  )
}

// ── Forecast Tab ──────────────────────────────────────────────────────────────

function ForecastTab({ date, summary, showBands = false }: { date: string | null; summary: ForecastSummary | null; showBands?: boolean }) {
  const { t, fmtDate } = useT()
  const forecast = useFetch<ForecastJSON>(date ? `${BASE}forecast/${date}.json` : null)
  const actual   = useFetch<ActualJSON>(date ? `${BASE}actual/${date}.json` : null)
  const alerts   = useFetch<AlertsJSON>(date ? `${BASE}alerts/${date}.json` : null)

  if (!date) {
    return <div className="tab-content empty-msg">{t.noData}</div>
  }

  const loading = forecast.loading || actual.loading || alerts.loading

  const hasTepco = actual.data?.series.some(p => p.tepcoForecastMw != null) ?? false
  const hasActual = actual.data?.series.some(p => p.actualMw != null) ?? false
  const subtitle = hasActual ? t.latestDataSubtitle : t.forecastSubtitle

  return (
    <div className="tab-content">
      <div className="date-header">
        <h2>{fmtDate(date)}</h2>
        <p>{subtitle}</p>
      </div>

      {loading && <div className="loading">{t.loading}</div>}

      {!loading && (
        <>
          {hasTepco && actual.data && summary
            ? <TodayPeakCard actual={actual.data} forecast={forecast.data?.series} severity={summary.severity} peakTempC={summary.peakTempC} />
            : summary && <ForecastPeakCard s={summary} forecast={forecast.data?.series} actual={actual.data?.series} />
          }
          {alerts.data && <AlertsList alerts={alerts.data} />}

          {forecast.data?.availability === 'not_yet_available' && (
            <div className="card">
              <span className="badge info">{t.insufficientData}</span>
              {forecast.data.message && (
                <p style={{ marginTop: 8, fontSize: 13, color: 'var(--text-secondary)' }}>{forecast.data.message}</p>
              )}
            </div>
          )}

          {forecast.data && forecast.data.series.length > 0 && (
            <ForecastChart forecast={forecast.data.series} actual={actual.data?.series} showBands={showBands} />
          )}

          {!forecast.data && (
            <div className="card empty-msg">{t.noForecastData}</div>
          )}
        </>
      )}
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

interface AppProps {
  locale: Locale
  setLocale: (l: Locale) => void
}

export default function App({ locale, setLocale }: AppProps) {
  const { data: status, loading, error } = useFetch<StatusJSON>(`${BASE}status.json`)
  const [activeTab, setActiveTab] = useState<TabId>('today')
  const { t } = useT()

  const yesterdayDate = status?.yesterday ?? status?.latest?.date ?? status?.coverageTo ?? null
  const todayDate     = status?.today?.date ?? null
  const tomorrowDate  = status?.tomorrow?.date ?? null

  const tabLabels: Record<TabId, string> = {
    yesterday: t.tabYesterday,
    today: t.tabToday,
    tomorrow: t.tabTomorrow,
    validation: t.tabValidation,
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="inner">
          <h1>Tokyo Grid EMS</h1>
          <span className="subtitle">{t.appSubtitle}</span>
          <div className="spacer" />
          <div className="lang-switcher">
            {(Object.keys(LOCALE_LABELS) as Locale[]).map(l => (
              <button
                key={l}
                className={`lang-btn${locale === l ? ' active' : ''}`}
                onClick={() => setLocale(l)}
              >
                {LOCALE_LABELS[l]}
              </button>
            ))}
          </div>
        </div>
      </header>

      {loading && <div className="loading">{t.loading}</div>}
      {error && <div className="error-msg">{t.failedLoad}: {error}</div>}

      {status && (
        <>
          <StatusBar status={status} />

          <nav className="tabs">
            <div className="inner">
            {(() => {
              const yesterdaySev = usageSeverity(status.latest?.peakUsagePct)
              return (['yesterday', 'today', 'tomorrow', 'validation'] as TabId[]).map(tab => (
                <button
                  key={tab}
                  className={`tab-btn${activeTab === tab ? ' active' : ''}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tabLabels[tab]}
                  {tab === 'yesterday' && yesterdaySev && (
                    <>&nbsp;<span className={`badge ${yesterdaySev}`} style={{ fontSize: 10, padding: '1px 5px' }}>
                      {yesterdaySev === 'critical' ? t.severityCritical : t.severityWarning}
                    </span></>
                  )}
                  {tab === 'today' && status.today && status.today.severity !== 'info' && (
                    <>&nbsp;<span className={`badge ${status.today.severity}`} style={{ fontSize: 10, padding: '1px 5px' }}>
                      {status.today.severity === 'critical' ? t.severityCritical : t.severityWarning}
                    </span></>
                  )}
                  {tab === 'tomorrow' && status.tomorrow && status.tomorrow.severity !== 'info' && (
                    <>&nbsp;<span className={`badge ${status.tomorrow.severity}`} style={{ fontSize: 10, padding: '1px 5px' }}>
                      {status.tomorrow.severity === 'critical' ? t.severityCritical : t.severityWarning}
                    </span></>
                  )}
                </button>
              ))
            })()}
            </div>
          </nav>

          <main>
            {activeTab === 'yesterday' && yesterdayDate
              ? <YesterdayTab date={yesterdayDate} latest={status.latest} />
              : activeTab === 'yesterday'
                ? <div className="tab-content empty-msg">{t.noHistoricalData}</div>
                : null
            }
            {activeTab === 'today' && (
              <ForecastTab date={todayDate} summary={status.today} showBands={true} />
            )}
            {activeTab === 'tomorrow' && (
              <ForecastTab date={tomorrowDate} summary={status.tomorrow} showBands={true} />
            )}
            {activeTab === 'validation' && (
              <ValidationPanel baseUrl={BASE} />
            )}
          </main>
        </>
      )}
    </div>
  )
}
