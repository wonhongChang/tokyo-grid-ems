# JSON 스키마 명세 (Dashboard Contract)

언어: [English](../en/json_schema.md) · [日本語](../ja/json_schema.md)

GitHub Pages(정적 대시보드)가 직접 읽는 **정적 JSON 산출물 계약**입니다.
ETL/배치 파이프라인은 이 스키마에 맞춰 `web/public/` 아래 파일들을 생성합니다.

> 원칙
> - 날짜별 산출물은 **UTC가 아닌 Asia/Tokyo(JST)** 기준의 날짜(`YYYY-MM-DD`)를 사용합니다.
> - 결측/미평가 상태는 값 `null` 또는 명시적인 `status` 필드로 표현합니다.
> - 스키마는 MVP에서 고정하고, 3년치 확장 시에도 **변경하지 않는 것**을 목표로 합니다.

---

## 파일 목록
- `web/public/status.json`
- `web/public/alerts/YYYY-MM-DD.json`
- `web/public/forecast/YYYY-MM-DD.json`
- `web/public/forecast_snapshots/YYYY-MM-DD/index.json`
- `web/public/forecast_snapshots/YYYY-MM-DD/*.json`
- `web/public/actual/YYYY-MM-DD.json`
- `web/public/metrics/forecast_accuracy.json`
- `web/public/metrics/model_backtest.json`
- `web/public/reports/daily/YYYY-MM-DD.json`
- `web/public/reports/daily/index.json`
- `web/public/reports/ai/daily/YYYY-MM-DD.json`
- `web/public/reports/ai/daily/index.json`
- `web/public/reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json`
- `web/public/reports/ai/daily/{ko,en,ja}/index.json`
- `web/public/reports/internal/operational-calibration/YYYY-MM-DD.json`
- `web/public/reports/internal/operational-calibration/snapshots/YYYY-MM-DD/index.json`
- `web/public/reports/internal/operational-calibration/snapshots/YYYY-MM-DD/*.json`

---

## 공통 규칙
- 위험도/중요도는 전 산출물에서 `severity`(info|warning|critical)로 통일합니다.

## 공통 타입 정의

### Timestamp
- ISO 8601 문자열, **배치 산출물에서는 timezone(+09:00) 포함을 사실상 필수로 권장**
  - 예: `2025-12-01T18:00:00+09:00`

### Severity
- `"info" | "warning" | "critical"`

### DataAvailability (대시보드 상태 표현)
- `"ok"`: 정상 처리 완료
- `"missing"`: 미수집/미처리(배치 누락 등)
- `"failed"`: 시도했으나 실패(파싱/품질 게이트/입력 오류 등)
- `"not_yet_available"`: 제공 지연(정상 범주일 수 있음)

---

# 1) status.json

## 목적
대시보드 상단에 표시할 **현재 상태(Last Updated / Coverage / 결측일)** 및 요약 KPI를 제공.

## 경로
`web/public/status.json`

## 스키마
```json
{
  "project": "tokyo-grid-ems",
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",

  "lastUpdatedAt": "2025-12-02T07:05:12+09:00",
  "coverageTo": "2025-12-01",

  "availability": "ok",
  "missingDays": ["2025-11-23"],
  "failedDays": ["2025-11-24"],

  "latest": {
    "date": "2025-12-01",
    "peakActualMw": 58230.0,
    "peakActualAt": "2025-12-01T18:00:00+09:00",
    "peakUsagePct": 96.2,
    "peakSupplyMw": 61000.0
  },

  "yesterday": "2025-12-01",

  "today": {
    "date": "2025-12-02",
    "peakForecastMw": 57500.0,
    "peakForecastAt": "2025-12-02T18:00:00+09:00",
    "severity": "warning"
  },

  "tomorrow": {
    "date": "2025-12-03",
    "peakForecastMw": 56000.0,
    "peakForecastAt": "2025-12-03T18:00:00+09:00",
    "severity": "info"
  }
}
```

