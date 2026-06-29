# 2026-06-29 영업일 오후 shape와 늦은 저녁 carryover 보정

언어: [English](../../en/model-improvements/model-improvement-2026-06-29-business-day-afternoon-shape-and-late-carryover.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-29-business-day-afternoon-shape-and-late-carryover.md)

## 배경

2026-06-29 영업일 예측에서는 여러 단계가 이어져 shape가 깨지는 문제가 확인됐다.

- 09시는 08시 실측이 이미 과대예측을 보여줬는데도 충분히 눌리지 않았다.
- 13~16시는 warm business-day 오후인데도 analog 단계의 과한 하방 이동을 그대로 받아 너무 낮아졌다.
- 21~22시는 오후 과소예측으로 커진 양수 잔차가 늦은 저녁까지 이월되며 높게 남을 가능성이 컸다.

TEPCO 예측은 진단용 외부 기준으로만 사용한다. 모델 입력과 보정 로직은 TEPCO 예측을 사용하지 않는다.

## 변경 사항

### 09시 morning anchor 보호

`intraday_correction.morning_observed_anchor_cap.target_hours`에 `9`를 포함했다.

08시 실측에서 이미 과대예측이 확인된 경우, 10시까지 기다리지 않고 바로 다음 09시 bucket도 보호할 수 있게 했다.

### 영업일 오후 analog 하방 이동 가드

`adjustment.post_holiday_timeband_guard.business_afternoon_analog_downshift_guard`를 추가했다.

warm business-day 오후에 lag/recent shape가 명확한 하락을 지지하지 않는데 analog 단계가 forecast를 크게 낮추는 경우, 하방 이동폭을 제한한다. 이번 케이스처럼 raw LGBM은 이후 실측에 더 가까웠지만 analog 단계가 14~15시를 과하게 낮춘 상황을 겨냥한다.

### 낮 시간 과소예측 lift의 최신 잔차 반응

`intraday_correction.daytime_sustained_underforecast_lift`를 조정했다.

- 적용 시간을 15~16시까지 확장
- 영업일에는 최신 잔차가 강하게 튄 경우 단일 강한 miss로도 보수적으로 작동 가능
- post-midday shape gate는 12~13시에 집중시켜, 이후 더운 오후 회복을 막지 않도록 조정

### 늦은 저녁 양수 carryover 감쇠

`intraday_correction.afternoon_positive_residual_carryover_damping`을 20~22시까지 확장하고, 참조 시간을 19시까지 볼 수 있게 했다.

오후 과소예측으로 생긴 양수 잔차가 lag24/recent shape가 모두 하락을 가리키는 늦은 저녁까지 기계적으로 전파되는 것을 막는다.

## 검증

다음 회귀 테스트를 추가했다.

- 영업일 warm afternoon analog 하방 이동 제한
- 실제 하락 근거가 강한 analog 하방 이동은 유지
- 09시 observed anchor cap
- hot business afternoon의 최신 잔차 기반 daytime lift
- 늦은 저녁 양수 residual carryover damping

검증 명령:

```powershell
python -m pytest -q
```

결과: `422 passed`.

## 운영 메모

이번 패치는 TEPCO를 따라가기 위한 수정이 아니다. 내부 후처리 단계가 당일 실측 근거 또는 lag/recent shape 문맥과 충돌할 때만 과한 이동을 막는 보수적 방어선이다.

다음 영업일 고온 오후에서 확인할 점:

- 13~16시가 analog downshift로 과하게 눌리지 않는지
- 21~22시가 오후 양수 잔차를 과하게 물고 가지 않는지
- 09시 anchor cap이 실제 morning ramp를 지나치게 평탄화하지 않는지
