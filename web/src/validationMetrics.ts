import type { Locale } from './i18n'
import type { ForecastAccuracyDaily } from './types'

export type ErrorMetric = 'mae' | 'wape'
export interface VintageMetrics {
  hours: number
  maeMw: number | null
  wapePct: number | null
  rmseMw: number | null
  maxErrorMw: number | null
}
export interface VintagePair { model: VintageMetrics; tepco: VintageMetrics }
export interface VintageBucket extends VintagePair {
  dates: number
  timeBands: Record<string, VintagePair>
}
export interface VintageWindow {
  period: { start: string | null; end: string | null; days: number; requestedDays: number }
  leadBuckets: Record<string, VintageBucket>
}
export interface LeadBucketDefinition {
  name: string
  lowerExclusive: number
  upperInclusive: number
}
export interface ForecastVintageAccuracyJSON {
  schemaVersion: string
  generatedAt: string
  availability: string
  methodology: {
    type: string
    sourceTimestamp: string
    issuedAtAvailable: boolean
    futureTargetsOnly: boolean
    sourcePastRevisionsApplied: boolean
    selectionWithinBucket: string
    leadBucketsMinutes: LeadBucketDefinition[]
  }
  windows: Record<string, VintageWindow>
  qualification: { failures: string[] }
}

export function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function errorGap(model: number | null | undefined, tepco: number | null | undefined): number | null {
  return finite(model) && finite(tepco) ? model - tepco : null
}

export function formatErrorPower(value: number | null | undefined, locale: Locale): string {
  if (!finite(value)) return '-'
  const divisor = locale === 'en' ? 1000 : 10
  const unit = locale === 'en' ? 'GW' : locale === 'ja' ? '万kW' : '만 kW'
  return `${(value / divisor).toLocaleString(locale, { maximumFractionDigits: locale === 'en' ? 3 : 1 })} ${unit}`
}

export function formatExactMw(value: number | null | undefined, locale: Locale): string {
  return finite(value) ? `${value.toLocaleString(locale, { maximumFractionDigits: 1 })} MW` : '-'
}

export function formatErrorPct(value: number | null | undefined): string {
  return finite(value) ? `${value.toFixed(2)}%` : '-'
}

export function referenceDays(rows: ForecastAccuracyDaily[]): ForecastAccuracyDaily[] {
  return rows.filter(row => row.includedInSummary !== false && finite(row.hours) && row.hours > 0)
    .sort((a, b) => a.date.localeCompare(b.date))
}

export function isPartialDay(row: Pick<ForecastAccuracyDaily, 'hours'>): boolean {
  return row.hours < 24
}

export function referenceMetricValue(row: ForecastAccuracyDaily, source: 'model' | 'tepco', metric: ErrorMetric): number | null {
  const value = metric === 'wape'
    ? source === 'model' ? row.modelWapePct : row.tepcoWapePct
    : source === 'model' ? row.modelMaeMw : row.tepcoMaeMw
  return finite(value) && value >= 0 ? value : null
}

export function hasPairedSamples(pair: VintagePair | undefined): boolean {
  return !!pair && finite(pair.model?.hours) && pair.model.hours > 0
    && pair.model.hours === pair.tepco?.hours
}

export function bucketCoverageLimited(failures: string[], window: string, bucket: string): boolean {
  return failures.some(reason => (
    reason === `${window}.insufficient_days`
      || (reason.startsWith(`${window}.${bucket}.`)
        && /\.(insufficient_days|insufficient_hours)$/.test(reason))
  ))
}

export function supportedVintage(report: ForecastVintageAccuracyJSON): boolean {
  const method = report.methodology
  return report.schemaVersion === '1.0.0'
    && method?.type === 'matched_capture_lead_time_evaluation'
    && method.sourceTimestamp === 'capturedAt'
    && method.issuedAtAvailable === false
    && method.futureTargetsOnly === true
    && method.sourcePastRevisionsApplied === false
    && method.selectionWithinBucket === 'minimum_positive_lead_within_bucket'
    && Array.isArray(method.leadBucketsMinutes)
    && method.leadBucketsMinutes.length > 0
    && method.leadBucketsMinutes.every(bucket => bucket && typeof bucket.name === 'string' && finite(bucket.lowerExclusive)
      && finite(bucket.upperInclusive) && bucket.lowerExclusive >= 0 && bucket.upperInclusive > bucket.lowerExclusive)
    && !!report.windows && typeof report.windows === 'object'
    && Object.values(report.windows).every(window => window?.period && window.leadBuckets
      && finite(window.period.requestedDays) && window.period.requestedDays > 0
      && finite(window.period.days) && window.period.days >= 0)
    && Array.isArray(report.qualification?.failures)
    && report.qualification.failures.every(reason => typeof reason === 'string')
}
