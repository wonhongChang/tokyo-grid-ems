import { createContext, useContext } from 'react'

export type Locale = 'ko' | 'en' | 'ja'

interface Translations {
  hourly: { title: string; empty: string; issued: string; confirmed: string; unverified: string; history: string;
    states: Record<"waiting" | "disabled" | "missed" | "issued", string>;
    actual: string; provisional: string; final: string; error: string; comparison: string; noActive: string }
  appSubtitle: string
  statusUpdated: string
  statusCoverage: string
  statusMissingDays: (n: number) => string
  statusFailedDays: (n: number) => string
  availOk: string
  availFailed: string
  availPending: string
  tabYesterday: string
  tabToday: string
  tabTomorrow: string
  tabValidation: string
  tabOpsReport: string
  peakActual: string
  peakForecast: string
  peakTepcoForecast: string
  peakUsage: string
  supply: string
  peakTemp: string
  alertEvents: string
  noEvents: string
  forecast: string
  modelForecast: string
  actual: string
  forecastRange: string
  tepcoForecast: string
  loading: string
  noData: string
  insufficientData: string
  latestDataSubtitle: string
  forecastSubtitle: string
  championForecast: string; d1Raw: string; sameDayObserved: string; forecastBuilt: string; publicationUnknown: string
  severityCritical: string
  severityWarning: string
  severityInfo: string
  criticalBadge: string
  warningBadge: string
  infoBadge: string
  okBadge: string
  eventReserveRisk: string
  eventSpike: string
  eventDrop: string
  eventDrift: string
  metricLabel: string
  metricUsagePct: string
  metricActualMw: string
  metricResidualMw: string
  noForecastData: string
  noHistoricalData: string
  failedLoad: string
  refreshUnverified: string
  through: string
  tomorrowNotReady: string
}

const KO: Translations = {
  hourly: { title: '다음 한 시간 예측', empty: '이 날짜의 H1 발행 기록 및 실행 상태를 확인할 수 없습니다.', issued: '발행',
    states: { waiting: '최근 실행: 발행 조건 대기', disabled: '최근 실행: H1 비활성', missed: '최근 실행: 시작 전 발행 미확인 · 채점 제외', issued: '시작 전 발행 확인 · 대상 시간 시작됨' },
    confirmed: '공개 데이터 확인', unverified: '시작 전 공개 미확인 · 채점 제외', history: '발행 이력', actual: '실측',
    provisional: '잠정', final: '확정', error: '절대오차', comparison: '대상별 마지막 적격 발행 MAE', noActive: '현재 적용할 사전 예측이 없습니다.' },
  appSubtitle: 'TEPCO 전력망 모니터',
  statusUpdated: '공개 데이터 갱신',
  statusCoverage: '일간 실측 확정일',
  statusMissingDays: (n) => `${n}일 누락`,
  statusFailedDays: (n) => `${n}일 실패`,
  availOk: '데이터 준비됨',
  availFailed: '● 실패',
  availPending: '● 대기',
  tabYesterday: '어제',
  tabToday: '오늘',
  tabTomorrow: '내일',
  tabValidation: '검증',
  tabOpsReport: '운영 리포트',
  peakActual: '최대 실적',
  peakForecast: '최대 예측',
  peakTepcoForecast: 'TEPCO 최대 예측',
  peakUsage: '최대 사용률',
  supply: '공급력',
  peakTemp: '피크 기온',
  alertEvents: '이상 감지 이벤트',
  noEvents: '이벤트 없음',
  forecast: '예측',
  modelForecast: '자체 모델',
  actual: '실적',
  forecastRange: '자체 모델 95% 구간',
  tepcoForecast: 'TEPCO 예측',
  loading: '로딩 중…',
  noData: '데이터 없음',
  insufficientData: '예측에 충분한 과거 데이터가 없습니다',
  latestDataSubtitle: '실적 포함 최신 데이터',
  forecastSubtitle: '대상일의 공개 예측',
  championForecast: 'LightGBM Champion · 운영 보정을 적용한 하루 예측', d1Raw: 'LightGBM · 이번 D-1 갱신은 Raw 중심값 사용', sameDayObserved: '당일 잠정 실측과 공개 예측',
  forecastBuilt: '예측 생성', publicationUnknown: '원 발행 시각 미확인',
  severityCritical: '위험',
  severityWarning: '경고',
  severityInfo: '정보',
  criticalBadge: '● 위험',
  warningBadge: '▲ 경고',
  infoBadge: '● 정보',
  okBadge: '● 정상',
  eventReserveRisk: '예비율 위험',
  eventSpike: '급등',
  eventDrop: '급락',
  eventDrift: '편차 지속',
  metricLabel: '지표',
  metricUsagePct: '사용률',
  metricActualMw: '실적 전력',
  metricResidualMw: '예측 편차',
  noForecastData: '예측 데이터 없음',
  noHistoricalData: '아직 과거 데이터가 없습니다',
  failedLoad: '상태 로딩 실패',
  refreshUnverified: '일부 자료를 갱신하지 못했습니다. 표시 중인 값이 최신인지 확인되지 않았습니다.',
  through: '~',
  tomorrowNotReady: '오늘 실적 데이터 확인 후 표시됩니다',
}

