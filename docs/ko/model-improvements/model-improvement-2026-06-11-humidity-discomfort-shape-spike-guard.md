# 2026-06-11 습도/불쾌지수 피처와 국소 shape spike 가드

## 문제

최근 서빙 데이터에서 서로 다른 두 가지 shape 문제가 확인됐습니다.

- 2026-06-10 15:00 예측이 한 시간만 튀는 국소 피크를 만들었습니다. 주변 시간, lag 기울기, 최근 같은 영업 타입 shape, 기상 방향성 모두 독립적인 15시 피크를 강하게 지지하지 않았습니다.
- 2026-06-11에는 따뜻하고 습한 영업일 낮 수요가 낮게 잡혔습니다. 기존 모델은 체감온도와 냉방 degree는 사용했지만, 습도/불쾌지수 변화량과 영업시간 습도 교호작용을 LightGBM에 직접 제공하지 않았습니다.

## 변경 내용

- LightGBM 학습 피처 수를 56개에서 63개로 확장했습니다.
- 직접 습도/불쾌지수 피처를 추가했습니다.
  - `humidity_pct`
  - `discomfort_index`
  - `humidity_delta_24h`
  - `discomfort_delta_24h`
  - `business_morning_x_humidity_delta_24h`
  - `business_morning_x_discomfort_delta_24h`
  - `business_daytime_x_discomfort_index`
- 과거 weather cache에 습도 필드가 없는 경우에도 학습 row가 빠지지 않도록 보수적인 fill 로직을 추가했습니다.
- 모델 호환성 버전을 `q025_q50_q975_p95_v10_humidity_discomfort`로 올려, 기존 pickle을 재사용하지 않고 재학습하도록 했습니다.
- `MiddayTransitionGuard` 이후, intraday 보정 이전에 `LocalizedShapeSpikeGuard`를 추가했습니다. 주변 시간보다 한 시간만 과하게 튀고 lag/recent/weather 문맥이 이를 지지하지 않을 때만 제한적으로 감쇠합니다.
- operational calibration snapshot과 AI 리포트 feature catalog에 습도/불쾌지수 필드를 추가했습니다.

## 가드 범위

국소 shape guard는 의도적으로 좁게 작동합니다.

- 영업일만 대상,
- 기본 대상 시간은 13:00-17:00,
- 양쪽 이웃 시간보다 명확하게 높은 한 시간짜리 피크일 때만 평가,
- lag shape, 최근 같은 영업 타입 shape, 당일 실측 기울기, 기상 delta가 실제 피크를 지지하면 개입하지 않음,
- shrinkage와 최대 감쇠폭 cap 적용.

목표는 실제 더운 날 피크를 평평하게 만드는 것이 아니라, analog/post-processing에서 드물게 생기는 국소 shape artifact를 줄이는 것입니다.

## 검증

```text
389 passed
```

추가 단위 테스트는 다음을 확인합니다.

- 근거 없는 15시 단일 spike는 감쇠됨,
- 기상적으로 지지되는 피크는 유지됨.

## 운영 메모

이번 변경은 먼저 원천 피처 개선이고, 가드는 보조 안전장치입니다. 습도/불쾌지수 피처는 따뜻하고 습한 낮 수요를 모델이 직접 학습하도록 돕고, 국소 가드는 드문 후처리 shape artifact를 제한합니다.
