import { useState } from 'react'
import { useFetch } from '../hooks/useFetch'
import { useT } from '../i18n'
import {
  bucketCoverageLimited, errorGap, formatErrorPct, formatErrorPower, formatExactMw,
  hasPairedSamples, supportedVintage,
  type ForecastVintageAccuracyJSON,
} from '../validationMetrics'

const COPY = {
  ko: {
    title: '사전 예측 비교', period: '집계 구간', days: '관측일', lead: '예측 선행 시간',
    description: '같은 시점에 수집한 두 예측을 실측과 비교합니다. TEPCO가 나중에 수정한 과거 예측값은 반영하지 않습니다.',
    scope: '기간 내 운영 모델·보정 정책을 함께 집계하며, 현재 모델 버전만의 성적은 아닙니다. 원본 발표 시각은 확인할 수 없습니다.',
    method: '각 구간에서 목표 시각에 가장 가까운 사전 예측 1개를 선택합니다. 시간은 하한 초과·상한 이하이며, 구간별 표본은 합산하지 않습니다.',
    model: '모델', samples: '비교 표본', coverage: '일자', limited: '표본 범위 부족', recorded: '비교 가능',
    none: '비교 표본 없음', unavailable: '사전 예측 비교 데이터가 아직 없습니다.',
    error: '사전 예측 비교 데이터를 불러오지 못했습니다.', unsupported: '비교 기준을 확인할 수 없는 데이터입니다.',
    gap: 'MAE 차이 (모델 − TEPCO)', risk: '오차 상세', updated: '데이터 생성',
    units: '각 값은 모델 / TEPCO 순서입니다. MAE·WAPE·RMSE·최대 오차는 낮을수록 좋습니다.',
    observed: '관측된 일자', maxError: '최대 오차',
  },
  en: {
    title: 'Advance forecast comparison', period: 'Window', days: 'observed days', lead: 'Forecast lead time',
    description: 'Compares both forecasts captured at the same time against actual demand. Later TEPCO revisions of past forecasts are excluded.',
    scope: 'Includes operational models and calibration policies used during this period, not only the current model version. Original publication times are unavailable.',
    method: 'Selects the forecast closest to the target within each bucket. Lower bounds are exclusive; upper bounds inclusive. Samples across buckets are not additive.',
    model: 'Model', samples: 'Paired samples', coverage: 'Dates', limited: 'Limited coverage', recorded: 'Comparable',
    none: 'No paired samples', unavailable: 'Advance comparison data is not available yet.',
    error: 'Could not load advance comparison data.', unsupported: 'The comparison contract could not be verified.',
    gap: 'MAE gap (model − TEPCO)', risk: 'Error details', updated: 'Data generated',
    units: 'Values are model / TEPCO. Lower MAE, WAPE, RMSE and maximum error are better.',
    observed: 'Observed dates', maxError: 'Max error',
  },
  ja: {
    title: '事前予測比較', period: '集計区間', days: '観測日', lead: '予測リード時間',
    description: '同じ時点で取得した両予測を実績と比較します。TEPCOによる過去予測の事後修正は反映しません。',
    scope: '期間内の運用モデル・補正方針を含み、現在のモデルバージョンだけの成績ではありません。元の発表時刻は確認できません。',
    method: '各区間内で対象時刻に最も近い事前予測を1件選択します。下限超・上限以下で区切り、区間間の標本は合算しません。',
    model: 'モデル', samples: '比較標本', coverage: '日数', limited: '標本範囲不足', recorded: '比較可能',
    none: '比較標本なし', unavailable: '事前予測比較データはまだありません。',
    error: '事前予測比較データを取得できませんでした。', unsupported: '比較基準を確認できないデータです。',
    gap: 'MAE差 (モデル − TEPCO)', risk: '誤差詳細', updated: 'データ生成',
    units: '各値はモデル / TEPCOの順です。MAE・WAPE・RMSE・最大誤差は低いほど良好です。',
    observed: '観測された日数', maxError: '最大誤差',
  },
}

