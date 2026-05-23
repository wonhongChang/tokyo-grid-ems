export type Severity = 'info' | 'warning' | 'critical'
export type Availability = 'ok' | 'failed' | 'not_yet_available' | 'missing'

export interface LatestSummary {
  date: string
  peakActualMw: number | null
  peakActualAt: string | null
  peakUsagePct: number | null
  peakSupplyMw: number | null
  peakTempC?: number
}

export interface ForecastSummary {
  date: string
  peakForecastMw: number | null
  peakForecastAt: string | null
  severity: Severity
  peakTempC?: number
}

export interface StatusJSON {
  project: string
  schemaVersion: string
  timezone: string
  lastUpdatedAt: string
  coverageTo: string | null
  availability: Availability
  missingDays: string[]
  failedDays: string[]
  latest: LatestSummary | null
  yesterday: string | null
  today: ForecastSummary | null
  tomorrow: ForecastSummary | null
}

export interface ForecastPoint {
  ts: string
  forecastMw: number
  p95LowerMw: number
  p95UpperMw: number
  p99LowerMw: number
  p99UpperMw: number
}

export interface ForecastJSON {
  date: string
  timezone: string
  availability: Availability
  model?: { name: string; version: string; nWeeks: number }
  peak?: {
    forecastMw: number
    at: string
    interval: { p95Lower: number; p95Upper: number }
  }
  series: ForecastPoint[]
  message?: string
}

export interface AlertEvent {
  id: string
  type: string
  severity: Severity
  startAt: string
  endAt: string
  metric: string
  reason: string
  usagePct?: number
  thresholdPct?: number
  supplyMw?: number | null
  actualMw?: number
  expectedMw?: number
  interval?: {
    p95Lower: number
    p95Upper: number
    p99Lower: number
    p99Upper: number
  }
  residualAvgMw?: number
  thresholdMw?: number
  method?: string
  contextNote?: string
  tags: string[]
}

export interface AlertsJSON {
  date: string
  timezone: string
  availability: Availability
  summary: { critical: number; warning: number; info: number }
  events: AlertEvent[]
}

export interface ActualPoint {
  ts: string
  actualMw: number | null
  actualSource?: 'observed' | 'tepco_forecast_fallback' | null
  tepcoForecastMw: number | null
  usagePct: number | null
  supplyMw: number | null
}

export interface ActualJSON {
  date: string
  timezone: string
  availability: Availability
  series: ActualPoint[]
}

export interface ForecastAccuracyDaily {
  date: string
  modelName?: string
  modelFamily?: string
  includedInSummary?: boolean
  hours: number
  modelMaeMw: number | null
  tepcoMaeMw: number | null
  modelWapePct?: number | null
  tepcoWapePct?: number | null
  modelRmseMw?: number | null
  tepcoRmseMw?: number | null
  modelMaxErrorMw?: number | null
  tepcoMaxErrorMw?: number | null
  modelMaxErrorHour?: number | null
  tepcoMaxErrorHour?: number | null
  maeGapMw?: number | null
  wapeGapPct?: number | null
  verdict?: 'model_better' | 'tepco_better' | 'close' | 'mixed' | 'insufficient'
  modelWins: number
  tepcoWins: number
  ties: number
  modelAdvantageHours?: number
  tepcoAdvantageHours?: number
  equalHours?: number
  modelAdvantageRate?: number | null
}

export interface ForecastAccuracyHourly {
  hour: number
  samples: number
  modelMaeMw: number | null
  tepcoMaeMw: number | null
  modelWapePct?: number | null
  tepcoWapePct?: number | null
  modelRmseMw?: number | null
  tepcoRmseMw?: number | null
  modelMaxErrorMw?: number | null
  tepcoMaxErrorMw?: number | null
  modelWins: number
  tepcoWins: number
  ties: number
  modelAdvantageHours?: number
  tepcoAdvantageHours?: number
  equalHours?: number
  modelAdvantageRate?: number | null
}

export interface ForecastAccuracyJSON {
  schemaVersion: string
  timezone: string
  generatedAt: string
  windowDays: number
  modelScope?: {
    summaryModelFamily: string | null
    summaryModelNames: string[]
    excludedDates: string[]
  }
  summary: {
    dates: number
    hours: number
    modelMaeMw: number | null
    tepcoMaeMw: number | null
    modelWapePct?: number | null
    tepcoWapePct?: number | null
    modelRmseMw?: number | null
    tepcoRmseMw?: number | null
    modelMaxErrorMw?: number | null
    tepcoMaxErrorMw?: number | null
    modelMaxErrorHour?: number | null
    tepcoMaxErrorHour?: number | null
    verdict?: 'model_better' | 'tepco_better' | 'close' | 'mixed' | 'insufficient'
    modelWins: number
    tepcoWins: number
    ties: number
    modelWinRate: number | null
    modelAdvantageHours?: number
    tepcoAdvantageHours?: number
    equalHours?: number
    modelAdvantageRate?: number | null
  }
  daily: ForecastAccuracyDaily[]
  hourly: ForecastAccuracyHourly[]
}

export type DailyOperationVerdict = 'model_better' | 'tepco_better' | 'close' | 'mixed' | 'insufficient'

export interface DailyOperationInsight {
  code: string
  severity: Severity
  title: string
  evidence?: Record<string, string | number | null>
}

export interface DailyOperationTopMiss {
  hour: number
  actualMw: number
  modelForecastMw: number
  tepcoForecastMw: number
  modelErrorMw: number
  tepcoErrorMw: number
  modelAbsErrorMw: number
  tepcoAbsErrorMw: number
}

