import { useState } from 'react'
import { useFetch } from './hooks/useFetch'
import { StatusBar } from './components/StatusBar'
import { ForecastChart } from './components/ForecastChart'
import { AlertsList } from './components/AlertsList'
import { useT, LOCALE_LABELS, type Locale } from './i18n'
import type { StatusJSON, ForecastJSON, AlertsJSON, ActualJSON, LatestSummary, ForecastSummary, Severity } from './types'

const BASE = import.meta.env.BASE_URL

type TabId = 'yesterday' | 'today' | 'tomorrow'

// ── Helpers ──────────────────────────────────────────────────────────────────

const MW_TO_MANKW = 10

function fmtTime(iso: string) { return iso.substring(11, 16) }
function fmtMankw(mw: number) { return Math.round(mw / MW_TO_MANKW).toLocaleString() }

function SeverityBadge({ sev }: { sev: Severity }) {
  const { t } = useT()
  const label = sev === 'critical' ? t.criticalBadge : sev === 'warning' ? t.warningBadge : t.infoBadge
  return <span className={`badge ${sev}`}>{label}</span>
}

// ── Peak Cards ────────────────────────────────────────────────────────────────

function ActualPeakCard({ s }: { s: LatestSummary }) {
  const { t } = useT()
  const pct = s.peakUsagePct
  const sev: Severity | null = pct != null ? (pct >= 95 ? 'critical' : pct >= 90 ? 'warning' : null) : null
  return (
    <div className="card">
      {sev && <div className="card-title"><SeverityBadge sev={sev} /></div>}
      <div className="peak-grid">
        {s.peakActualMw != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakActual}</div>
            <div>
              <span className="peak-stat-value">{fmtMankw(s.peakActualMw)}</span>
              <span className="peak-stat-unit"> 万kW</span>
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
              <span className="peak-stat-value">{fmtMankw(s.peakSupplyMw)}</span>
              <span className="peak-stat-unit"> 万kW</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function ForecastPeakCard({ s }: { s: ForecastSummary }) {
  const { t } = useT()
  return (
    <div className="card">
      <div className="card-title"><SeverityBadge sev={s.severity} /></div>
      <div className="peak-grid">
        {s.peakForecastMw != null && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakForecast}</div>
            <div>
              <span className="peak-stat-value">{fmtMankw(s.peakForecastMw)}</span>
              <span className="peak-stat-unit"> 万kW</span>
            </div>
            {s.peakForecastAt && <div className="peak-stat-sub">@ {fmtTime(s.peakForecastAt)}</div>}
          </div>
        )}
      </div>
    </div>
  )
}

function TodayPeakCard({ actual, severity }: { actual: ActualJSON; severity: Severity }) {
  const { t } = useT()
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
      <div className="card-title"><SeverityBadge sev={severity} /></div>
      <div className="peak-grid">
        {tPeak && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakTepcoForecast}</div>
            <div>
              <span className="peak-stat-value">{fmtMankw(tPeak.tepcoForecastMw!)}</span>
              <span className="peak-stat-unit"> 万kW</span>
            </div>
            <div className="peak-stat-sub">@ {fmtTime(tPeak.ts)}</div>
          </div>
        )}
        {aPeak && (
          <div className="peak-stat">
            <div className="peak-stat-label">{t.peakActual}</div>
            <div>
              <span className="peak-stat-value">{fmtMankw(aPeak.actualMw!)}</span>
              <span className="peak-stat-unit"> 万kW</span>
            </div>
            <div className="peak-stat-sub">@ {fmtTime(aPeak.ts)}</div>
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
            ? <TodayPeakCard actual={actual.data} severity={summary.severity} />
            : summary && <ForecastPeakCard s={summary} />
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
              const yPct = status.latest?.peakUsagePct ?? null
              const yesterdaySev: Severity | null = yPct != null
                ? (yPct >= 95 ? 'critical' : yPct >= 90 ? 'warning' : null)
                : null
              return (['yesterday', 'today', 'tomorrow'] as TabId[]).map(tab => (
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
                  {tab === 'today' && status.today && (
                    <>&nbsp;<span className={`badge ${status.today.severity}`} style={{ fontSize: 10, padding: '1px 5px' }}>
                      {status.today.severity === 'critical' ? t.severityCritical : status.today.severity === 'warning' ? t.severityWarning : t.severityInfo}
                    </span></>
                  )}
                  {tab === 'tomorrow' && status.tomorrow && (
                    <>&nbsp;<span className={`badge ${status.tomorrow.severity}`} style={{ fontSize: 10, padding: '1px 5px' }}>
                      {status.tomorrow.severity === 'critical' ? t.severityCritical : status.tomorrow.severity === 'warning' ? t.severityWarning : t.severityInfo}
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
          </main>
        </>
      )}
    </div>
  )
}
