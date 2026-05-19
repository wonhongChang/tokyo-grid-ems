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
  "series": []
}
```

## 보존 정책
- `config.yaml`의 `forecast_snapshots.retention_days`, `forecast_snapshots.max_per_day`가 제어합니다.
- 현재 기본값은 최근 21개 target date, target date별 최대 16개 스냅샷입니다.

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
- `summary.modelWins`, `summary.tepcoWins`: 시간별 절대 오차 기준 승패
- `daily[]`: 일별 MAE와 승패. `includedInSummary`가 `false`인 날짜는 전체 요약에서 제외됨
- `daily[].maeGapMw`: 모델 MAE에서 TEPCO MAE를 뺀 값. 양수면 TEPCO가 더 가까웠고 음수면 모델이 더 가까웠음
- `daily[].verdict`: `model_better`, `tepco_better`, `close`, `insufficient` 중 하나인 일별 판정
- `hourly[]`: 시간대별 MAE와 승패

## model_backtest 핵심 필드
- `methodology`: 백테스트 방식과 기준일
- `trainPeriod`, `testPeriod`: 학습/테스트 구간
- `baseline`, `lightgbm`: RMSE, MAE, MAPE, sample count
- `improvementPct`: 베이스라인 대비 LightGBM 개선율

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
