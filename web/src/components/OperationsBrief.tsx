import { createElement, type MouseEvent, type ReactNode } from 'react'
import type { AIDailyReport } from '../types'
import type { Locale } from '../i18n'
import { byId, chartSlots, children, isTag, verifiedAdvice, type BriefNode as Node, type Slot, type Tag } from '../briefEvidence'
import { briefCopy } from '../briefCopy'
import { BriefDayChart, fmt, hourText } from './BriefDayChart'
import './operationsBrief.css'

const tags = new Set('header small h1 h2 section p b details summary div table thead tbody tr th td a dl dt dd code'.split(' '))
const prefix = 'ops-v8-'

function validAttribute(tag: string, name: string, value: unknown): boolean {
  if (typeof value !== 'string') return false
  switch (name) {
    case 'id': case 'data-id': case 'data-field': return /^[A-Za-z0-9_:/→.-]{1,180}$/.test(value)
    case 'class': return value === 'scroll' || value === 'note'
    case 'scope': return tag === 'th' && value === 'row'
    case 'tabindex': return (tag === 'tr' && value === '-1') || (tag === 'div' && value === '0')
    case 'href': return tag === 'a' && /^#row-[A-Za-z0-9_:/→.-]{1,160}$/.test(value)
    default: return false
  }
}

export function briefNodes(report: AIDailyReport, date: string | null, locale: string): Node[] | null {
  const view = report.operationsBrief
  if (import.meta.env.VITE_OPS_REPORT_LAYOUT === 'legacy' || !view || view.version !== 'tokyo-grid-ops/v8'
    || report.date !== date || view.date !== date || report.language !== locale || view.language !== locale
    || !view.fingerprint || view.fingerprint !== report.inputSnapshot?.fingerprint || !Array.isArray(view.nodes)) return null
  const ids = new Set<string>()
  let count = 0
  function valid(n: unknown, depth: number): boolean {
    if (++count > 35000 || depth > 16) return false
    if (typeof n === 'string') return true
    if (!Array.isArray(n) || !tags.has(n[0]) || !n[1] || typeof n[1] !== 'object' || Array.isArray(n[1])) return false
    const attrs = n[1]
    if (!Object.entries(attrs).every(([key, value]) => validAttribute(n[0], key, value))) return false
    if (attrs.id) {
      if (ids.has(attrs.id)) return false
      ids.add(attrs.id)
    }
    return n.slice(2).every(child => valid(child, depth + 1))
  }
  return view.nodes.every(n => valid(n, 0)) && ids.has('brief') && ids.has('next') && ids.has('coverage')
    ? view.nodes as Node[] : null
}

function element(n: Node, key: number): ReactNode {
  if (typeof n === 'string') return n
  const [tag, attrs, ...children] = n
  const props: Record<string, string | number> = { key }
  for (const [name, value] of Object.entries(attrs)) {
    if (name === 'id') props.id = prefix + value
    else if (name === 'href') props.href = '#' + prefix + value.slice(1)
    else if (name === 'tabindex') props.tabIndex = Number(value)
    else if (name === 'class') props.className = value
    else props[name] = value
  }
  return createElement(tag, props, ...children.map(element))
}

const groups = {
  ko: ['시간대별 수요와 정확도','예측 수정과 보정 단계','구간·표본·진단 근거'],
  en: ['Demand and accuracy by hour','Forecast revisions and calibration','Intervals, samples and diagnostics'],
  ja: ['時間帯別の需要と予測精度','予測の更新と補正の内訳','予測区間・比較対象・診断結果'],
}
const groupIds = [
  ['rank','peak','band','point','change','shape_daily','daily','repeat'],
  ['vintage','stages','history','check','control'],
]