export interface DailyOperationReport {
  schemaVersion: string
  timezone: string
  generatedAt: string
  date: string
  availability: Availability | 'insufficient'
  model: { name: string; family: string }
  summary: {
    comparableHours: number
    modelMaeMw?: number | null
    tepcoMaeMw?: number | null
    modelWapePct?: number | null
    tepcoWapePct?: number | null
    modelRmseMw?: number | null
    tepcoRmseMw?: number | null
    modelMaxErrorMw?: number | null
    tepcoMaxErrorMw?: number | null
    modelMaxErrorHour?: number | null
    tepcoMaxErrorHour?: number | null
    maeGapMw?: number | null
    wapeGapPct?: number | null
    verdict?: DailyOperationVerdict
    modelWins?: number
    tepcoWins?: number
    ties?: number
    modelAdvantageHours?: number
    tepcoAdvantageHours?: number
    equalHours?: number
    modelAdvantageRate?: number | null
  }
  peak?: {
    actual: { hour: number; actualMw: number }
    model: { hour: number; forecastMw: number; errorAtActualPeakMw: number; timeErrorHours: number }
    tepco: { hour: number; forecastMw: number; errorAtActualPeakMw: number; timeErrorHours: number }
  } | null
  topMisses?: DailyOperationTopMiss[]
  insights: DailyOperationInsight[]
}

export interface DailyOperationReportIndex {
  schemaVersion: string
  timezone: string
  generatedAt: string
  availability: Availability
  latest: DailyOperationReport | null
  reports: Array<{
    date: string
    availability: Availability | 'insufficient'
    model?: { name: string; family: string }
    summary?: DailyOperationReport['summary']
    insights: DailyOperationInsight[]
  }>
}

export type AIDailyReportConfidence = 'low' | 'medium' | 'high'
export type AIDailyReportEvidenceStatus = 'confirmed' | 'partial' | 'not_observed'
export type AIDailyReportPriority = 'low' | 'medium' | 'high'
export type AIDailyReportRecommendationType =
  | 'feature_engineering'
  | 'calibration'
  | 'data_quality'
  | 'evaluation'
  | 'monitoring'

export interface AIDailyReportEvidence {
  source: string
  metric: string
  value: string | number | null
  unit?: string
  hour?: number | null
  timeBand?: string | null
  note?: string
}

export interface AIDailyReportHypothesis {
  id: string
  severity: Severity
  confidence: AIDailyReportConfidence
  evidenceStatus: AIDailyReportEvidenceStatus
  title: string
  explanation: string
  evidence: AIDailyReportEvidence[]
  relatedHours: number[]
  relatedTimeBands: string[]
  relatedFeatures: string[]
  counterEvidence?: string[]
}

export interface AIDailyReportFeatureRecommendation {
  id: string
  priority: AIDailyReportPriority
  type: AIDailyReportRecommendationType
  target: string
  suggestion: string
  expectedEffect: string
  risk: string
  validationPlan: string
  linkedHypotheses: string[]
  autoApply: false
}

export interface AIDailyReport {
  schemaVersion: string
  reportType: 'ai_daily_operation_report'
  timezone: string
  date: string
  generatedAt: string
  availability: Availability | 'insufficient'
  language: 'en' | 'ko' | 'ja'
  contentLanguage?: 'en' | 'ko' | 'ja'
  generator: {
    provider: 'openai' | 'fallback'
    model: string | null
    localizationModel?: string | null
    localizationStatus?: 'ok' | 'fallback_en' | 'not_requested'
    localizationFallback?: 'en' | null
    promptVersion: string
    schemaVersion: string
  }
  inputRefs: {
    operationReport: string
    internalDiagnostics?: string | null
    operationalCalibration?: string | null
    operationalCalibrationHistory?: string | null
    alerts?: string | null
    forecast?: string | null
    actual?: string | null
    metrics?: string | null
  }
  inputSnapshot?: {
    schemaVersion: string
    createdAt: string
    fingerprint: string
    sources: Record<string, {
      path: string | null
      exists: boolean
      date: string | null
      generatedAt: string | null
      fingerprint: string | null
    }>
  }
  dataQuality: {
    comparableHours: number
    observedHours: number
    fallbackActualHours: number
    calibrationSnapshotCount?: number
    limitations: string[]
  }
  executiveSummary: {
    severity: Severity
    headline: string
    summary: string
    modelVerdict: DailyOperationVerdict
    confidence: AIDailyReportConfidence
  }
  performance: DailyOperationReport['summary']
  rootCauseHypotheses: AIDailyReportHypothesis[]
  featureRecommendations: AIDailyReportFeatureRecommendation[]
  operatorNotes: string[]
  limitations: string[]
}

export interface AIDailyReportIndex {
  schemaVersion: string
  timezone: string
  generatedAt: string
  availability: Availability
  latest: {
    date: string
    availability: Availability | 'insufficient'
    severity?: Severity
    headline?: string
    modelVerdict?: DailyOperationVerdict
  } | null
  reports: Array<{
    date: string
    availability: Availability | 'insufficient'
    severity?: Severity
    headline?: string
    modelVerdict?: DailyOperationVerdict
    modelMaeMw?: number | null
    tepcoMaeMw?: number | null
  }>
}

export interface BacktestMetrics {
  rmse: number | null
  mae: number | null
  mape: number | null
  n: number
}

export interface ModelBacktestJSON {
  schemaVersion: string
  timezone: string
  generatedAt: string
  methodology: {
    type: string
    target: string
    testStart: string
    minTrainDays: number
  }
  trainPeriod: {
    start: string
    end: string
    rows: number
  }
  testPeriod: {
    start: string
    end: string
    days: number
  }
  baseline: BacktestMetrics
  lightgbm: BacktestMetrics | null
  improvementPct: {
    rmse: number | null
    mae: number | null
  }
}
