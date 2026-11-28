import { createElement, type MouseEvent, type ReactNode } from 'react'
import type { AIDailyReport } from '../types'
import type { Locale } from '../i18n'
import './operationsBrief.css'

type Node = string | [string, Record<string, string>, ...Node[]]
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

const WORDS = {
  ko: {made:'리포트 작성', actual:'실측', finalized:'확정', provisional:'잠정', unknown:'확정 여부 미기록',
    source:'본문: Python · Luna 근거 선택', selected:'선택됨', abstained:'채택된 근거 없음', not_requested:'호출 안 함',
    no_eligible_evidence:'대상 근거 없음 · 미호출', failed:'호출 또는 응답 검증 실패', input_unavailable:'입력 준비 불가 · 미호출', unavailable:'기록 불충분',
    mae:'MAE는 예측과 실측이 평균 몇 MW 어긋났는지 나타냅니다. Champion과 TEPCO의 최종 공개값을 같은 대상시간에서 비교하며, 발행 시각이나 남은 예측 시간이 같다는 뜻은 아닙니다.',
    h1:'별도 비교: 시간 시작 전 확인된 마지막 발행과 당시 Champion, 동일 확정 실측 기준'},
  en: {made:'Report created', actual:'Actuals', finalized:'finalized', provisional:'provisional', unknown:'finality not recorded',
    source:'Body: Python · Luna evidence selection', selected:'selected', abstained:'no selection accepted', not_requested:'not called',
    no_eligible_evidence:'no eligible evidence; not called', failed:'call or response validation failed', input_unavailable:'input unavailable; not called', unavailable:'not established',
    mae:'MAE is the average distance in MW between forecast and actual demand. The final published Champion and TEPCO values cover the same target hours, not necessarily the same issue times or lead times.',
    h1:'Separate comparison: last confirmed pre-start issue vs its contemporary Champion, on the same finalized actuals'},
  ja: {made:'レポート作成', actual:'実績', finalized:'確定', provisional:'暫定', unknown:'確定状況の記録なし',
    source:'本文：Python · Lunaによる根拠選択', selected:'選択あり', abstained:'採用された根拠なし', not_requested:'呼出しなし',
    no_eligible_evidence:'対象の根拠なし・未呼出し', failed:'呼出しまたは応答検証に失敗', input_unavailable:'入力を準備できず未呼出し', unavailable:'記録不足',
    mae:'MAEは予測と実績のずれの絶対値をMWで平均したものです。ChampionとTEPCOの最終公開値を同じ対象時刻で比較しており、発行時刻や予測リードが等しいとは限りません。',
    h1:'別集計：対象開始前に確認した最後の発行と当時のChampionを、同一の確定実績で比較'},
}

export function OperationsBrief({ nodes, locale, report }: { nodes: Node[]; locale: Locale; report: AIDailyReport }) {
  const w = WORDS[locale], view = report.operationsBrief!
  const allowed = ['selected','abstained','not_requested','no_eligible_evidence','failed','input_unavailable'] as const
  const advisory = allowed.find(s => s === view.advisoryStatus) ?? 'unavailable'
  const stamp = Date.parse(report.generatedAt)
  const created = Number.isFinite(stamp) ? new Date(stamp).toLocaleString(locale,{timeZone:'Asia/Tokyo',hour12:false})+' JST' : '—'
  const meta = w.made+': '+created+' · '+w.actual+': '+(w[view.actualStatus ?? 'unknown'] ?? w.unknown)
  const source = w.source+': '+ w[advisory]
  const score = view.hourlyComparison
  function section(n: Node, i: number): ReactNode {
    if (typeof n === 'string') return n
    if (n[0] === 'header') return element([...n, ['small', {}, meta]] as Node,i)
    if (n[1].id !== 'brief') return element(n,i)
    const children: Node[] = []
    for (const child of n.slice(2) as Node[]) {
      children.push(child)
      if (Array.isArray(child) && child[0] === 'p' && typeof child[2] === 'string' && /^(Daily MAE|일간 MAE|日別MAE)/.test(child[2]))
        children.push(['p',{class:'note'},w.mae])
    }
    if (score && score.sampleTargets > 0 && score.issueIds?.length === score.sampleTargets &&
        Number.isFinite(score.h1MaeMw) && Number.isFinite(score.championMaeMw))
      children.push(['p',{},w.h1+' (n='+score.sampleTargets+'): MAE · SD-H1-P50 '+score.h1MaeMw+' MW / Champion '+score.championMaeMw+' MW'])
    children.push(['small',{},source])
    return element([n[0],n[1],...children],i)
  }
  function showEvidence(event: MouseEvent<HTMLElement>) {
    const link = (event.target as Element).closest('a')
    if (!link || !link.hash.startsWith('#' + prefix + 'row-')) return
    const row = document.getElementById(decodeURIComponent(link.hash.slice(1)))
    const details = row?.closest('details')
    if (!row || !details || !event.currentTarget.contains(row)) return
    event.preventDefault()
    details.open = true
    row.focus({ preventScroll: true })
    row.scrollIntoView({ block: 'center' })
  }
  return <article lang={locale} className="ops-v8" data-report-layout="v8" onClick={showEvidence}>{nodes.map(section)}</article>
}
