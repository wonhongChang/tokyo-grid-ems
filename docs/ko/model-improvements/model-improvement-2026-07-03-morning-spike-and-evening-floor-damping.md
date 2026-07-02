# 2026-07-03 오전 스파이크와 저녁 floor 감쇠

언어: [English](../../en/model-improvements/model-improvement-2026-07-03-morning-spike-and-evening-floor-damping.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-03-morning-spike-and-evening-floor-damping.md)

## 배경

2026-07-02 서빙 예측에서는 서로 다른 세 가지 실패 모드가 동시에 보였다.

- 08시 JST는 영업일 오전 램프업을 낮게 잡았다.
- 이후 10~12시는 오전 실측이 들어온 뒤 보정이 과하게 위로 작동했다.
- 20~23시는 실측과 lag/recent shape가 이미 하락 중인데도 `negative_residual_near_term_floor`가 하방 보정을 너무 많이 되돌려 높게 남았다.

다음날인 2026-07-03 사전 관측 예측에서도 09시 JST 단발 스파이크가 드러났다. raw/analog 조정 곡선이 lag/recent shape 지지보다 훨씬 크게 뛰고, 10시에 바로 내려오는 형태였다.

이번 변경은 TEPCO 예측을 입력으로 쓰지 않는다. TEPCO는 외부 비교 기준으로만 사용한다.

## 변경 사항

### 오전 실측 램프 floor의 shape 지지 cap

`intraday_correction.morning_observed_ramp_floor`에 두 가지 지지 조건을 추가했다.

- `min_support_delta_mw`
- `support_delta_fraction`

강한 오전 실측 램프는 계속 보호하지만, 대상 시간의 lag/recent shape가 이미 완만하거나 하락 중이면 최신 실측 기울기만 보고 다음 시간을 끝까지 들어 올리지 않는다. 2026-07-02처럼 09시 실측은 강했지만 10~11시 shape 지지가 충분하지 않았던 경우를 겨냥한 수정이다.

### 하락 shape 인식형 negative residual floor 감쇠

`intraday_correction.negative_residual_near_term_floor`에 `decline_support_damping`을 추가했다.

다음 조건이 동시에 맞으면 floor가 하방 보정을 되돌리는 강도를 줄인다.

- 최신 당일 실측 기울기가 명확히 음수
- 대상 시간의 lag/recent shape도 하락 방향

이렇게 하면 실제 저녁 수요가 내려가고 있는데 floor가 억지로 예측선을 위로 복구하는 문제를 줄일 수 있다. 2026-07-02 20~23시 문제가 이 케이스였다.

운영 스냅샷에는 아래 필드를 추가했다.

- `negativeResidualNearTermSupportDeltaMw`
- `negativeResidualNearTermDeclineDampingFactor`

AI 운영 리포트의 압축 fact packet에도 같은 정보를 포함한다.

### 사전 관측 오전 단발 스파이크 가드

`adjustment.localized_shape_spike_guard.morning_spike`를 추가했다.

이 가드는 오전 특정 시간이 다음 조건을 모두 만족할 때만 보수적으로 낮춘다.

- 앞뒤 시간보다 튀어 있는 local peak
- forecast 증가폭이 lag/recent shape 지지보다 과도함
- 다음 시간에 바로 큰 하락이 있음
- 24시간 기상 변화가 강한 상승을 충분히 설명하지 못함

2026-07-03 09시 예측처럼, 당일 실측이 없는 상태에서 09시에 약 4.6GW 뛰고 10시에 약 1.6GW 내려가는 모양을 막기 위한 장치다.

## 검증

다음 회귀 테스트를 추가했다.

- 오전 실측 램프 floor가 target-hour shape 지지를 부분적으로만 반영하는지
- 저녁 하락 shape에서 negative residual near-term floor 복구량을 감쇠하는지
- 관측 전 영업일 오전 단발 스파이크를 줄이는지

대상 테스트:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_observed_morning_ramp_floor_uses_fractional_support_and_skips_weak_targets tests/test_intraday_correction.py::test_intraday_near_term_floor_damps_restore_when_evening_shape_points_down tests/test_adjustment.py::test_localized_shape_spike_guard_dampens_business_morning_pre_observation_spike -q
```

결과: `3 passed`.

관련 테스트:

```powershell
python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py tests/test_ai_daily_report.py -q
```

결과: `155 passed`.

## 운영 메모

이번 변경은 보수적인 shape 제어다. TEPCO를 따라가도록 만들지 않고, 이미 서빙된 예측값도 다시 쓰지 않는다.

다음 관찰 포인트는 오전 floor가 실제 강한 램프업 날을 여전히 보호하면서도, 2026-07-02의 10~12시 과리프트를 반복하지 않는지다.
