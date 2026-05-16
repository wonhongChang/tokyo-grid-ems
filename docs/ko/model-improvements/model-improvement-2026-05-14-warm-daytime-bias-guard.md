# 2026-05-14 따뜻한 낮 시간대 과소예측 보정

> 09:00-18:00 JST 구간에서 반복된 따뜻한 날 과소예측을 보고 추가한 후속 운영 개선 기록입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md) · [日本語](../../ja/model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md)

---

## 왜 필요했나

휴일 래그 기반 주간 고온 guard를 추가한 뒤에도, 최근 운영 데이터에서 따뜻한 평일 낮 시간대 과소예측이 반복되었습니다.

09:00-18:00 JST 기준:

| 날짜 | 모델 bias | 모델 MAE | 메모 |
|---|---:|---:|---|
| 2026-05-11 | -1,294 MW | 1,294 MW | 낮 시간대 전반 과소예측 |
| 2026-05-13 | -704 MW | 751 MW | 따뜻한 오후가 여전히 낮게 잡힘 |
| 2026-05-14 | -866 MW | 930 MW | 09:00-11:00 관측 기준 부분 집계 |

패턴은 골든위크 래그 문제만으로 설명되지 않았습니다. 따뜻한 평일 자체에서도 모델이 냉방 수요를 약하게 보는 구간이 있어, 따뜻한 계절 데이터가 더 쌓이기 전까지 작은 운영 guard가 필요했습니다.

## 예측 개선 내용

`python/forecast/adjustment.py`에 일반 따뜻한 평일 낮 guard를 추가했습니다.

다음 조건을 모두 만족할 때만 작동합니다.

- 시간이 설정된 낮 시간대에 들어감
- 목표 날짜가 영업일임
- `temp_anomaly_doy >= warm_day_min_temp_anomaly_doy`
- 유사일 보정이 이미 예측을 위로 올리고 있지 않음

작동하면 q50과 예측 밴드에 작은 상향 offset을 적용합니다.

관련 설정:

```yaml
adjustment:
  post_holiday_timeband_guard:
    daytime:
      activate_on_warm_day: true
      warm_day_min_temp_anomaly_doy: 1.0
      warm_day_upward_offset_mw: 250
```

## 설계 경계

이 보정은 휴일 래그 guard보다 작게 설계했습니다.

- TEPCO 예측값을 모델 입력으로 사용하지 않습니다.
- 고정된 절대온도 기준이 아니라 계절 대비 기온 편차를 기준으로 작동합니다.
- 유사일 보정이 이미 위쪽으로 움직이면 추가 offset을 넣지 않습니다.
- 주말 또는 공휴일에는 수동 warm-day offset을 넣지 않습니다. 비영업일의 더위 효과는 모델의 날씨 피처가 담당합니다.

목표는 모델을 무조건 높게 잡는 것이 아니라, 반복되는 따뜻한 낮 시간대 과소예측을 완화하는 것입니다.