export function OperationsBrief({ nodes, locale, report }: { nodes: Node[]; locale: Locale; report: AIDailyReport }) {
  const w=briefCopy[locale], v=report.operationsBrief!, g=report.generator
  const section=byId(nodes,'brief')!, next=byId(nodes,'next')!, research=byId(nodes,'research')
  const repeat=byId(nodes,'repeat'), advice=verifiedAdvice(nodes,report)
  const slots=chartSlots(nodes,report), points=slots?.filter((s):s is Slot=>s!==null) ?? []
  const full=points.length===24 && !!byId(nodes,'row-daily/day')
  const ordered=[...points].sort((a,b)=>Math.abs(b.error)-Math.abs(a.error)||a.hour-b.hour)
  const worst=ordered[0], best=[...points].sort((a,b)=>Math.abs(a.error)-Math.abs(b.error)||a.hour-b.hour)[0]
  const peaks=points.filter(s=>byId(nodes,'row-peak/'+hourText(s.hour)))
  const peak=peaks[0], times=peaks.map(r=>hourText(r.hour)).join(', ')
  const direction=(s:Slot)=>s.error<0?w.under:s.error>0?w.over:w.exact
  const summary=report.performance
  const verdict=({model_better:w.publishedWins,tepco_better:w.utilityWins,close:w.close,mixed:w.mixed} as Record<string,string>)[summary.verdict??'']
  const maeOK=full && summary.comparableHours===points.length && typeof summary.modelMaeMw==='number' &&
    Number.isFinite(summary.modelMaeMw) && typeof summary.tepcoMaeMw==='number' && Number.isFinite(summary.tepcoMaeMw)
  const textTime=Date.parse(report.generatedAt)
  const created=Number.isFinite(textTime)?new Date(textTime).toLocaleString(locale,{timeZone:'Asia/Tokyo',hour12:false})+' JST':w.unknown
  const meta=g.advisory
  const states=['selected','abstained','not_requested','no_eligible_evidence','failed','input_unavailable'] as const
  const status=states.find(s=>s===v.advisoryStatus)??'unavailable'
  const attempted=meta ? meta.attempted : status==='unavailable'?null:['selected','abstained','failed'].includes(status)
  const model=meta?.model ?? (g.provider==='openai'?g.model:null)
  const score=v.hourlyComparison
  const h1=score && score.sampleTargets>0 && score.issueIds?.length===score.sampleTargets && Number.isFinite(score.h1MaeMw) && Number.isFinite(score.championMaeMw)
  const archived=nodes.filter(isTag).filter(n=>n[0]==='details'&&!['luna','research','provenance'].includes(n[1].id))
  const buckets=[archived.filter(n=>groupIds[0].includes(n[1].id)),archived.filter(n=>groupIds[1].includes(n[1].id)),
    archived.filter(n=>!groupIds.some(ids=>ids.includes(n[1].id)))]
  const pattern=repeat && children(section).filter(isTag).find(n=>n[0]==='p'&&typeof n[2]==='string'&&/^\d{2}-\d{2}/.test(n[2]))
  const original=children(section).filter(n=>!isTag(n)||n[1].id!=='next')
  function showEvidence(event: MouseEvent<HTMLElement>) {
    const link=(event.target as Element).closest('a')
    if (!link || !link.hash.startsWith('#'+prefix+'row-')) return
    const row=document.getElementById(decodeURIComponent(link.hash.slice(1)))
    if (!row || !event.currentTarget.contains(row)) return
    event.preventDefault()
    for(let box=row.closest('details');box;box=box.parentElement?.closest('details')??null) box.open=true
    row.focus({preventScroll:true});row.scrollIntoView({block:'center'})
  }
  const tail=(node:Tag)=>children(node).filter(n=>!isTag(n)||n[0]!=='summary').map(element)
  const check=children(next).filter(n=>!isTag(n)||n[0]!=='b').map(n=>typeof n==='string'?n.replace(/^\s*·\s*/,''):n)
  return <article lang={locale} className="ops-v8" data-report-layout="v8" onClick={showEvidence}>
    <header className="brief-heading"><div className="brief-dateline"><time dateTime={report.date}>{report.date}</time> · JST</div>
      <h1>{w.title}</h1><div className="brief-byline">{w.created}: {created} · {w.observed}: {w[v.actualStatus??'unknown']}</div>
    </header>
    <section id="ops-v8-brief" aria-label={w.insights}>
      {maeOK && <><dl className="brief-metrics">
        {peak && <div><dt>{w.peak}</dt><dd>{fmt(peak.actual,locale)} <small>MW</small></dd><dd className="brief-metric-sub">{times} JST</dd></div>}
        <div><dt>Champion · MAE</dt><dd>{fmt(summary.modelMaeMw!,locale)} <small>MW</small></dd><dd className="brief-metric-sub">{w.mae}</dd></div>
        <div><dt>TEPCO · MAE</dt><dd>{fmt(summary.tepcoMaeMw!,locale)} <small>MW</small></dd><dd className="brief-metric-sub">{w.mae}</dd></div>
        <div><dt>{w.largest}</dt><dd>{fmt(worst.error,locale,true)} <small>MW</small></dd><dd className="brief-metric-sub">{hourText(worst.hour)} · {direction(worst)}</dd></div>
      </dl><p className="brief-method"><b>{w.fullScope} · {w.hours} {points.length}/24{verdict?' · '+verdict:''}</b><br/>{w.compare}</p></>}
      {!maeOK && original.map(element)}
      {pattern && maeOK && <div className="brief-finding"><strong>{w.repeat}</strong>{children(pattern).map(element)}</div>}
      <div className="brief-next" id="ops-v8-next"><strong>{w.follow}</strong><span>{check.map(element)}</span></div>
    </section>
    {slots && <BriefDayChart slots={slots} worst={worst} best={best} locale={locale}/>}
    {advice && <section className="brief-reading" id="ops-v8-luna"><h2>{w.reading}</h2>{tail(advice)}</section>}
    {h1 && <section className="brief-reading"><h2>SD-H1-P50</h2><p>{w.h1} (n={score.sampleTargets}): MAE · SD-H1-P50 {fmt(score.h1MaeMw,locale)} MW / Champion {fmt(score.championMaeMw,locale)} MW</p></section>}
    {research && <section className="brief-research"><h2>{w.research}</h2>{element(research,0)}</section>}
    <section className="brief-support"><h2>{w.more}</h2>
      {maeOK && <details><summary>{w.overview}</summary>{original.map(element)}</details>}
      {buckets.map((items,i)=>items.length>0 && <details className="brief-group" key={i}><summary>{groups[locale][i]}</summary>{items.map(element)}</details>)}
    </section>
    <footer><details className="brief-generation"><summary>{w.source}</summary>
      <dl>{[[w.body,'Python'],[w.created,created],[w.model,model??w.unknown],[w.attempt,attempted===true?w.yes:attempted===false?w.no:w.unavailable],
        [w.selection,w[status]]].map(([k,val])=><div key={k}><dt>{k}</dt><dd>{val}</dd></div>)}</dl>
      {byId(nodes,'provenance') && element(byId(nodes,'provenance')!,0)}
      <code>{v.fingerprint}</code>
      <p><a href={import.meta.env.BASE_URL+'reports/ai/daily/'+locale+'/'+report.date+'.json'}>JSON</a>
        {' · '}<a href={'https://github.com/wonhongChang/tokyo-grid-ems/blob/main/docs/'+locale+'/review-bundle-cli.md'}>Review Bundle CLI</a></p>
    </details>{advice && <small className="brief-credit">{w.credit}</small>}</footer>
  </article>
}
