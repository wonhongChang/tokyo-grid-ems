import assert from 'node:assert/strict'
import test from 'node:test'
import { isTechnicalCatalogNote } from '../src/reportNotes.ts'

for (const prefix of ['운영 보정 신호 카탈로그:', 'Operational calibration signal catalog:', '運用補正シグナルカタログ：', '運用調整信号カタログ:']) {
  test(`recognizes the existing localized catalog: ${prefix}`, () => {
    assert.equal(isTechnicalCatalogNote(`  ${prefix} intraday_correction.example`), true)
  })
}

for (const text of [
  'Review intraday_correction.example against observations.',
  '운영 보정 신호 카탈로그의 내용을 검토했습니다.',
  'Unknown future note: intraday_correction.example',
  '',
]) {
  test(`preserves ordinary or unknown notes: ${text}`, () => {
    assert.equal(isTechnicalCatalogNote(text), false)
  })
}
