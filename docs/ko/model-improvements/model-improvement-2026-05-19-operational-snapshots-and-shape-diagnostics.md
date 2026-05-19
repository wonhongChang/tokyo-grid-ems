# 2026-05-19 예측 스냅샷과 shape 진단

> intraday 예측 사고를 나중에 운영 관점에서 다시 분석하기 위한 후속 개선 기록.

언어: [English](../../en/model-improvements/model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md)

---

## 왜 추가했나

2026-05-19 문제는 단순히 MAE가 나쁜 문제가 아니었다. 더 중요한 질문은 다음이었다.

> 모델이 각 갱신 시점에 무엇을 보고 있었고, 왜 공개 예측선의 모양이 바뀌었는가?

최신 `forecast/YYYY-MM-DD.json`만 보관하면 현재 대시보드 상태는 알 수 있지만, lead-time별 예측 맥락은 사라진다. 운영 예측 모델이라면 갱신 시점별 예측 이력이 필요하다.

---

## 변경 사항

### 1. Lead-time 예측 스냅샷

ETL과 intraday 실행 시 제한된 예측 스냅샷을 아래 위치에 저장한다.

```text
web/public/forecast_snapshots/YYYY-MM-DD/
```

각 스냅샷에는 다음이 들어간다.

- target date
- 생성 시각
- 실행 타입 (`etl`, `intraday`, 수동 refresh 계열)
- 모델 이름/버전
- peak 요약
- 시간별 예측 series 전체
- 생성 시점에 확보된 실측 시간 수와 TEPCO fallback 시간 수

보존 범위는 의도적으로 제한했다.

- `retention_days: 21`
- `max_per_day: 16`

최근 운영 문제를 분석하기엔 충분하지만, data branch가 무제한 데이터베이스가 되지는 않도록 했다.

### 2. Shape 진단

daily operation report에 `shape` 섹션을 추가했다.

다음 값들의 시간 간 변화량을 비교한다.

- 실제 수요
- 자체 모델 예측
- TEPCO 예측

이렇게 하면 단순 MAE만으로는 숨겨지는 문제, 예를 들어 실측은 거의 변하지 않았는데 모델 예측선만 수천 MW 급락하는 경우를 잡아낼 수 있다.

### 3. Weather-delta 진단

내부 daily diagnostics에 다음 요약을 추가했다.

- `coolingDelta24hByBand`
- `weatherDeltaRiskByBand`

24시간 전 대비 날씨 변화 피처가 오전/주간/오후 구간에서 도움이 되는지, 혹은 모델을 잘못 끌고 가는지 확인하기 위한 자료다.

### 4. Negative residual damping

intraday residual correction은 정오 이후 음수 residual 보정을 약하게 적용하도록 했다.

일시적인 양의 모델 오차를 보고 가까운 미래 수요를 과하게 아래로 끌어내리는 상황을 줄이기 위한 조치다. 가장 가까운 미래 시간대에는 기존 양방향 ramp guard도 계속 작동한다.

---

## 안전 메모

- 스냅샷은 data branch의 공개 정적 JSON이지만 UI에서는 직접 링크하지 않는다.
- 스냅샷은 진단 산출물이며 학습 actual로 쓰지 않는다.
- TEPCO forecast fallback은 intraday 실측이 아직 없는 시간에만 제한적으로 사용한다.
- 더 공격적인 피처를 추가하기 전에, 먼저 운영 사고를 재현하고 해석할 수 있는 기반을 만든 변경이다.

---

## 테스트

다음을 검증하는 테스트를 추가했다.

- 스냅샷 보존 개수와 index 생성
- 스냅샷의 실측/fallback 시간 수 기록
- daily operation report의 비정상 shape 하락 감지
- weather-delta 내부 진단 요약
- 오후 음수 residual damping