## 필드 설명
- `lastUpdatedAt`: 배치가 마지막으로 성공적으로 status를 갱신한 시각
- `coverageTo`: **어느 날짜(전날)까지** 이상탐지/실적 기반 산출물이 생성되었는지
- `availability`: 대시보드 전반 상태
- `missingDays`, `failedDays`: 결측/실패 일자 리스트(표시용)
- `latest`: 최근 처리된 실적 요약(전날)
- `yesterday`: 항상 `today - 1`일 (ISO 날짜 문자열). `coverageTo`와 달리 CSV 처리 여부와 무관하게 달력 기준 어제를 가리킴. 대시보드 "어제" 탭의 날짜 기준으로 사용
- `today`, `tomorrow`: 오늘/내일 예측 요약 — Phase 2에서 채워짐

---

# 2) alerts/YYYY-MM-DD.json

## 목적
**어제(전날)**의 이상탐지 결과를 "이벤트" 단위로 제공.

## 경로 예
- `web/public/alerts/2025-12-01.json`

## 스키마
```json
{
  "date": "2025-12-01",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "summary": {
    "critical": 1,
    "warning": 2,
    "info": 0
  },

  "events": [
    {
      "id": "2025-12-01T18:00:00+09:00_spike",
      "type": "spike",
      "severity": "critical",
      "startAt": "2025-12-01T18:00:00+09:00",
      "endAt": "2025-12-01T19:00:00+09:00",
      "metric": "actual_mw",
      "actualMw": 61500.0,
      "expectedMw": 58000.0,
      "interval": {
        "p95Lower": 56000.0,
        "p95Upper": 60000.0,
        "p99Lower": 55000.0,
        "p99Upper": 61000.0
      },
      "reason": "Actual exceeded p99 upper bound by 0.8%",
      "tags": ["interval", "peak"]
    },
    {
      "id": "2025-12-01T09:00:00+09:00_drift",
      "type": "drift",
      "severity": "warning",
      "startAt": "2025-12-01T09:00:00+09:00",
      "endAt": "2025-12-01T12:00:00+09:00",
      "metric": "residual_mw",
      "residualAvgMw": 1200.0,
      "method": "ewma",
      "thresholdMw": 1000.0,
      "reason": "EWMA residual above threshold for 3 hours",
      "tags": ["residual"]
    },
    {
      "id": "2025-12-01T17:00:00+09:00_reserve_risk",
      "type": "reserve_risk",
      "severity": "warning",
      "startAt": "2025-12-01T17:00:00+09:00",
      "endAt": "2025-12-01T19:00:00+09:00",
      "metric": "usage_pct",
      "usagePct": 95.4,
      "thresholdPct": 92.0,
      "supplyMw": 61000.0,
      "reason": "Usage rate exceeded threshold",
      "tags": ["kpi"]
    }
  ]
}
```

## 필드 설명
- `events[].type`: `"spike" | "drop" | "drift" | "reserve_risk" | "quality"`
- `events[].interval`: spike/drop에서 예측 구간이 있을 때만 포함
- Phase 1에서는 `availability: "not_yet_available"`, `events: []`로 생성됨

### 결측/실패 예시
```json
{
  "date": "2025-12-02",
  "timezone": "Asia/Tokyo",
  "availability": "missing",
  "summary": { "critical": 0, "warning": 0, "info": 0 },
  "events": [],
  "message": "No source data. Ingestion was skipped or data was not available."
}
```

---

# 3) forecast/YYYY-MM-DD.json

## 목적
**특정 날짜의 시간별 수요 예측(오늘/내일)**을 제공.

## 경로 예
- `web/public/forecast/2025-12-02.json`

## 스키마
```json
{
  "date": "2025-12-02",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "model": {
    "name": "baseline_dow_hour_mean",
    "version": "mvp-1",
    "nWeeks": 12
  },

  "peak": {
    "forecastMw": 57500.0,
    "at": "2025-12-02T18:00:00+09:00"
  },

  "series": [
    {
      "ts": "2025-12-02T00:00:00+09:00",
      "forecastMw": 42000.0,
      "p95LowerMw": 40000.0,
      "p95UpperMw": 44000.0,
      "p99LowerMw": 39000.0,
      "p99UpperMw": 45000.0
    }
  ]
}
```

## 필드 설명
- `model.name`: `baseline_dow_hour_mean` — 최근 N주 동일 요일/시간 평균
- `model.nWeeks`: 훈련에 사용한 롤링 윈도우 주 수
- `series[]`: 24포인트 예측값 + 구간(95/99%)
- 데이터 부족 시 `availability: "not_yet_available"`, `series: []`로 생성됨

