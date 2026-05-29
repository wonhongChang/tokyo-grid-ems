# 운영 리포트 탭 설명

운영 리포트 탭은 전날 전력 수요 예측 결과를 사람이 읽기 쉬운 형태로 정리하는 일일 해설 화면입니다. 검증 탭이 MAE/WAPE/RMSE 같은 정량 지표를 중심으로 보여준다면, 운영 리포트 탭은 그 지표를 바탕으로 **왜 그런 오차가 발생했는지**, **어떤 보정 레이어가 관련됐는지**, **다음에 무엇을 검토할 수 있는지**를 설명합니다.

---

## 화면의 목적

이 탭의 목적은 모델 예측 결과를 운영 관점에서 복기하는 것입니다.

- 전날 모델과 TEPCO 예측의 성능 차이를 요약
- 가장 크게 빗나간 시간대와 time band를 표시
- lag, 날씨, 영업일/비영업일 전환, intraday 보정 레이어와 관련된 원인 가설을 제시
- 다음 모델 개선 후보를 자동 적용이 아닌 검토 항목으로 남김

운영 리포트는 예측 모델을 직접 바꾸지 않습니다. 화면에 표시되는 해설과 추천은 분석 참고용입니다.

---

## 데이터 생성 흐름

운영 리포트는 ETL 실행 시점에 생성됩니다.

```text
TEPCO CSV / forecast JSON / actual JSON
  -> reports/daily/YYYY-MM-DD.json
  -> reports/internal/daily-diagnostics/YYYY-MM-DD.json
  -> reports/internal/operational-calibration/YYYY-MM-DD.json
  -> reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json
  -> Dashboard Ops Report tab
```

기본적으로 최신 확정 일자, 보통 어제 데이터만 OpenAI 리포트 생성 대상입니다. 같은 날짜/언어 리포트가 이미 있으면 다시 생성하지 않아 API 비용이 반복 발생하지 않습니다.

Intraday/status-only 실행은 오늘 데이터와 예측선을 갱신하지만, 운영 리포트 본문은 다시 쓰지 않습니다.

---

## 리포트 생성 방식

운영 리포트는 두 가지 방식으로 생성될 수 있습니다.

| 방식 | 조건 | 설명 |
|------|------|------|
| deterministic fallback | OpenAI 키가 없거나 호출하지 않을 때 | Python 규칙 기반으로 성능 지표와 주요 오차를 요약 |
| OpenAI 해설 | `OPENAI_API_KEY`가 있을 때 | 압축된 fact packet을 바탕으로 자연어 원인 분석과 개선 후보를 생성 |

OpenAI를 사용하는 경우에도 성능 수치, 입력 파일 참조, 데이터 품질 정보, 커버리지 구분, stage attribution, controller diagnosis, band quality는 Python 코드가 고정합니다. OpenAI는 이 숫자들을 다시 계산하지 않고 해설 레이어만 생성합니다.

---

## 다국어 처리

OpenAI 리포트는 비용과 품질을 위해 2단계로 처리합니다.

1. 영어 마스터 분석 생성
2. 영어 마스터를 기준으로 한국어/일본어 현지화

기본 모델:

```text
OPENAI_DAILY_REPORT_MODEL=gpt-4o-mini
OPENAI_DAILY_REPORT_LOCALIZATION_MODEL=gpt-4o-mini
```

번역이 실패하거나 timeout되면 해당 언어 경로는 영어 마스터 본문을 보여주며, JSON에는 다음 상태가 기록됩니다.

```json
{
  "contentLanguage": "en",
  "generator": {
    "localizationStatus": "fallback_en",
    "localizationFallback": "en"
  }
}
```

UI는 이 상태를 감지해 "영어 원문 표시" 배지를 보여줍니다.

---

## 주요 UI 구성

### 1. 헤더

선택된 날짜, 리포트 생성 방식, 심각도, 모델 판정 결과를 표시합니다.

- `provider: "fallback"`: 시스템 자동 진단
- `provider: "openai"`: AI 심층 운영 해설
- `contentLanguage !== language`: 영어 원문 fallback 표시

