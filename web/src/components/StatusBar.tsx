import type { StatusJSON, Availability } from '../types'
import { useT } from '../i18n'

interface Props { status: StatusJSON }

function AvailBadge({ av }: { av: Availability }) {
  const { t } = useT()
  if (av === 'ok') return <span className="badge ok">{t.availOk}</span>
  if (av === 'failed') return <span className="badge critical">{t.availFailed}</span>
  return <span className="badge info">{t.availPending}</span>
}

function fmtTs(iso: string) {
  return iso.substring(0, 16).replace('T', ' ') + ' JST'
}

export function StatusBar({ status }: Props) {
  const { t } = useT()
  return (
    <div className="status-bar">
      <div className="inner">
      <div className="status-item">
        <AvailBadge av={status.availability} />
      </div>
      <div className="status-item">
        <span className="status-label">{t.statusUpdated}</span>
        <span className="status-value">{fmtTs(status.lastUpdatedAt)}</span>
      </div>

      {status.missingDays.length > 0 && (
        <div className="status-item">
          <span className="badge warning">{t.statusMissingDays(status.missingDays.length)}</span>
        </div>
      )}
      {status.failedDays.length > 0 && (
        <div className="status-item">
          <span className="badge critical">{t.statusFailedDays(status.failedDays.length)}</span>
        </div>
      )}
      </div>
    </div>
  )
}