---

# 3.5) forecast_snapshots/YYYY-MM-DD/*.json

## 목적
운영 분석을 위해 lead-time 예측 스냅샷을 제한적으로 보관합니다. Pages 산출물과 함께 저장하지만 대시보드 UI에서는 직접 링크하지 않습니다.

## 경로 예
- `web/public/forecast_snapshots/2025-12-02/index.json`
- `web/public/forecast_snapshots/2025-12-02/2025-12-01T21-20-00-09-00.json`

## 스냅샷 스키마
```json
{
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",
  "targetDate": "2025-12-02",
  "generatedAt": "2025-12-01T21:20:00+09:00",
  "runType": "intraday",
  "preserveObservedForecastHours": true,
  "model": {
    "name": "lgbm_quantile_q50_intraday_residual",
    "version": "mvp-1",
    "nWeeks": 12
  },
  "peak": {
    "forecastMw": 57500.0,
    "at": "2025-12-02T18:00:00+09:00"
  },
  "observationSummary": {
    "actualHoursAtGeneration": 12,
    "observedActualHoursAtGeneration": 12,
    "fallbackActualHoursAtGeneration": 0,
    "lastActualHour": 11,
    "lastObservedActualHour": 11,
    "lastFallbackActualHour": null
  },
  "forecastBuild": {
    "stageSummary": {
      "raw_lgbm": { "hours": 24, "peak": {} },
      "pre_calibration": { "hours": 24, "peak": {} }
    },
    "series": [
      {
        "hour": 9,
        "ts": "2025-12-02T09:00:00+09:00",
        "forecastMwByStage": {
          "raw_lgbm": 31000.0,
          "analog_adjusted": 30950.0,
          "post_holiday_guarded": 30950.0,
          "midday_guarded": 30950.0,
          "pre_calibration": 30950.0
        }
      }
    ]
  },
  "series": []
}
```

`forecastBuild`는 운영 분석용 선택 필드입니다. 공개 UI에는 직접 표시하지 않지만, lead-time 스냅샷에서 raw LightGBM, analog 보정, guard, intraday 보정 직전 값을 비교할 수 있게 합니다.

## 보존 정책
- `config.yaml`의 `forecast_snapshots.retention_days`, `forecast_snapshots.max_per_day`가 제어합니다.
- 현재 기본값은 최근 21개 target date, target date별 최대 16개 스냅샷입니다.

---

# 3.6) reports/internal/operational-calibration/YYYY-MM-DD.json

## 목적
운영 보정 레이어가 예측선을 어떻게 움직였는지 추적하기 위한 내부 분석용 JSON입니다. 대시보드 UI에는 직접 연결하지 않습니다.

## 핵심 필드
- `source_confidence`: 당일 실측/대체값/결측 상태 요약
- `applied_regime_reason`: 적용된 보정 사유 목록
- `applied_day_bias`: 하루 단위 scale 보정 평균값
- `forecast_build.stageSummary`: raw model부터 pre-calibration까지의 단계별 요약
- `correction`: residual 보정 메타데이터. 날짜 경계 이월, 하루 단위 bias, `businessTypeTransitionPriorApplied`, `businessTypeTransitionPriorBiasMw`, `businessTypeTransitionApplied`, `businessTypeTransitionBiasMw` 같은 영업/비영업 전환 보정 플래그와 `positiveResidualMitigationApplied`, `positiveResidualMitigationMaxMw`, `negResidualRecoveryDampingApplied`, `negResidualRecoveryDampingFactor` 같은 handoff 및 회복 감쇄 필드를 포함할 수 있음
- `hourlyDiagnostics[]`: 시간별 actual, TEPCO, stage별 forecast, pre/post calibration forecast, calibration delta, residual

---

# 3.7) reports/internal/operational-calibration/snapshots/YYYY-MM-DD/*.json

## 목적
intraday 실행별 운영 보정 상태를 제한적으로 보관합니다. 최신 `operational-calibration/YYYY-MM-DD.json`은 덮어쓰기되지만, snapshot index는 중간 실행 이력을 남겨 **운영 리포트**가 보정 레이어의 흐름을 더 잘 설명할 수 있게 합니다.

