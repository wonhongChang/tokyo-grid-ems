# 학생을 위한 프로젝트 전체 설명

언어: [English](../en/project-walkthrough.md) · [日本語](../ja/project-walkthrough.md)

이 문서는 코딩과 데이터 파이프라인을 배우는 학생이 Tokyo Grid EMS 전체 구조를 이해할 수 있도록 설명합니다.

---

## 이 프로젝트는 무엇을 하나요?

Tokyo Grid EMS는 TEPCO가 공개하는 전력 수요 CSV를 가져와서 웹 대시보드로 보여주는 프로젝트입니다.

대시보드는 네 가지 질문에 답합니다.

1. 어제 전력 사용량은 어땠나?
2. 이상 징후가 있었나?
3. 오늘과 내일 전력 수요는 어떻게 예측되나?
4. 내 모델은 TEPCO 공식 예측보다 얼마나 잘 맞고 있나?

---

## 전체 흐름

```text
TEPCO CSV 파일
  -> Python ETL
  -> 정리된 시간별 데이터
  -> 예측 모델
  -> 이상탐지
  -> JSON 파일
  -> GitHub Pages의 React 대시보드
```

이 프로젝트에는 항상 켜져 있는 백엔드 서버가 없습니다. GitHub Actions가 정해진 시간에 Python 작업을 실행하고, 결과 JSON을 저장한 뒤, GitHub Pages가 정적 대시보드를 제공합니다.

---

## TEPCO 데이터는 두 종류입니다

TEPCO는 데이터를 두 방식으로 제공합니다.

| 데이터 | 갱신 시점 | 프로젝트에서 쓰는 방식 |
|---|---|---|
| 월별 ZIP | 오전 JST 기준, 확정 이력 데이터 포함 | 메인 ETL 소스 |
| Intraday CSV | 당일 중 계속 갱신 | 월별 ZIP이 따라오기 전 오늘 실측 보강 |

그래서 workflow도 두 개입니다.

- `ETL + Deploy`: 확정 데이터 처리와 모델 학습 담당
- `Intraday Update`: 당일 데이터와 예측/status 갱신 담당

---

## 주요 폴더

```text
python/
  etl/                 데이터 다운로드, 파싱, cache, JSON 생성
  forecast/            baseline, LightGBM, 피처 생성, intraday 보정
  anomaly/             이상탐지 규칙
  eval/                백테스트와 TEPCO 비교

web/
  src/                 React 대시보드 소스
  public/              workflow 실행 중 생성되는 JSON

docs/                  프로젝트 문서
tests/                 자동 테스트
```

처음 읽는다면 이 순서가 좋습니다.

1. `python/etl/fetch_tepco.py`
2. `python/tepc_parser.py`
3. `python/etl/run_batch.py`
4. `python/forecast/feature_builder.py`
5. `python/forecast/lgbm_model.py`
6. `python/anomaly/detector.py`
7. `web/src/App.tsx`
8. `web/src/components/ForecastChart.tsx`
9. `web/src/components/ValidationPanel.tsx`

---

## 여기서 ETL이란?

ETL은 세 단계를 뜻합니다.

- Extract: TEPCO CSV나 ZIP을 다운로드합니다.
- Transform: 일본어 CSV 테이블을 파싱하고, 단위를 바꾸고, 시간대를 붙이고, 기온 데이터를 연결합니다.
- Load: 대시보드가 바로 읽을 수 있는 JSON을 만듭니다.

생성되는 대표 파일은 다음과 같습니다.

```text
status.json
actual/YYYY-MM-DD.json
forecast/YYYY-MM-DD.json
alerts/YYYY-MM-DD.json
metrics/forecast_accuracy.json
metrics/model_backtest.json
```

React 앱은 예측을 직접 계산하지 않습니다. 이미 만들어진 JSON을 읽어서 시각화합니다.

---

## cache가 필요한 이유

예측 모델은 과거 데이터가 필요합니다. 매번 모든 CSV를 다시 읽으면 느리기 때문에, ETL은 시간별 cache를 유지합니다.

```text
web/public/.hourly_cache.parquet
```

이 cache에는 시간별 실적 수요, TEPCO 예측, 공급력, 사용률, 기온이 들어갑니다.

이런 생성 데이터는 `main`에 커밋하지 않고, GitHub Actions가 `data` 브랜치에 저장합니다.

---

## 예측 모델을 쉽게 말하면

모델은 이렇게 질문합니다.

> "내일 각 시간의 전력 수요는 얼마일까?"

모델이 참고하는 힌트는 다음과 같습니다.

- 어제 같은 시간 수요
- 지난주 같은 시간 수요
- 요일과 공휴일 여부
- 최근 4주 평균
- 기온
- 어제/지난주 값이 연휴 때문에 낮게 나온 값인지 여부

LightGBM은 이 힌트들 사이의 패턴을 학습합니다. 문제가 생기면 baseline 모델로 돌아갈 수 있습니다.

---

## Intraday 보정

당일 실측이 쌓이면 모델은 자기 예측과 실제값을 비교할 수 있습니다.

실제 수요가 예측보다 계속 높으면 남은 시간 예측을 올리고, 계속 낮으면 내립니다.

23:40 JST에도 23:00 실측이 아직 없을 수 있습니다. 이때는 TEPCO 예측값을 임시로 사용하고 아래처럼 표시합니다.

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

이 값은 다음 예측 입력에는 사용할 수 있지만, 모델 점수 계산이나 이상탐지의 진짜 실측 판정에는 사용하지 않습니다.

---

## 이상탐지

이 프로젝트는 이상 이벤트를 세 가지로 나눕니다.

| 이벤트 | 의미 |
|---|---|
| Reserve Risk | 사용률이 높아 공급 여유가 줄어든 상태 |
| Spike / Drop | 실적 수요가 예측 밴드를 벗어난 상태 |
| Drift | 모델이 여러 시간 동안 한쪽으로 계속 빗나간 상태 |

중요한 점은 "모델이 틀렸다"와 "전력 수급이 위험하다"를 분리했다는 것입니다.

---

## 검증

검증 탭은 두 가지 역할을 합니다.

| 리포트 | 목적 |
|---|---|
| Model backtest | 과거 데이터에서 LightGBM이 baseline보다 나은지 확인 |
| Forecast accuracy | 운영 중 자체 모델과 TEPCO 예측 중 어느 쪽이 실적에 가까웠는지 비교 |

TEPCO 예측은 공식 예측이라 강한 기준선입니다. 이 프로젝트의 목표는 TEPCO를 항상 이긴다고 주장하는 것이 아니라, 공개 데이터만으로 만든 모델의 성능을 투명하게 보여주는 것입니다.

---

## 이 프로젝트에서 배울 수 있는 것

- 예약 실행 데이터 파이프라인
- 현실 데이터의 갱신 지연과 시간대 문제
- 소스 코드와 생성 데이터를 분리하는 방법
- 백엔드 서버 없이 정적 대시보드를 운영하는 방법
- 모델을 공정하게 평가하는 방법
- 모델의 한계를 문서화하는 방법
