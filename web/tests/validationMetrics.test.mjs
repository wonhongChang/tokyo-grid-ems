import assert from 'node:assert/strict'
import test from 'node:test'
import {
  bucketCoverageLimited, errorGap, formatErrorPct, formatErrorPower, formatExactMw,
  hasPairedSamples, isPartialDay, referenceDays, referenceMetricValue, supportedVintage,
} from '../src/validationMetrics.ts'

const metric = { hours: 24, maeMw: 498.1, wapePct: 1.65, rmseMw: 620, maxErrorMw: 1200 }
const report = () => ({
  schemaVersion: '1.0.0',
  methodology: {
    type: 'matched_capture_lead_time_evaluation', sourceTimestamp: 'capturedAt', issuedAtAvailable: false,
    futureTargetsOnly: true, sourcePastRevisionsApplied: false,
    selectionWithinBucket: 'minimum_positive_lead_within_bucket',
    leadBucketsMinutes: [{ name: '0_2h', lowerExclusive: 0, upperInclusive: 120 }],
  },
  windows: { '28d': { period: { requestedDays: 28, days: 1 }, leadBuckets: {} } },
  qualification: { failures: [] },
})

test('precision preserves small errors in all UI power units', () => {
  assert.equal(formatErrorPower(498.1, 'ko'), '49.8 만 kW')
  assert.equal(formatErrorPower(498.1, 'ja'), '49.8 万kW')
  assert.equal(formatErrorPower(498.1, 'en'), '0.498 GW')
  assert.equal(formatExactMw(498.1, 'en'), '498.1 MW')
  assert.equal(formatErrorPower(0, 'ja'), '0 万kW')
})

test('invalid metrics remain missing, not zero or Infinity', () => {
  for (const value of [null, undefined, NaN, Infinity]) {
    assert.equal(formatExactMw(value, 'ko'), '-')
    assert.equal(formatErrorPower(value, 'ja'), '-')
    assert.equal(formatErrorPct(value), '-')
    assert.equal(errorGap(value, 10), null)
  }
  assert.equal(formatErrorPct(1.65), '1.65%')
  assert.equal(errorGap(100, 0), 100)
  assert.equal(errorGap(20, 30), -10)
})

test('reference scope is sorted, excludes unscoped and zero samples, and keeps partial days', () => {
  const rows = [
    { date: '2026-09-17', hours: 8 }, { date: '2026-09-16', hours: 24 },
    { date: '2026-09-15', hours: 24, includedInSummary: false }, { date: '2026-09-18', hours: 0 },
  ]
  assert.deepEqual(referenceDays(rows).map(row => row.date), ['2026-09-16', '2026-09-17'])
  assert.equal(rows[0].date, '2026-09-17')
  assert.equal(isPartialDay(rows[0]), true)
  assert.equal(isPartialDay(rows[1]), false)
})

test('WAPE uses the supplied same-sample percentage; never substitutes MAE or a daily average', () => {
  const row = { modelMaeMw: 498.1, tepcoMaeMw: 153.8, modelWapePct: 1.65, tepcoWapePct: 0.51 }
  assert.equal(referenceMetricValue(row, 'model', 'mae'), 498.1)
  assert.equal(referenceMetricValue(row, 'tepco', 'wape'), 0.51)
  assert.equal(referenceMetricValue({ ...row, modelWapePct: null }, 'model', 'wape'), null)
  assert.equal(referenceMetricValue({ ...row, modelWapePct: 0 }, 'model', 'wape'), 0)
  assert.equal(referenceMetricValue({ ...row, modelMaeMw: Infinity }, 'model', 'mae'), null)
})

test('pairs require matching, positive sample counts', () => {
  assert.equal(hasPairedSamples({ model: metric, tepco: metric }), true)
  assert.equal(hasPairedSamples({ model: metric, tepco: { ...metric, hours: 23 } }), false)
  assert.equal(hasPairedSamples({ model: { hours: 0 }, tepco: { hours: 0 } }), false)
  assert.equal(hasPairedSamples(undefined), false)
})

test('coverage failures are distinct from poor performance and scoped to the selected window/bucket', () => {
  const failures = ['84d.insufficient_days', '28d.0_2h.mae_ratio', '28d.2_4h.overnight.insufficient_hours']
  assert.equal(bucketCoverageLimited(failures, '28d', '0_2h'), false)
  assert.equal(bucketCoverageLimited(failures, '28d', '2_4h'), true)
  assert.equal(bucketCoverageLimited(failures, '84d', '0_2h'), true)
  assert.equal(bucketCoverageLimited(['28d.8_24h.insufficient_days'], '28d', '8_24h'), true)
})

test('recognizes the existing matched-capture contract without claiming same publication time', () => {
  assert.equal(supportedVintage(report()), true)
  assert.equal(supportedVintage({ ...report(), windows: {} }), true)
})

for (const change of [
  { type: 'latest_published_value_reference' }, { issuedAtAvailable: true },
  { futureTargetsOnly: false }, { sourcePastRevisionsApplied: true },
  { sourceTimestamp: 'generatedAt' }, { leadBucketsMinutes: [] },
  { leadBucketsMinutes: [{ name: '0_2h', lowerExclusive: -1, upperInclusive: 120 }] },
  { leadBucketsMinutes: [null] },
]) {
  test(`rejects unsupported comparison contracts: ${JSON.stringify(change)}`, () => {
    const value = report()
    value.methodology = { ...value.methodology, ...change }
    assert.equal(supportedVintage(value), false)
  })
}

test('incomplete window or qualification metadata cannot become a supported comparison', () => {
  assert.equal(supportedVintage({ ...report(), qualification: {} }), false)
  assert.equal(supportedVintage({ ...report(), windows: { '28d': {} } }), false)
  assert.equal(supportedVintage({ ...report(), schemaVersion: '2.0.0' }), false)
})
