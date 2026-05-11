import { createContext, useContext } from 'react'

export type Locale = 'ko' | 'en' | 'ja'

interface Translations {
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
  through: string
  tomorrowNotReady: string
}

const KO: Translations = {
  appSubtitle: 'TEPCO 전력망 모니터',
  statusUpdated: '업데이트',
  statusCoverage: '기간',
  statusMissingDays: (n) => `${n}일 누락`,
  statusFailedDays: (n) => `${n}일 실패`,
  availOk: '● 정상',
  availFailed: '● 실패',
  availPending: '● 대기',
  tabYesterday: '어제',
  tabToday: '오늘',
  tabTomorrow: '내일',
  tabValidation: '검증',
  peakActual: '최대 실적',
  peakForecast: '최대 예측',
  peakTepcoForecast: 'TEPCO 최대 예측',
  peakUsage: '최대 사용률',
  supply: '공급력',
  peakTemp: '피크 기온',
  alertEvents: '이상 감지 이벤트',
  noEvents: '이벤트 없음',
  forecast: '예측',
  modelForecast: '모델 예측',
  actual: '실적',
  forecastRange: '예측 범위',
  tepcoForecast: 'TEPCO 예측',
  loading: '로딩 중…',
  noData: '데이터 없음',
  insufficientData: '예측에 충분한 과거 데이터가 없습니다',
  latestDataSubtitle: '실적 포함 최신 데이터',
  forecastSubtitle: '과거 동일 요일 평균 기반 예측 (공휴일 보정 포함)',
  severityCritical: '심각',
  severityWarning: '경고',
  severityInfo: '정보',
  criticalBadge: '● 심각',
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
  through: '~',
  tomorrowNotReady: '오늘 실적 데이터 확인 후 표시됩니다',
}

const EN: Translations = {
  appSubtitle: 'TEPCO Power Grid Monitor',
  statusUpdated: 'Updated',
  statusCoverage: 'Coverage',
  statusMissingDays: (n) => `${n} missing day${n > 1 ? 's' : ''}`,
  statusFailedDays: (n) => `${n} failed day${n > 1 ? 's' : ''}`,
  availOk: '● OK',
  availFailed: '● Failed',
  availPending: '● Pending',
  tabYesterday: 'Yesterday',
  tabToday: 'Today',
  tabTomorrow: 'Tomorrow',
  tabValidation: 'Validation',
  peakActual: 'Peak Actual',
  peakForecast: 'Peak Forecast',
  peakTepcoForecast: 'TEPCO Peak Forecast',
  peakUsage: 'Peak Usage',
  supply: 'Supply',
  peakTemp: 'Peak Temp',
  alertEvents: 'Alert Events',
  noEvents: 'No events',
  forecast: 'Forecast',
  modelForecast: 'Model forecast',
  actual: 'Actual',
  forecastRange: 'Forecast range',
  tepcoForecast: 'TEPCO forecast',
  loading: 'Loading…',
  noData: 'No data available',
  insufficientData: 'Insufficient historical data for forecast',
  latestDataSubtitle: 'Latest data with actual measurements',
  forecastSubtitle: 'Historical same-weekday baseline (holiday-adjusted)',
  severityCritical: 'Critical',
  severityWarning: 'Warning',
  severityInfo: 'Info',
  criticalBadge: '● Critical',
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
  through: 'through',
  tomorrowNotReady: "Available after today's actuals are confirmed",
}

const JA: Translations = {
  appSubtitle: 'TEPCO電力網モニター',
  statusUpdated: '更新',
  statusCoverage: 'カバレッジ',
  statusMissingDays: (n) => `${n}日分欠損`,
  statusFailedDays: (n) => `${n}日分失敗`,
  availOk: '● 正常',
  availFailed: '● 失敗',
  availPending: '● 待機',
  tabYesterday: '昨日',
  tabToday: '今日',
  tabTomorrow: '明日',
  tabValidation: '検証',
  peakActual: 'ピーク実績',
  peakForecast: 'ピーク予測',
  peakTepcoForecast: 'TEPCOピーク予測',
  peakUsage: '最大使用率',
  supply: '供給力',
  peakTemp: 'ピーク気温',
  alertEvents: '異常検知イベント',
  noEvents: 'イベントなし',
  forecast: '予測',
  modelForecast: 'モデル予測',
  actual: '実績',
  forecastRange: '予測範囲',
  tepcoForecast: 'TEPCO予測',
  loading: '読み込み中…',
  noData: 'データなし',
  insufficientData: '予測に必要な過去データが不足しています',
  latestDataSubtitle: '実績含む最新データ',
  forecastSubtitle: '過去の同曜日平均に基づく予測（祝日補正あり）',
  severityCritical: '重大',
  severityWarning: '警告',
  severityInfo: '情報',
  criticalBadge: '● 重大',
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
