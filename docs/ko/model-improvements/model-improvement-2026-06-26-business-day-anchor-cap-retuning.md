# 2026-06-26 영업일 anchor cap 재조정

언어: [English](../../en/model-improvements/model-improvement-2026-06-26-business-day-anchor-cap-retuning.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-26-business-day-anchor-cap-retuning.md)

## 배경

2026-06-26 라이브 예측에서 영업일 따뜻한 오전 램프 구간의 상방 과열이 다시 확인되었습니다.

- 09:00-11:00 JST는 당일 실측이 이미 램프 둔화를 보여주고 있었는데도 모델이 높게 유지되었습니다.
- raw LightGBM 선 자체가 높았고, analogous-day / warm-day 계층이 10:00-14:00 부근의 레벨을 충분히 누르지 못했습니다.
- 이후 intraday 실행은 남은 미래 시간대를 하방으로 보정했지만, 이미 공개된 오전 슬롯은 freeze 정책상 다시 쓸 수 없습니다.

TEPCO 값은 오차 진단을 위한 외부 기준으로만 사용했습니다. 모델 입력이나 보정에는 섞지 않습니다.

## 변경 사항

### 오전 실측 anchor cap 강화

`intraday_correction.morning_observed_anchor_cap`은 최신 오전 관측 슬롯에서 이미 의미 있는 과대예측이 확인된 경우 더 단호하게 작동합니다.

- `min_latest_overforecast_mw`: 500 -> 400
- `cap_buffer_mw`: 250 -> 0
- `shrinkage`: 0.75 -> 1.0
- `max_reduction_mw`: 800 -> 1000

동일한 당일 실측 근거를 유지하되, 과열된 10:00-13:00 선이 여분의 버퍼 때문에 살아남는 문제를 줄였습니다.

### 오후 anchor cap의 완만한 회복 허용

`intraday_correction.afternoon_observed_anchor_cap.max_latest_slope_mw`를 500 MW/h에서 900 MW/h로 완화했습니다.

기존 값은 점심 이후 실측이 완만하게 회복하기만 해도 오후 cap을 꺼버렸습니다. 이제는 모델 과대예측 잔차가 분명하면 완만한 회복 중에도 cap이 유지되고, 매우 강한 실제 램프일 때만 개입을 피합니다.

## 검증

다음 회귀 테스트를 추가했습니다.

- 09:00 관측 잔차가 음수인 따뜻한 영업일 오전에서 10:00-13:00을 더 단호하게 제한하는지
- 점심 이후 실측 slope는 양수지만 잔차가 여전히 과대예측을 가리키는 경우 오후 cap이 작동하는지

대상 intraday correction 테스트:

```text
64 passed
```

## 운영 메모

이 변경은 TEPCO를 추종하지 않고, 이미 공개된 과거 슬롯도 수정하지 않습니다. 당일 실측으로 모델이 높다는 것이 확인된 뒤의 다음 intraday 실행에서 근거리 영업일 cap을 더 안정적으로 적용하기 위한 조정입니다.
