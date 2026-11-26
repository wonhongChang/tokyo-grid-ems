import { createElement, type MouseEvent, type ReactNode } from 'react'
import type { AIDailyReport } from '../types'
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

export function OperationsBrief({ nodes, locale }: { nodes: Node[]; locale: string }) {
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
  return <article lang={locale} className="ops-v8" data-report-layout="v8" onClick={showEvidence}>{nodes.map(element)}</article>
}