## 경로 예
- `web/public/reports/internal/operational-calibration/snapshots/2026-05-23/index.json`
- `web/public/reports/internal/operational-calibration/snapshots/2026-05-23/2026-05-23T09-20-00-09-00.json`

## index 핵심 필드
- `snapshots[]`: 보존된 실행 목록
- `snapshots[].appliedRegimeReason`: 해당 실행에서 기록된 보정 사유 목록
- `snapshots[].baseAdjustmentMw`, `snapshots[].appliedDayBiasMw`: 잔차/일 단위 보정 규모
- `snapshots[].businessTypeTransitionPriorApplied`, `snapshots[].positiveResidualMitigationApplied`, `snapshots[].negResidualRecoveryDampingApplied`: 주요 보정 레이어 플래그

## 보존 정책
- `config.yaml`의 `operational_calibration_snapshots.retention_days`, `operational_calibration_snapshots.max_per_day`가 제어합니다.
- 현재 기본값은 최근 14개 target date, target date별 최대 24개 스냅샷입니다.

---

# 4) actual/YYYY-MM-DD.json

## 목적
**특정 날짜의 시간별 실적값**을 제공. 당일 데이터는 인트라데이 워크플로가 실시간 갱신.

## 경로 예
- `web/public/actual/2025-12-01.json`

## 스키마
```json
{
  "date": "2025-12-01",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "series": [
    {
      "ts": "2025-12-01T00:00:00+09:00",
      "actualMw": 42000.0,
      "actualSource": "observed",
      "tepcoForecastMw": 41500.0,
      "usagePct": 68.5,
      "supplyMw": 61000.0
    }
  ]
}
```

## 필드 설명
- `actualMw`: 실적 전력 수요 (MW). 미확정 시간은 `null`
- `actualSource`: `actualMw`의 출처. `observed`는 실측값, `tepco_forecast_fallback`은 23:40 JST 갱신에서 23시 실측이 아직 없을 때 TEPCO 예측값으로 보강한 값. 이 보강값은 운영 예측 입력에는 사용하지만 검증 지표와 이상탐지 실측 판정에서는 제외
- `tepcoForecastMw`: TEPCO 공식 예측값 (CSV 포함값)
- `usagePct`: 사용률 (%)
- `supplyMw`: 공급력 (MW)

---

# 5) metrics/*.json

## 목적
대시보드의 **검증 탭**에서 모델 성능을 설명하기 위한 평가 산출물입니다.

## 파일
- `metrics/forecast_accuracy.json`: 최근 운영 구간에서 자체 모델과 TEPCO 예측의 시간별 오차 비교
- `metrics/model_backtest.json`: 베이스라인 대비 LightGBM 오프라인 백테스트

## 공통 필드
- `schemaVersion`: metrics 스키마 버전
- `timezone`: `Asia/Tokyo`
- `generatedAt`: 평가 산출 시각

## forecast_accuracy 핵심 필드
- `modelScope.summaryModelFamily`: 전체 요약에 포함한 최신 운영 모델 계열
- `modelScope.excludedDates`: baseline 등 다른 모델 계열이라 전체 요약에서 제외한 날짜
- `summary.modelMaeMw`, `summary.tepcoMaeMw`: 최근 비교 가능 시간의 MAE
- `summary.modelWapePct`, `summary.tepcoWapePct`: 총 실적 수요 대비 절대 오차율
- `summary.modelRmseMw`, `summary.tepcoRmseMw`: 큰 오차 리스크를 반영한 RMSE
- `summary.modelMaxErrorMw`, `summary.tepcoMaxErrorMw`: 비교 구간의 단일 시간 최대 오차
- `summary.modelAdvantageHours`, `summary.tepcoAdvantageHours`: 시간별 절대 오차 기준 우위 시간. 하위 호환을 위해 `summary.modelWins`, `summary.tepcoWins`도 유지
- `summary.modelAdvantageRate`: `modelAdvantageHours / summary.hours`
- `daily[]`: 일별 MAE/WAPE/RMSE와 우위 시간. `includedInSummary`가 `false`인 날짜는 전체 요약에서 제외됨
- `daily[].maeGapMw`: 모델 MAE에서 TEPCO MAE를 뺀 값. 양수면 TEPCO가 더 가까웠고 음수면 모델이 더 가까웠음
- `daily[].wapeGapPct`: 모델 WAPE에서 TEPCO WAPE를 뺀 값
- `daily[].verdict`: `model_better`, `tepco_better`, `close`, `mixed`, `insufficient` 중 하나인 일별 운영 판단
- `hourly[]`: 시간대별 MAE/WAPE/RMSE와 우위 시간