### 2. 요약 카드

모델과 TEPCO의 주요 성능 지표를 비교합니다.

- MAE
- WAPE
- RMSE
- 최대 오차
- TEPCO 대비 성능 우위 시간 수

전력 단위는 UI locale의 표시 규칙을 따릅니다. 일본어 UI에서는 TEPCO 기준에 맞춰 `万kW`를 사용합니다.

### 3. 원인 가설

`rootCauseHypotheses[]`를 카드 형태로 표시합니다. 각 가설은 다음 정보를 포함합니다.

- 제목과 설명
- 관련 시간대
- 관련 feature 또는 보정 레이어
- evidenceStatus
- counterEvidence

`evidenceStatus`는 가설의 근거 품질을 나타냅니다.

| 값 | 의미 |
|----|------|
| `confirmed` | 입력 JSON에 직접적인 보정 플래그나 수치가 있음 |
| `partial` | 지표/피처상 강한 정황은 있지만 직접 플래그는 없음 |
| `not_observed` | 덮어쓰기 구조 등으로 중간 이력을 확인할 수 없음 |

`not_observed`는 confidence를 낮게 표시해, 확인되지 않은 내용을 단정하지 않도록 합니다.

### 4. 개선 후보

`featureRecommendations[]`는 다음에 검토할 수 있는 모델/보정 개선 후보입니다.

중요한 원칙:

```json
{
  "autoApply": false
}
```

즉, 운영 리포트는 개선 방향을 제안할 뿐 자동으로 모델 설정을 바꾸지 않습니다.

### 5. 날짜 선택 콤보박스

운영 리포트 탭은 `reports/ai/daily/{locale}/index.json`를 읽어 날짜 목록을 만듭니다.

표시 예:

```text
2026-05-22
2026-05-23
2026-05-24
```

UI는 전체 파일 목록을 직접 훑지 않고 index만 읽습니다. 기본 생성 범위는 최근 14일이므로 콤보박스가 무한히 길어지지 않습니다.

---

## 비용 제어

OpenAI 비용을 막기 위해 다음 제어를 둡니다.

- 최신 확정 일자만 OpenAI 대상
- 기본 최대 호출 수 3회. 현지화 검증 실패 시 1회 재시도까지 포함
- 기존 리포트가 있으면 재생성하지 않음
- OpenAI 입력은 압축된 fact packet만 전달
- fact packet에는 `controllerDiagnosis`, `stageAttribution`, `bandQuality`, `freezeImpact`, `coverageContext`, `rollingPatternContext` 같은 계산 완료 필드를 포함
- 자연어 fallback 문장, 전체 hourly row, SHA fingerprint, 파일 path 등은 프롬프트에서 제외

관련 기본값:

```text
OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN=3
OPENAI_DAILY_REPORT_LATEST_ONLY=true
OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90
OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180
```

GitHub Actions에는 `OPENAI_API_KEY` secret만 있어도 기본값으로 동작합니다. 나머지는 repository variables로 필요할 때만 조정합니다.

---

## JSON 경로

운영 리포트 탭이 사용하는 주요 경로입니다.

```text
web/public/reports/ai/daily/index.json
web/public/reports/ai/daily/ko/index.json
web/public/reports/ai/daily/en/index.json
web/public/reports/ai/daily/ja/index.json
web/public/reports/ai/daily/{locale}/YYYY-MM-DD.json
```

루트 경로 `reports/ai/daily/YYYY-MM-DD.json`는 하위 호환용 한국어 리포트입니다.

---

## 주의할 점

- 운영 리포트는 모델 개선 후보를 제안하지만 자동 적용하지 않습니다.
- OpenAI 해설은 deterministic 지표를 기반으로 하지만, 최종 판단은 검증 탭의 수치와 원천 JSON을 함께 봐야 합니다.
- 중간 intraday 실행 이력이 보존되지 않은 날짜는 일부 원인 가설이 `not_observed`로 표시될 수 있습니다.
- 번역 실패 시 리포트가 비어 있지 않도록 영어 마스터를 fallback으로 표시합니다.