const EN: Translations = {
  hourly: { title: 'Next-hour forecast', empty: 'No verified H1 issue or run status for this date.', issued: 'Issued',
    states: { waiting: 'Last run: waiting for eligible inputs or issue window', disabled: 'Last run: H1 disabled', missed: 'Last run: pre-start issue unconfirmed; not scored', issued: 'Pre-start issue confirmed; target already started' },
    confirmed: 'Public data confirmed', unverified: 'Pre-start publication unverified · not scored', history: 'Issue history', actual: 'Actual',
    provisional: 'provisional', final: 'final', error: 'Absolute error', comparison: 'MAE at last eligible issue per target', noActive: 'No active pre-start estimate.' },
  appSubtitle: 'TEPCO Power Grid Monitor',
  statusUpdated: 'Public data updated',
  statusCoverage: 'Daily actuals finalized through',
  statusMissingDays: (n) => `${n} missing day${n > 1 ? 's' : ''}`,
  statusFailedDays: (n) => `${n} failed day${n > 1 ? 's' : ''}`,
  availOk: 'Data available',
  availFailed: '● Failed',
  availPending: '● Pending',
  tabYesterday: 'Yesterday',
  tabToday: 'Today',
  tabTomorrow: 'Tomorrow',
  tabValidation: 'Validation',
  tabOpsReport: 'Ops Report',
  peakActual: 'Peak Actual',
  peakForecast: 'Peak Forecast',
  peakTepcoForecast: 'TEPCO Peak Forecast',
  peakUsage: 'Peak Usage',
  supply: 'Supply',
  peakTemp: 'Peak Temp',
  alertEvents: 'Alert Events',
  noEvents: 'No events',
  forecast: 'Forecast',
  modelForecast: 'Our model',
  actual: 'Actual',
  forecastRange: 'Our model’s 95% interval',
  tepcoForecast: 'TEPCO forecast',
  loading: 'Loading…',
  noData: 'No data available',
  insufficientData: 'Insufficient historical data for forecast',
  latestDataSubtitle: 'Latest data with actual measurements',
  forecastSubtitle: 'Published forecast for the target date',
  championForecast: 'LightGBM Champion · daily forecast with serving adjustments', d1Raw: 'LightGBM · raw center for this D-1 update', sameDayObserved: 'Provisional observations and published forecast',
  forecastBuilt: 'Forecast generated', publicationUnknown: 'Original publication time unverified',
  severityCritical: 'Danger',
  severityWarning: 'Warning',
  severityInfo: 'Info',
  criticalBadge: '● Danger',
  warningBadge: '▲ Warning',
  infoBadge: '● Info',
  okBadge: '● OK',
  eventReserveRisk: 'Reserve Risk',
  eventSpike: 'Spike',
  eventDrop: 'Drop',
  eventDrift: 'Drift',
  metricLabel: 'metric',
  metricUsagePct: 'Usage rate',
  metricActualMw: 'Actual load',
  metricResidualMw: 'Forecast residual',
  noForecastData: 'No forecast data',
  noHistoricalData: 'No historical data available yet',
  failedLoad: 'Failed to load status',
  refreshUnverified: 'Some data could not be refreshed. Values shown may be from the previous update.',
  through: 'through',
  tomorrowNotReady: "Available after today's actuals are confirmed",
}