export function VintageComparison({ baseUrl }: { baseUrl: string }) {
  const { t, locale } = useT()
  const labels = COPY[locale]
  const request = useFetch<ForecastVintageAccuracyJSON>(`${baseUrl}metrics/forecast_vintage_accuracy.json`)
  const [selectedWindow, setSelectedWindow] = useState('28d')
  const [selectedLead, setSelectedLead] = useState('0_2h')
  if (request.loading) return <div className="loading" role="status">{t.loading}</div>
  if (request.error) return <p className="empty-msg" role="alert">{labels.error}</p>
  if (!request.data) return <p className="empty-msg">{labels.unavailable}</p>
  const data = request.data
  if (!supportedVintage(data)) return <p className="empty-msg" role="alert">{labels.unsupported}</p>
  const windows = Object.entries(data.windows).filter(([, item]) => item?.period && item.leadBuckets)
  const windowKey = windows.some(([key]) => key === selectedWindow) ? selectedWindow : windows[0]?.[0]
  const window = data.windows[windowKey]
  if (!window) return <p className="empty-msg">{labels.unavailable}</p>
  const definitions = data.methodology.leadBucketsMinutes
  const leadKey = definitions.some(item => item.name === selectedLead) ? selectedLead : definitions[0].name
  const bucket = window.leadBuckets[leadKey]
  const paired = hasPairedSamples(bucket)
  const period = window.period
  const leadLabel = (lower: number, upper: number) => `${lower / 60}–${upper / 60}h`
  const power = (value: number | null | undefined) => formatErrorPower(value, locale)
  const stateLabel = (key: string) => !hasPairedSamples(window.leadBuckets[key]) ? labels.none
    : bucketCoverageLimited(data.qualification.failures, windowKey, key) ? labels.limited : labels.recorded

  return (
    <section className="validation-section" aria-label={labels.title}>
      <p className="validation-note">{labels.description}</p>
      <div className="validation-controls">
        <label>{labels.period}
          <select aria-label={labels.period} value={windowKey} onChange={event => setSelectedWindow(event.target.value)}>
            {windows.map(([key, item]) => <option key={key} value={key}>{item.period.requestedDays} {labels.days}</option>)}
          </select>
        </label>
        <label>{labels.lead}
          <select aria-label={labels.lead} value={leadKey} onChange={event => setSelectedLead(event.target.value)}>
            {definitions.map(item => <option key={item.name} value={item.name}>{leadLabel(item.lowerExclusive, item.upperInclusive)}</option>)}
          </select>
        </label>
      </div>
      <div className="validation-scope-line">
        <span>{period.start ?? '-'} ~ {period.end ?? '-'} JST</span>
        <span>{labels.observed}: {period.days} / {period.requestedDays}</span>
        <span className="badge info">{stateLabel(leadKey)}</span>
      </div>
      <div className="validation-stat-grid">
        {[
          [`${labels.model} MAE`, paired ? power(bucket.model.maeMw) : '-', paired ? formatExactMw(bucket.model.maeMw, locale) : ''],
          ['TEPCO MAE', paired ? power(bucket.tepco.maeMw) : '-', paired ? formatExactMw(bucket.tepco.maeMw, locale) : ''],
          [`${labels.model} WAPE`, paired ? formatErrorPct(bucket.model.wapePct) : '-', ''],
          ['TEPCO WAPE', paired ? formatErrorPct(bucket.tepco.wapePct) : '-', ''],
          [labels.gap, paired ? formatExactMw(errorGap(bucket.model.maeMw, bucket.tepco.maeMw), locale) : '-', ''],
          [labels.samples, paired ? String(bucket.model.hours) : '-', `${labels.coverage}: ${bucket?.dates ?? 0}`],
        ].map(([label, value, sub]) => (
          <div className="validation-stat" key={label}>
            <div className="validation-stat-label">{label}</div>
            <div className="validation-stat-value">{value}</div>
            {sub && <div className="validation-stat-sub">{sub}</div>}
          </div>
        ))}
      </div>
      <p className="validation-note validation-scope-note">{labels.scope}</p>
      <h3 className="card-title">{labels.risk}</h3>
      <p className="validation-note">{labels.units}</p>
      <div className="validation-table-wrap" tabIndex={0} role="region" aria-label={labels.risk}>
        <table className="validation-table">
          <thead><tr><th>{labels.lead}</th><th>{labels.samples}</th><th>MAE (MW)</th><th>WAPE</th><th>RMSE (MW)</th><th>{labels.maxError} (MW)</th><th>{labels.coverage}</th></tr></thead>
          <tbody>{definitions.map(item => {
            const row = window.leadBuckets[item.name]
            const valid = hasPairedSamples(row)
            return <tr key={item.name} className={item.name === leadKey ? 'validation-selected-row' : ''}>
              <th scope="row">{leadLabel(item.lowerExclusive, item.upperInclusive)}</th>
              <td>{valid ? row.model.hours : '-'}</td>
              <td>{valid ? `${formatExactMw(row.model.maeMw, locale)} / ${formatExactMw(row.tepco.maeMw, locale)}` : '-'}</td>
              <td>{valid ? `${formatErrorPct(row.model.wapePct)} / ${formatErrorPct(row.tepco.wapePct)}` : '-'}</td>
              <td>{valid ? `${formatExactMw(row.model.rmseMw, locale)} / ${formatExactMw(row.tepco.rmseMw, locale)}` : '-'}</td>
              <td>{valid ? `${formatExactMw(row.model.maxErrorMw, locale)} / ${formatExactMw(row.tepco.maxErrorMw, locale)}` : '-'}</td>
              <td>{row?.dates ?? 0} / {period.requestedDays} · {stateLabel(item.name)}</td>
            </tr>
          })}</tbody>
        </table>
      </div>
      <p className="validation-note validation-scope-note">{labels.method}</p>
      <p className="validation-note">{labels.updated}: {data.generatedAt.replace('T', ' ')} · <a href={`${baseUrl}metrics/forecast_vintage_accuracy.json`}>JSON</a></p>
    </section>
  )
}
