import { useState } from 'react'
import { useFetch } from './hooks/useFetch'
import { StatusBar } from './components/StatusBar'
import { ForecastChart } from './components/ForecastChart'
import { AlertsList } from './components/AlertsList'
import { ValidationPanel } from './components/ValidationPanel'
import { OpsReportPanel } from './components/OpsReportPanel'
import { useT, LOCALE_LABELS, type Locale } from './i18n'
import { formatPowerParts } from './units'
import { isObservedActual, peakUsageMetrics, type UsageMetric, type PeakUsageMetrics } from './usageMetrics'
import type {
  StatusJSON, ForecastJSON, AlertsJSON, ActualJSON,
  LatestSummary, ForecastSummary, Severity, ForecastPoint, ActualPoint,
} from './types'

const BASE = import.meta.env.BASE_URL
const USAGE_WARNING_PCT = 92
const USAGE_CRITICAL_PCT = 97

type TabId = 'yesterday' | 'today' | 'tomorrow' | 'validation' | 'opsReport'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(iso: string) { return iso.substring(11, 16) }

function fmtPct(value: number): string {
  return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)
}

function WeatherSourceLabel() {
  return <div className="peak-stat-sub peak-stat-source">JMA</div>
}

function usageMetricLabels(locale: Locale) {
  if (locale === 'en') return {
    observed: 'Peak observed usage', tepco: 'TEPCO estimated peak usage',
    model: 'Model estimated peak usage', modelDetails: 'Model usage estimate',
    tepcoSupply: 'Supply at TEPCO usage peak', modelSupply: 'Supply at model usage peak',
  }
  if (locale === 'ja') return {
    observed: '最大実績使用率', tepco: 'TEPCO予測最大使用率',
    model: 'モデル予測最大使用率', modelDetails: 'モデルの予測使用率',
    tepcoSupply: 'TEPCO使用率ピーク時の供給力', modelSupply: 'モデル使用率ピーク時の供給力',
  }
  return {
    observed: '최대 실측 사용률', tepco: 'TEPCO 예상 최대 사용률',
    model: '모델 예상 최대 사용률', modelDetails: '모델 예상 사용률',
    tepcoSupply: 'TEPCO 사용률 피크 시점 공급력', modelSupply: '모델 사용률 피크 시점 공급력',
  }
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

function UsageStat({ metric, label }: { metric: UsageMetric | null; label: string }) {
  return (
    <div className="peak-stat">
      <div className="peak-stat-label">{label}</div>
      <div>
        <span className="peak-stat-value">{metric ? fmtPct(metric.usagePct) : '-'}</span>
        {metric && <span className="peak-stat-unit"> %</span>}
      </div>
      <div className="peak-stat-sub">{metric ? `@ ${fmtTime(metric.at)}` : '-'}</div>
    </div>
  )
}

function UsageSupplyStat({ metric, label }: { metric: UsageMetric | null; label: string }) {
  return (
    <div className="peak-stat">
      <div className="peak-stat-label">{label}</div>
      <div>
        {metric?.supplyMw != null ? <PowerStatValue mw={metric.supplyMw} /> : <span className="peak-stat-value">-</span>}
      </div>
      <div className="peak-stat-sub">{metric ? `@ ${fmtTime(metric.at)}` : '-'}</div>
    </div>
  )
}

function UsageMetricStats({ metrics, showObserved = false }: { metrics: PeakUsageMetrics; showObserved?: boolean }) {
  const { locale } = useT()
  const labels = usageMetricLabels(locale)
  return (
    <>
      {showObserved && <UsageStat metric={metrics.observed} label={labels.observed} />}
      <UsageStat metric={metrics.tepco} label={labels.tepco} />
      <UsageSupplyStat metric={metrics.tepco} label={labels.tepcoSupply} />
    </>
  )
}

function ModelUsageDetails({ metric }: { metric: UsageMetric | null }) {
  const { locale } = useT()
  const labels = usageMetricLabels(locale)
  return (
    <details className="usage-comparison">
      <summary>{labels.modelDetails}</summary>
      <div className="peak-grid">
        <UsageStat metric={metric} label={labels.model} />
        <UsageSupplyStat metric={metric} label={labels.modelSupply} />
      </div>
    </details>
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
            <WeatherSourceLabel />
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
  const metrics = peakUsageMetrics(s.date, forecast, actual)
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
        <UsageMetricStats metrics={metrics} />
        {s.peakTempC != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakTemp}</div>
            <div>
              <span className="peak-stat-value">{s.peakTempC}</span>
              <span className="peak-stat-unit"> °C</span>
            </div>
            <WeatherSourceLabel />
          </div>
        )}
      </div>
      <ModelUsageDetails metric={metrics.model} />
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
  const metrics = peakUsageMetrics(actual.date, forecast, actual.series)
  const tepcoPoints = actual.series.filter(p => p.tepcoForecastMw != null)
  const tPeak = tepcoPoints.length > 0
    ? tepcoPoints.reduce((a, b) => b.tepcoForecastMw! > a.tepcoForecastMw! ? b : a)
    : null
  const actualPoints = actual.series.filter(isObservedActual)
  const aPeak = actualPoints.length > 0
    ? actualPoints.reduce((a, b) => b.actualMw! > a.actualMw! ? b : a)
    : null
  return (
    <div className="card">
      {severity !== 'info' && <div className="card-title"><SeverityBadge sev={severity} /></div>}
      <div className="peak-grid peak-grid-today">
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
        <UsageMetricStats metrics={metrics} showObserved />
        {peakTempC != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakTemp}</div>
            <div>
              <span className="peak-stat-value">{peakTempC}</span>
              <span className="peak-stat-unit"> °C</span>
            </div>
            <WeatherSourceLabel />
          </div>
        )}
      </div>
      <ModelUsageDetails metric={metrics.model} />
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
    opsReport: t.tabOpsReport,
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
              return (['yesterday', 'today', 'tomorrow', 'validation', 'opsReport'] as TabId[]).map(tab => (
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
            {activeTab === 'opsReport' && (
              <OpsReportPanel baseUrl={BASE} />
            )}
          </main>
        </>
      )}
    </div>
  )
}
