# 2026-06-20 비영업일 prior 및 plateau 가드

언어: [English](../../en/model-improvements/model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md)

## 문제

2026-06-20 토요일 서빙 예측에서 비영업일 전용으로 분리해서 봐야 하는 실패 패턴이 세 가지 확인됐다.

- 당일 실측이 들어오기 전, 여러 no-observation prior가 겹치면서 새벽과 낮 일부 구간을 raw 모델보다 과하게 아래로 밀었다. 00:54 JST 실행분은 cooler-day scale bias, day-boundary carryover, business-type transition prior가 함께 들어갔고, 이후 published forecast freeze 때문에 일부 값이 고정됐다.
- 오전 실측이 들어온 뒤에는 주말 램프업 자체는 살아 있었지만, `morning_observed_ramp_floor`가 영업일 전용이라 10:00-11:00 지지가 약했다.
- 습한 오후에는 14:00-15:00 예측이 실측보다 낮게 남았다. 전날 대비 기온 델타는 낮았기 때문에 기존 영업일 heat/ramp lift가 비영업일의 고습도 plateau를 인식하지 못했다.

저녁 구간도 함께 점검했다. 기존 non-business evening residual damping은 이미 작동 중이었으므로, 이번 수정에서는 근거리 실측 근거가 없는 강한 저녁 cap을 새로 추가하지 않았다.

## 변경

- `pre_observation_prior_stack_cap`을 추가해 당일 실측이 없거나 거의 없을 때 no-observation prior들이 합쳐져 생기는 과도한 하방 이동을 제한했다.
- `morning_observed_ramp_floor`를 비영업일에도 적용하되, 더 작은 slope fraction과 lift cap을 사용하도록 했다.
- `daytime_sustained_underforecast_lift`에 14:00-15:00 비영업일 고습도 plateau 분기를 좁게 추가했다.
- 시간별 residual carryover 로그에 습도와 불쾌지수 진단값을 남기도록 했다.
- AI 운영 리포트가 새 가드 이름을 직접 언급할 수 있도록 feature catalog를 갱신했다.

## 리스크 제어

- TEPCO 예측값은 보정 입력으로 사용하지 않는다.
- no-observation cap은 raw forecast 대비 과도한 하방 이동만 되돌리며, 새로운 상방 예측 체제를 만들지 않는다.
- 주말 오전 floor는 반드시 당일 실측 램프업 근거가 있을 때만 작동한다.
- 고습도 plateau lift는 지속적인 양수 residual, 양수 residual pressure, 높은 습도 또는 불쾌지수가 함께 있어야만 작동한다.
- 저녁 shape는 강제로 누르지 않고 계속 관측 대상으로 둔다.

## 검증

```text
tests/test_intraday_correction.py::test_intraday_caps_pre_observation_prior_stack_before_weekend_actuals
tests/test_intraday_correction.py::test_intraday_weekend_morning_ramp_floor_lifts_observed_non_business_ramp
tests/test_intraday_correction.py::test_intraday_weekend_humid_daytime_underforecast_lifts_plateau_hours
```
