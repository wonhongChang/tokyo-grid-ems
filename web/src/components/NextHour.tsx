import { useEffect, useState } from 'react'
import { useT } from '../i18n'
import type { HourlyIssue, StatusJSON } from '../types'

const stamp = (ts: string) => ts.slice(0, 10) + ' ' + ts.slice(11, 19)
const windowText = (r: HourlyIssue) => r.targetStart.slice(0, 10) + ' ' + r.targetStart.slice(11, 16) + ' – '
  + (r.targetStart.slice(0, 10) === r.targetEnd.slice(0, 10) ? '' : r.targetEnd.slice(0, 10) + ' ') + r.targetEnd.slice(11, 16) + ' JST'

export function NextHour({ data, date }: { data: StatusJSON['hourlyNext']; date: string }) {
  const { t, locale } = useT()
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const sync = () => setNow(Date.now())
    const edges = (data?.rows ?? []).flatMap(r => [Date.parse(r.confirmedAt ?? ''), Date.parse(r.targetStart)]).filter(n => n > Date.now())
    const timer = edges.length ? window.setTimeout(sync, Math.min(...edges) - Date.now() + 10) : undefined
    document.addEventListener('visibilitychange', sync)
    return () => { window.clearTimeout(timer); document.removeEventListener('visibilitychange', sync) }
  }, [data, now])
  if (!data || data.model !== 'SD-H1-P50') return null
  const tr = t.hourly
  const mw = (x: number) => x.toLocaleString(locale, { maximumFractionDigits: 1 }) + ' MW'
  const rows = data.rows.filter(r => r.targetStart.slice(0, 10) === date).sort((a,b) => b.issuedAt.localeCompare(a.issuedAt))
  const active = rows.find(r => r.confirmedAt && Date.parse(r.confirmedAt) <= now && now < Date.parse(r.targetStart))
  const health = data.health?.runAt.slice(0, 10) === date ? data.health : null
  const matched = new Map<string, HourlyIssue>()
  for (const r of rows) if (r.confirmedAt && r.actualMw != null && !matched.has(r.targetStart)) matched.set(r.targetStart, r)
  const score = (field: 'forecastMw' | 'championMw') => mw([...matched.values()].reduce((sum,r) => sum + Math.abs(r[field]-r.actualMw!),0)/matched.size)
  return <section className="card next-hour">
    <header><h3>{tr.title}</h3><small>SD-H1-P50</small></header>
    {active ? <><strong>{mw(active.forecastMw)}</strong><span>Champion {mw(active.championMw)}</span><p>{windowText(active)}</p>
      <p>{tr.issued}: {stamp(active.issuedAt)} JST · {tr.confirmed}: {stamp(active.confirmedAt!)} JST</p></>
      : <p>{health ? tr.states[health.state] : rows.length ? tr.noActive : tr.empty}
        {health && <> · {stamp(health.runAt)} JST</>}</p>}
    {active && health && health.state !== 'issued' && <p>{tr.states[health.state]} · {stamp(health.runAt)} JST</p>}
    {matched.size > 0 && <p>{tr.comparison} (n={matched.size}): SD-H1-P50 {score('forecastMw')} · Champion {score('championMw')}</p>}
    {rows.length > 0 && <details className="usage-comparison"><summary>{tr.history} ({rows.length})</summary><ul>
      {rows.map(r => <li key={r.id}><b>{windowText(r)}</b><p>{tr.issued}: {stamp(r.issuedAt)} JST</p>
        <p>{r.confirmedAt ? tr.confirmed + ': ' + stamp(r.confirmedAt) + ' JST' : tr.unverified}</p>
        <p>SD-H1-P50 {mw(r.forecastMw)} · Champion {mw(r.championMw)}</p>
        {r.actualMw != null && <p>{tr.actual} ({r.finalized ? tr.final : tr.provisional}): {mw(r.actualMw)}<br/>
          {tr.error}: SD-H1-P50 {mw(Math.abs(r.forecastMw-r.actualMw))} · Champion {mw(Math.abs(r.championMw-r.actualMw))}</p>}</li>)}
    </ul></details>}
  </section>
}
