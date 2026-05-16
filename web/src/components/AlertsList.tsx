import type { AlertEvent, AlertsJSON, Severity } from '../types'
import { useT, type Locale } from '../i18n'
import { formatPower } from '../units'

interface Props { alerts: AlertsJSON }

function SeverityBadge({ sev }: { sev: Severity }) {
  const { t } = useT()
  const label = sev === 'critical' ? t.criticalBadge : sev === 'warning' ? t.warningBadge : t.infoBadge
  return <span className={`badge ${sev}`}>{label}</span>
}

function fmtTime(iso: string) { return iso.substring(11, 16) }

function fmtPct(value: number): string {
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`
}

function reserveRiskCriteria(locale: Locale) {
  if (locale === 'en') {
    return {
      title: 'Usage thresholds',
      warning: 'Warning: 92% to under 97%',
      critical: 'Danger: 97% or higher',
    }
  }
  if (locale === 'ja') {
    return {
      title: '使用率基準',
      warning: '警告: 92%以上97%未満',
      critical: '危険: 97%以上',
    }
  }
  return {
    title: '사용률 기준',
    warning: '경고: 92% 이상 97% 미만',
    critical: '위험: 97% 이상',
  }
}

function labelsFor(locale: Locale) {
  if (locale === 'en') {
    return {
      threshold: 'Threshold',
      reserveRange: 'Risk range',
      upperBand: 'Upper band',
      lowerBand: 'Lower band',
      averageResidual: 'Avg residual',
    }
  }
  if (locale === 'ja') {
    return {
      threshold: '基準',
      reserveRange: 'リスク区分',
      upperBand: '上限',
      lowerBand: '下限',
      averageResidual: '平均残差',
    }
  }
  return {
    threshold: '기준',
    reserveRange: '위험 구간',
    upperBand: '상한',
    lowerBand: '하한',
    averageResidual: '평균 오차',
  }
}

function reserveRiskRange(severity: Severity, locale: Locale): string {
  if (severity === 'critical') {
    if (locale === 'en') return '97% or higher'
    if (locale === 'ja') return '97%以上'
    return '97% 이상'
  }
  if (locale === 'en') return '92% to under 97%'
  if (locale === 'ja') return '92%以上97%未満'
  return '92% 이상 97% 미만'
}

function localizedReason(event: AlertEvent, locale: Locale): string {
  if (event.type === 'reserve_risk' && event.usagePct != null && event.thresholdPct != null) {
    const range = reserveRiskRange(event.severity, locale)
    if (locale === 'en') {
      return event.severity === 'critical'
        ? `Grid usage entered the danger range (${range}).`
        : `Grid usage entered the warning range (${range}).`
    }
    if (locale === 'ja') {
      return event.severity === 'critical'
        ? `使用率が危険域（${range}）に入りました。`
        : `使用率が警告域（${range}）に入りました。`
    }
    return event.severity === 'critical'
      ? `전력 사용률이 위험 구간(${range})에 들어갔습니다.`
      : `전력 사용률이 경고 구간(${range})에 들어갔습니다.`
  }

  if (event.type === 'drift' && event.residualAvgMw != null) {
    const above = event.residualAvgMw >= 0
    if (locale === 'en') {
      return `Actual demand stayed ${above ? 'above' : 'below'} the model forecast.`
    }
    if (locale === 'ja') {
      return `実績需要がモデル予測を継続して${above ? '上回りました' : '下回りました'}。`
    }
    return `실제 수요가 모델 예측보다 계속 ${above ? '높게' : '낮게'} 나타났습니다.`
  }

  if (event.type === 'spike') {
    if (locale === 'en') return 'Actual demand moved above the forecast range.'
    if (locale === 'ja') return '実績需要が予測範囲を上回りました。'
    return '실제 수요가 예측 범위를 웃돌았습니다.'
  }

  if (event.type === 'drop') {
    if (locale === 'en') return 'Actual demand moved below the forecast range.'
    if (locale === 'ja') return '実績需要が予測範囲を下回りました。'
    return '실제 수요가 예측 범위보다 낮았습니다.'
  }

  return event.reason
}

function AlertItem({ event }: { event: AlertEvent }) {
  const { t, locale } = useT()
  const typeMap: Record<string, string> = {
    reserve_risk: t.eventReserveRisk,
    spike: t.eventSpike,
    drop: t.eventDrop,
    drift: t.eventDrift,
  }
  const metricMap: Record<string, string> = {
    usage_pct:    t.metricUsagePct,
    actual_mw:    t.metricActualMw,
    residual_mw:  t.metricResidualMw,
  }
  const localLabels = labelsFor(locale)
  const chips: Array<{ label: string; value: string }> = []

  if (event.type === 'reserve_risk') {
    if (event.usagePct != null) chips.push({ label: t.metricUsagePct, value: fmtPct(event.usagePct) })
    chips.push({ label: localLabels.reserveRange, value: reserveRiskRange(event.severity, locale) })
    if (event.supplyMw != null) chips.push({ label: t.supply, value: formatPower(event.supplyMw, locale) })
  } else if (event.type === 'drift') {
    if (event.residualAvgMw != null) chips.push({ label: localLabels.averageResidual, value: formatPower(event.residualAvgMw, locale) })
    if (event.thresholdMw != null) chips.push({ label: localLabels.threshold, value: formatPower(event.thresholdMw, locale) })
  } else if (event.type === 'spike' || event.type === 'drop') {
    if (event.actualMw != null) chips.push({ label: t.actual, value: formatPower(event.actualMw, locale) })
    if (event.expectedMw != null) chips.push({ label: t.modelForecast, value: formatPower(event.expectedMw, locale) })
    const band = event.type === 'spike'
      ? event.interval?.p99Upper ?? event.interval?.p95Upper
      : event.interval?.p99Lower ?? event.interval?.p95Lower
    if (band != null) {
      chips.push({
        label: event.type === 'spike' ? localLabels.upperBand : localLabels.lowerBand,
        value: formatPower(band, locale),
      })
    }
  }

  return (
    <li className="alert-item">
      <SeverityBadge sev={event.severity} />
      <div className="alert-item-body">
        <div className="alert-item-type">{typeMap[event.type] ?? event.type}</div>
        <div className="alert-item-time">{fmtTime(event.startAt)} {t.through} {fmtTime(event.endAt)}</div>
        <div className="alert-item-reason">{localizedReason(event, locale)}</div>
        {chips.length > 0 ? (
          <div className="alert-metrics">
            {chips.map(chip => (
              <span className="alert-metric-chip" key={`${chip.label}:${chip.value}`}>
                <span>{chip.label}</span>
                <strong>{chip.value}</strong>
              </span>
            ))}
          </div>
        ) : (
          <div className="alert-item-metric">{t.metricLabel}: {metricMap[event.metric] ?? event.metric}</div>
        )}
      </div>
    </li>
  )
}

export function AlertsList({ alerts }: Props) {
  const { t, locale } = useT()
  const { summary, events } = alerts
  const criteria = reserveRiskCriteria(locale)

  return (
    <div className="card">
      <div className="card-title">{t.alertEvents}</div>
      <div className="reserve-risk-criteria" aria-label={criteria.title}>
        <span className="reserve-risk-criteria-title">{criteria.title}</span>
        <span className="badge warning">{criteria.warning}</span>
        <span className="badge critical">{criteria.critical}</span>
      </div>
      <div className="alert-summary" style={{ marginBottom: events.length > 0 ? 12 : 0 }}>
        {summary.critical > 0 && <span className="badge critical">{summary.critical} {t.severityCritical}</span>}
        {summary.warning > 0 && <span className="badge warning">{summary.warning} {t.severityWarning}</span>}
        {summary.info > 0 && <span className="badge info">{summary.info} {t.severityInfo}</span>}
        {summary.critical === 0 && summary.warning === 0 && summary.info === 0 && (
          <span className="badge ok">{t.noEvents}</span>
        )}
      </div>
      {events.length > 0 && (
        <ul className="alert-list">
          {events.map(e => <AlertItem key={e.id} event={e} />)}
        </ul>
      )}
    </div>
  )
}
