import type { AIDailyReport } from './types'

export type BriefNode = string | [string, Record<string, string>, ...BriefNode[]]
export type Tag = Exclude<BriefNode, string>
export const isTag = (n: BriefNode): n is Tag => Array.isArray(n)
export const children = (n: Tag) => n.slice(2) as BriefNode[]
export function byId(nodes: BriefNode[], id: string): Tag | undefined {
  for (const node of nodes) if (isTag(node)) {
    if (node[1].id === id) return node
    const found = byId(children(node), id)
    if (found) return found
  }
}

export type Slot = {hour: number; actual: number; published: number; tepco: number; error: number; tepcoError: number}
const fields = ['actual', 'published', 'tepco', 'error', 'tepcoError'] as const
function readPoint(row: Tag, hour: number): Slot | null {
  const p = {hour} as Slot
  for (const f of fields) {
    const cells = children(row).filter(isTag).filter(n => n[0] === 'td' && n[1]['data-field'] === f)
    const raw = cells[0]?.[2]
    if (cells.length !== 1 || cells[0].length !== 3 || typeof raw !== 'string' ||
        !/^-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/.test(raw)) return null
    p[f] = Number(raw.replace(/,/g, ''))
    if (!Number.isFinite(p[f])) return null
  }
  return p
}

// Read only Python's labelled, already verified table cells in the frozen brief.
// Never parse translated prose, substitute a recent file, or bridge a missing hour.
export function chartSlots(nodes: BriefNode[], report: AIDailyReport): (Slot | null)[] | null {
  const group = byId(nodes, 'point')
  if (!group || group[0] !== 'details') return null
  const slots = Array<Slot | null>(24).fill(null)
  function visit(n: Tag): boolean {
    if (n[0] !== 'tr' || !n[1]['data-id']) return children(n).filter(isTag).every(visit)
    const key = n[1]['data-id'], m = /^point\/([01]\d|2[0-3]):00$/.exec(key)
    if (!m || n[1].id !== 'row-'+key || slots[+m[1]]) return false
    return !!(slots[+m[1]] = readPoint(n, +m[1]))
  }
  const expected = report.operationsBrief?.sampleHours === undefined ? report.dataQuality.comparableHours : report.operationsBrief.sampleHours
  return visit(group) && slots.some(Boolean) && slots.filter(Boolean).length === expected ? slots : null
}

export function verifiedAdvice(nodes: BriefNode[], report: AIDailyReport): Tag | undefined {
  const v=report.operationsBrief, g=report.generator, meta=g.advisory
  const model = meta?.model ?? (g.provider === 'openai' ? g.model : null)
  const note = byId(nodes,'luna')
  if (v?.advisoryStatus !== 'selected' || model !== 'gpt-6-luna' || !note ||
      (meta && (meta.provider !== 'openai' || meta.status !== 'selected' || meta.attempted !== true)) || !Array.isArray(v.selection)) return
  return v.selection.some(s => s && typeof s.relation === 'string' &&
    ((s.claim === 'published_closer' && s.relation.startsWith('vintage/')) ||
     (s.claim === 'opposite_directions' && s.relation.startsWith('change/'))) &&
    byId(nodes,'row-'+s.relation) && children(note).filter(isTag).some(a => a[0] === 'a' && a[1].href === '#row-'+s.relation)) ? note : undefined
}
