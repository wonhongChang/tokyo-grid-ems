import type { AlertEvent, AlertsJSON, Severity } from '../types'
import { useT } from '../i18n'

interface Props { alerts: AlertsJSON }

function SeverityBadge({ sev }: { sev: Severity }) {
  const { t } = useT()
  const label = sev === 'critical' ? t.criticalBadge : sev === 'warning' ? t.warningBadge : t.infoBadge
  return <span className={`badge ${sev}`}>{label}</span>
}

function fmtTime(iso: string) { return iso.substring(11, 16) }

function AlertItem({ event }: { event: AlertEvent }) {
  const { t } = useT()
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
  return (
    <li className="alert-item">
      <SeverityBadge sev={event.severity} />
      <div className="alert-item-body">
        <div className="alert-item-type">{typeMap[event.type] ?? event.type}</div>
        <div className="alert-item-time">{fmtTime(event.startAt)} – {fmtTime(event.endAt)}</div>
        <div className="alert-item-reason">{event.reason}</div>
        <div className="alert-item-metric">{t.metricLabel}: {metricMap[event.metric] ?? event.metric}</div>
      </div>
    </li>
  )
}

export function AlertsList({ alerts }: Props) {
  const { t } = useT()
  const { summary, events } = alerts

  return (
    <div className="card">
      <div className="card-title">{t.alertEvents}</div>
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