## model_backtest 핵심 필드
- `methodology`: 백테스트 방식과 기준일
- `trainPeriod`, `testPeriod`: 학습/테스트 구간
- `baseline`, `lightgbm`: RMSE, MAE, MAPE, sample count
- `improvementPct`: 베이스라인 대비 LightGBM 개선율

---

# 6) reports/ai/daily/*.json

## 목적
대시보드의 **일일 리포트 탭**에 표시할 AI 운영 분석 리포트입니다. AI 리포트는 deterministic JSON 산출물 위에 얹는 해설 레이어이며, 지표를 다시 계산하거나 모델 설정을 자동 변경하지 않습니다.

## 경로 예
- `web/public/reports/ai/daily/2026-05-23.json`
- `web/public/reports/ai/daily/index.json`
- `web/public/reports/ai/daily/ko/2026-05-23.json`
- `web/public/reports/ai/daily/en/2026-05-23.json`
- `web/public/reports/ai/daily/ja/2026-05-23.json`

## 일일 리포트 스키마
```json
{
  "schemaVersion": "1.0.0",
  "reportType": "ai_daily_operation_report",
  "timezone": "Asia/Tokyo",
  "date": "2026-05-23",
  "generatedAt": "2026-05-24T09:25:00+09:00",
  "availability": "ok",
  "language": "ko",
  "contentLanguage": "ko",
  "generator": {
    "provider": "fallback",
    "model": null,
    "localizationModel": null,
    "localizationStatus": "not_requested",
    "localizationFallback": null,
    "promptVersion": "fallback_rules_v1",
    "schemaVersion": "1.0.0"
  },
  "inputRefs": {
    "operationReport": "reports/daily/2026-05-23.json",
    "internalDiagnostics": "reports/internal/daily-diagnostics/2026-05-23.json",
    "operationalCalibration": "reports/internal/operational-calibration/2026-05-23.json",
    "operationalCalibrationHistory": "reports/internal/operational-calibration/snapshots/2026-05-23/index.json",
    "alerts": "alerts/2026-05-23.json",
    "forecast": "forecast/2026-05-23.json",
    "actual": "actual/2026-05-23.json",
    "metrics": "metrics/forecast_accuracy.json"
  },
  "inputSnapshot": {
    "schemaVersion": "1.0.0",
    "createdAt": "2026-05-24T09:25:00+09:00",
    "fingerprint": "sha256:...",
    "sources": {
      "operationReport": {
        "path": "reports/daily/2026-05-23.json",
        "exists": true,
        "date": "2026-05-23",
        "generatedAt": "2026-05-24T09:20:00+09:00",
        "fingerprint": "sha256:..."
      }
    }
  },
  "dataQuality": {
    "comparableHours": 21,
    "observedHours": 21,
    "fallbackActualHours": 0,
    "calibrationSnapshotCount": 3,
    "limitations": []
  },
  "executiveSummary": {
    "severity": "warning",
    "headline": "오전 ramp 과대예측이 일일 오차를 지배했습니다.",
    "summary": "모델은 전체적으로 TEPCO보다 뒤졌으며, 주로 07~08시 큰 오차와 이후 residual handoff 문제가 영향을 줬습니다.",
    "modelVerdict": "tepco_better",
    "confidence": "medium"
  },
  "performance": {
    "comparableHours": 21,
    "modelMaeMw": 535.2,
    "tepcoMaeMw": 279.0,
    "modelWapePct": 2.23,
    "tepcoWapePct": 1.16,
    "modelRmseMw": 732.9,
    "tepcoRmseMw": 382.4,
    "modelMaxErrorMw": 2008.3,
    "tepcoMaxErrorMw": 1110.0,
    "modelMaxErrorHour": 8,
    "tepcoMaxErrorHour": 8,
    "maeGapMw": 256.2,
    "wapeGapPct": 1.07,
    "verdict": "tepco_better",
    "modelAdvantageHours": 3,
    "tepcoAdvantageHours": 18,
    "equalHours": 0,
    "modelAdvantageRate": 0.143
  },
  "rootCauseHypotheses": [
    {
      "id": "h1",
      "severity": "warning",
      "confidence": "medium",
      "evidenceStatus": "partial",
      "title": "평일 lag가 비영업일 오전 ramp를 오염시켰을 가능성",
      "explanation": "가장 큰 오차가 오전 ramp 구간에서 발생했고, 24시간 lag가 다른 영업/비영업 타입에서 왔습니다.",
      "evidence": [
        {
          "source": "reports/daily",
          "metric": "modelAbsErrorMw",
          "value": 2008.3,
          "unit": "MW",
          "hour": 8,
          "timeBand": "morning_ramp"
        }
      ],
      "relatedHours": [7, 8],
      "relatedTimeBands": ["morning_ramp"],
      "relatedFeatures": [
        "lag_24h",
        "lag_24h_business_type_mismatch",
        "recent_same_business_type_mean"
      ],
      "counterEvidence": [
        "09시 부근에서 모델이 회복했으므로, 문제가 초기 ramp handoff에 제한됐을 가능성도 있습니다."
      ]
    }
  ],
  "featureRecommendations": [
    {
      "id": "r1",
      "priority": "medium",
      "type": "calibration",
      "target": "intraday_correction.business_type_transition_prior",
      "suggestion": "prior handoff를 마지막 실측 시간이 오전 ramp에 도달할 때까지 유지할지 검토합니다.",
      "expectedEffect": "전날 lag가 과열된 평일→비영업일 전환에서 이른 오전 과대예측을 줄입니다.",
      "risk": "same-business anchor가 너무 낮으면 실제로 높은 주말 수요를 억누를 수 있습니다.",
      "validationPlan": "최근 금요일→토요일 전환일을 replay하여 변경 전후 MAE/WAPE를 비교합니다.",
      "linkedHypotheses": ["h1"],
      "autoApply": false
    }
  ],
  "operatorNotes": [
    "피처 개선 제안은 검토 후보일 뿐이며 자동 반영하지 않습니다."
  ],
  "limitations": [
    "AI 리포트는 deterministic 지표에 대한 해석이며, 원천 truth가 아닙니다."
  ]
}
```