const JA: Translations = {
  hourly: { title: '次の1時間の需要予測', empty: 'この日のH1発行記録・実行状態は確認できません。', issued: '発行',
    states: { waiting: '直近の実行：発行条件待ち', disabled: '直近の実行：H1無効', missed: '直近の実行：開始前の発行未確認・採点対象外', issued: '開始前の発行を確認済み・対象時間は開始済み' },
    confirmed: '公開データ確認', unverified: '開始前の公開未確認・集計対象外', history: '発行履歴', actual: '実績',
    provisional: '速報', final: '確定', error: '絶対誤差', comparison: '対象時間ごとの最終有効予測のMAE', noActive: '現在有効な事前予測はありません。' },
  appSubtitle: 'TEPCO電力網モニター',
  statusUpdated: '公開データ更新',
  statusCoverage: '日別実績の確定日',
  statusMissingDays: (n) => `${n}日分欠損`,
  statusFailedDays: (n) => `${n}日分失敗`,
  availOk: 'データ取得済み',
  availFailed: '● 失敗',
  availPending: '● 待機',
  tabYesterday: '昨日',
  tabToday: '今日',
  tabTomorrow: '明日',
  tabValidation: '検証',
  tabOpsReport: '運用レポート',
  peakActual: 'ピーク実績',
  peakForecast: 'ピーク予測',
  peakTepcoForecast: 'TEPCOピーク予測',
  peakUsage: '最大使用率',
  supply: '供給力',
  peakTemp: 'ピーク気温',
  alertEvents: '異常検知イベント',
  noEvents: 'イベントなし',
  forecast: '予測',
  modelForecast: '当モデル',
  actual: '実績',
  forecastRange: '当モデルの95%予測区間',
  tepcoForecast: 'TEPCO予測',
  loading: '読み込み中…',
  noData: 'データなし',
  insufficientData: '予測に必要な過去データが不足しています',
  latestDataSubtitle: '実績含む最新データ',
  forecastSubtitle: '対象日の公開予測',
  championForecast: 'LightGBM Champion・運用補正を適用した日別予測', d1Raw: 'LightGBM・今回のD-1更新は補正前の中心値を使用', sameDayObserved: '当日の暫定実績と公開予測',
  forecastBuilt: '予測生成', publicationUnknown: '当初の公開時刻は未確認',
  severityCritical: '危険',
  severityWarning: '警告',
  severityInfo: '情報',
  criticalBadge: '● 危険',
  warningBadge: '▲ 警告',
  infoBadge: '● 情報',
  okBadge: '● 正常',
  eventReserveRisk: '予備率リスク',
  eventSpike: '急騰',
  eventDrop: '急落',
  eventDrift: 'ドリフト',
  metricLabel: '指標',
  metricUsagePct: '使用率',
  metricActualMw: '実績電力',
  metricResidualMw: '予測残差',
  noForecastData: '予測データなし',
  noHistoricalData: 'まだ過去データがありません',
  failedLoad: 'ステータス取得失敗',
  refreshUnverified: '一部の資料を更新できませんでした。表示値は前回の更新時点の可能性があります。',
  through: '〜',
  tomorrowNotReady: '本日の実績確認後に表示されます',
}

export const TRANSLATIONS: Record<Locale, Translations> = { ko: KO, en: EN, ja: JA }

export const LOCALE_LABELS: Record<Locale, string> = {
  ja: '日本語',
  en: 'English',
  ko: '한국어',
}

const DATE_LOCALES: Record<Locale, string> = {
  ko: 'ko-KR',
  en: 'en-US',
  ja: 'ja-JP',
}

export function fmtDate(isoDate: string, locale: Locale): string {
  return new Date(isoDate + 'T00:00:00+09:00').toLocaleDateString(DATE_LOCALES[locale], {
    year: 'numeric', month: 'long', day: 'numeric', weekday: 'short',
    timeZone: 'Asia/Tokyo',
  })
}

export const I18nContext = createContext<Locale>('ko')

export function useT() {
  const locale = useContext(I18nContext)
  return {
    t: TRANSLATIONS[locale],
    locale,
    fmtDate: (iso: string) => fmtDate(iso, locale),
  }
}
