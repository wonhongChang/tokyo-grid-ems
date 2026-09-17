import assert from 'node:assert/strict'
import test from 'node:test'
import { isObservedActual, peakUsageMetrics } from '../src/usageMetrics.ts'

const date = '2026-09-17'
const ts = hour => `${date}T${String(hour).padStart(2, '0')}:00:00+09:00`
const actual = (hour, overrides = {}) => ({
  ts: ts(hour), actualMw: null, actualSource: null, usagePct: null,
  tepcoForecastMw: 33820, supplyMw: 38710, ...overrides,
})
const forecast = (hour, mw = 34738.8) => ({ ts: ts(hour), forecastMw: mw })

test('TEPCO and model estimates retain separate numerators and timestamps', () => {
  const result = peakUsageMetrics(date, [forecast(17)], [actual(17)])
  assert.equal(result.observed, null)
  assert.equal(result.tepco.usagePct.toFixed(1), '87.4')
  assert.equal(result.model.usagePct.toFixed(1), '89.7')
  assert.equal(result.tepco.supplyMw, 38710)
  assert.equal(result.tepco.at, ts(17))
})

test('each source selects its own peak using same-hour supply', () => {
  const rows = [actual(10, { supplyMw: 40000, tepcoForecastMw: 36000, actualMw: 32000, actualSource: 'observed', usagePct: 80 }),
    actual(11, { supplyMw: 50000, tepcoForecastMw: 40000, actualMw: 45000, actualSource: 'observed', usagePct: 90 })]
  const result = peakUsageMetrics(date, [forecast(10, 30000), forecast(11, 48000)], rows)
  assert.equal(result.observed.at, ts(11))
  assert.equal(result.tepco.at, ts(10))
  assert.equal(result.tepco.supplyMw, 40000)
  assert.equal(result.model.at, ts(11))
  assert.equal(result.model.supplyMw, 50000)
})

test('reported observations work without a model forecast', () => {
  const result = peakUsageMetrics(date, [], [actual(10, { actualMw: 32000, usagePct: 83, actualSource: 'observed' })])
  assert.equal(result.observed.usagePct, 83)
  assert.equal(result.model, null)
  assert.ok(result.tepco)
})

test('legacy actuals use reported usage or compute from demand and supply', () => {
  const result = peakUsageMetrics(date, [], [actual(10, { actualMw: 32000, actualSource: undefined, supplyMw: 40000 })])
  assert.equal(result.observed.usagePct, 80)
})

test('substitute forecasts and usage without demand never become observations', () => {
  const substitute = actual(10, { actualMw: 39000, usagePct: 99, actualSource: 'tepco_forecast_fallback' })
  assert.equal(isObservedActual(substitute), false)
  const result = peakUsageMetrics(date, [], [substitute, actual(11, { usagePct: 100 })])
  assert.equal(result.observed, null)
  assert.ok(result.tepco)
})

for (const supply of [null, 0, -1, NaN, Infinity]) {
  test(`invalid supply ${supply} cannot produce estimates or infinite ratios`, () => {
    const result = peakUsageMetrics(date, [forecast(10)], [actual(10, { supplyMw: supply })])
    assert.deepEqual(result, { observed: null, tepco: null, model: null })
  })
}

test('known reported utilization survives missing supply, without inventing a denominator', () => {
  const result = peakUsageMetrics(date, [], [actual(10, { actualMw: 32000, usagePct: 83, supplyMw: null })])
  assert.equal(result.observed.usagePct, 83)
  assert.equal(result.observed.supplyMw, null)
})

test('missing TEPCO forecast is not replaced by the model', () => {
  const result = peakUsageMetrics(date, [forecast(10)], [actual(10, { tepcoForecastMw: null })])
  assert.equal(result.tepco, null)
  assert.ok(result.model)
})

test('matching by full timestamp prevents another day or minute supplying the model', () => {
  const result = peakUsageMetrics(date, [
    { ...forecast(10), ts: '2026-09-18T10:00:00+09:00' },
    { ...forecast(10), ts: `${date}T10:30:00+09:00` },
  ], [actual(10), { ...actual(11), ts: '2026-09-18T11:00:00+09:00', usagePct: 100 }])
  assert.equal(result.model, null)
  assert.equal(result.tepco.at, ts(10))
})

test('true ties use the earliest timestamp regardless of input order', () => {
  const result = peakUsageMetrics(date, [], [actual(11), actual(10)])
  assert.equal(result.tepco.at, ts(10))
})

test('peak selection occurs before display rounding', () => {
  const result = peakUsageMetrics(date, [], [
    actual(10, { tepcoForecastMw: 89940, supplyMw: 100000 }),
    actual(11, { tepcoForecastMw: 89949, supplyMw: 100000 }),
  ])
  assert.equal(result.tepco.at, ts(11))
  assert.equal(result.tepco.usagePct.toFixed(1), '89.9')
})

test('zero demand is valid; negative and non-finite estimates are excluded', () => {
  assert.equal(peakUsageMetrics(date, [forecast(10, 0)], [actual(10, { tepcoForecastMw: 0 })]).model.usagePct, 0)
  for (const value of [-1, NaN, Infinity]) {
    const result = peakUsageMetrics(date, [forecast(10, value)], [actual(10, { tepcoForecastMw: value })])
    assert.equal(result.model, null)
    assert.equal(result.tepco, null)
  }
})

test('empty data returns explicit missing metrics', () => {
  assert.deepEqual(peakUsageMetrics(date), { observed: null, tepco: null, model: null })
})