## 인덱스 스키마
```json
{
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",
  "generatedAt": "2026-05-24T09:25:00+09:00",
  "availability": "ok",
  "latest": {
    "date": "2026-05-23",
    "availability": "ok",
    "severity": "warning",
    "headline": "오전 ramp 과대예측이 일일 오차를 지배했습니다.",
    "modelVerdict": "tepco_better"
  },
  "reports": [
    {
      "date": "2026-05-23",
      "availability": "ok",
      "severity": "warning",
      "headline": "오전 ramp 과대예측이 일일 오차를 지배했습니다.",
      "modelVerdict": "tepco_better",
      "modelMaeMw": 535.2,
      "tepcoMaeMw": 279.0
    }
  ]
}
```

## 필드 규칙
- `performance`는 deterministic 일일 리포트 지표를 복사합니다. AI 생성기는 이 값을 새로 계산하거나 임의로 만들면 안 됩니다.
- `rootCauseHypotheses[].evidence[]`는 반드시 입력 source와 metric을 포함합니다.
- `inputRefs.operationalCalibration`은 선택값이며 해당 날짜의 intraday 보정 리포트가 없으면 `null`일 수 있습니다.
- `inputRefs.operationalCalibrationHistory`는 선택값이며 해당 날짜의 intraday 보정 snapshot index가 없으면 `null`일 수 있습니다.
- `inputSnapshot`은 AI 해설이 어떤 deterministic 입력 버전을 기준으로 작성됐는지 기록합니다. 참조 입력 JSON이 바뀌면 fingerprint가 달라지지만, 기존 AI 리포트 본문은 명시적 재생성 전까지 보존합니다.
- `rootCauseHypotheses[].evidenceStatus`는 입력 JSON에 직접적인 플래그/제어 수치가 있으면 `"confirmed"`, 지표/피처상 강한 정황이면 `"partial"`, 덮어쓰기 구조 때문에 확인할 수 없으면 `"not_observed"`를 사용합니다. `"not_observed"` 가설은 반드시 `confidence: "low"`로 낮춥니다.
- `featureRecommendations[]`는 개선 후보입니다. `autoApply`는 항상 `false`입니다.
- `relatedFeatures[]`에는 내부 피처명을 포함할 수 있습니다. 이 탭은 운영 분석용 화면입니다.
- deterministic fallback 리포트가 정상 생성되면 `availability: "ok"`, `generator.provider: "fallback"`, `generator.model: null`을 사용합니다. OpenAI 키가 있으면 OpenAI는 자연어 해설 레이어만 생성하며, `performance`, `inputRefs`, `dataQuality`는 deterministic 코드가 고정합니다. `availability: "failed"`는 생성 시도 후 실패한 경우에만 사용합니다.
- `language`는 생성된 리포트 경로의 대상 언어입니다. `ko`, `en`, `ja`별 리포트를 각각 생성하며, 대시보드는 현재 UI locale에 맞는 하위 경로를 읽습니다. 루트 `reports/ai/daily/YYYY-MM-DD.json`는 하위 호환용 한국어 리포트입니다.
- `contentLanguage`는 실제 화면에 표시되는 본문 언어입니다. 일반적으로 `language`와 같지만, 번역 호출이 실패하면 `ko`/`ja` 경로도 `contentLanguage: "en"`으로 영어 마스터 리포트를 표시할 수 있습니다.
- AI 리포트는 ETL 실행에서만 생성합니다. intraday/status-only 실행은 리포트 본문을 만들거나 갱신하지 않습니다.
- 같은 날짜/언어의 리포트 JSON이 이미 있으면 후속 ETL 재시도에서는 기존 파일을 보존합니다. 이때 index는 재구성할 수 있지만, 본문 JSON과 OpenAI 호출은 다시 수행하지 않습니다.
- OpenAI 호출은 기본적으로 비용 제한을 둡니다. 최신 일일 리포트 날짜만 OpenAI 후보이며, 기본 체인은 최대 2회 호출을 사용합니다. 먼저 압축된 fact packet으로 영어 마스터 분석을 만들고(`OPENAI_DAILY_REPORT_MODEL`, 기본값 `gpt-5.4-mini`), 그 영어 마스터를 기준으로 저비용 모델이 `ko`/`ja`를 현지화합니다(`OPENAI_DAILY_REPORT_LOCALIZATION_MODEL`, 기본값 `gpt-4o-mini`). 기본 상한은 `OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN=2`입니다. 범위를 줄이거나 넓히려면 `OPENAI_DAILY_REPORT_LOCALES`, `OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN`, `OPENAI_DAILY_REPORT_LATEST_ONLY`를 명시적으로 조정합니다.
- 번역 호출이 실패하거나 한국어/일본어 텍스트 검증에 실패하면, 해당 언어 경로는 영어 마스터 본문으로 fallback하며 `generator.localizationStatus: "fallback_en"`, `generator.localizationFallback: "en"`을 기록합니다.
- OpenAI 입력에는 전체 시간별 진단 row를 넘기지 않고 압축된 fact packet만 전달합니다. 프롬프트 입력에서는 fallback 자연어 객체, 규칙 기반 `insights`, 파일 path, SHA-256 fingerprint, `performance`와 중복되는 summary 블록을 제외합니다. deterministic 지표, 입력 경로, 데이터 품질, `inputSnapshot`은 Python 코드가 고정합니다.

---

# 대시보드 구현 팁(프론트)
- 결측은 `null`로 처리하여 라인이 끊기도록(연속선 금지)
- `availability !== "ok"`이면 탭 상단에 배지/메시지 표시
- `status.json`의 `coverageTo`와 `missingDays`는 항상 표시(신뢰성)

---

# MVP → 3년치 확장 시 유지 규칙
- **파일 경로/스키마는 고정**
- 변경은 config(학습 기간, baseline 윈도우, 임계값)로만
- `trainedFrom`만 바뀌고 `series/alerts` 구조는 동일
