# 2026-06-14 비영업일 shape 및 residual 가드

Languages: [English](../../en/model-improvements/model-improvement-2026-06-14-non-business-shape-and-residual-guards.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-14-non-business-shape-and-residual-guards.md)

## 문제

2026-06-14 일요일 서빙 차트의 09:00-19:00 구간에서는 서로 다른 세 가지 문제가 섞여 있었습니다.

- 09:00-10:00은 analogous-day 보정이 비영업일 오전 라인을 raw LightGBM보다 아래로 밀면서 과소예측이 커졌습니다. raw 라인이 실제에 더 가까웠지만, 후처리 라인이 작은 음수 analog shift를 그대로 허용했습니다.
- 14:00-17:00은 오후 plateau 과대예측 문제가 일요일에도 나타난 케이스였습니다. 최근 실측은 모델이 높게 가고 있음을 보여줬지만, `afternoon_observed_anchor_cap`이 영업일 전용으로 묶여 있어 일요일 오후에는 작동하지 않았습니다.
- 18:00-19:00은 18:31 스냅샷의 음수 intraday residual carryover가 너무 강하게 남아 예측선이 낮아졌습니다. 이때는 15:00-17:00 실측이 이미 회복 중이었으므로, 하방 residual은 그대로 이월하기보다 감쇠하는 편이 맞았습니다.

11:00-12:00 과대예측은 대부분 raw LightGBM shape 문제로 남았습니다. 해당 구간이 닫히기 전에는 안전하게 개입할 당일 증거가 부족했기 때문에, 이를 억지로 누르면 또 다른 하드코딩 점심 규칙이 될 위험이 큽니다.

## 변경 사항

- `non_business_analog_downshift_guard`를 더 엄격하게 조정했습니다.
  - 비영업일 ramp support가 있을 때는 작은 음수 analog downshift도 막습니다.
  - 가드 조건에서 기본 하방 shift 허용폭을 300MW에서 0MW로 줄였습니다.
  - analog day가 지지되는 weekend morning ramp를 지워버리지 못하게 raw LightGBM 흐름을 더 보존합니다.
- `afternoon_observed_anchor_cap`을 비영업일에도 적용 가능하게 했습니다.
  - `business_day_only`를 `false`로 변경했습니다.
  - 대상 시간에 17:00을 추가했습니다.
  - 여전히 최근 실측 과대예측 증거가 있어야 작동하므로, 일요일 전용 하드코딩이 아니라 관측 기반 reactive guard입니다.
- `non_business_evening_negative_residual_damping`을 추가했습니다.
  - 현재는 비영업일 18:00-20:00에만 적용합니다.
  - base residual이 강한 음수이고, 최근 당일 실측 slope가 회복 중이며, lag/recent same-business delta가 평탄 또는 상승 저녁을 부정하지 않을 때만 작동합니다.
  - raw 예측을 올리는 것이 아니라 음수 residual carryover만 감쇠합니다. TEPCO를 추종하지 않습니다.
- AI 운영 리포트가 새 음수 residual damping을 calibration JSON에서 읽어 설명할 수 있도록 관련 context 필드를 추가했습니다.

## 기대 효과

2026-06-14 공개 데이터 기준으로 다음 패턴을 줄이는 것이 목적입니다.

- 09:00과 10:00에서 지지되는 비영업일 analog downshift가 raw LightGBM 아래로 내려가는 문제
- 16:00과 17:00에서 일요일이라는 이유만으로 observed over-forecast cap이 빠지는 문제
- 18:00과 19:00에서 당일 실측이 이미 회복 중인데도 음수 residual carryover가 미래 예측선을 과하게 누르는 문제

이미 freeze된 과거 서빙선은 되돌려 쓰지 않습니다. 같은 증거 패턴이 다음 intraday 실행에서 들어올 때 예측선을 더 안정적으로 만들기 위한 변경이며, TEPCO는 여전히 진단 기준일 뿐 보정 타깃이 아닙니다.

## 남은 리스크

11:00-12:00 일요일 과대예측은 아직 raw 모델 shape 문제입니다. 다음 단계는 넓은 후처리 cap이 아니라, 비영업일 점심 shape에 대한 feature/backtest 작업이 더 안전합니다.

## 검증

```text
tests/test_adjustment.py::test_guard_caps_non_business_analog_downshift_when_ramp_is_supported
tests/test_adjustment.py::test_guard_keeps_non_business_analog_downshift_without_shape_support
tests/test_intraday_correction.py::test_intraday_afternoon_observed_anchor_cap_can_run_on_non_business_days
tests/test_intraday_correction.py::test_intraday_damps_non_business_evening_negative_carryover_when_actual_recovers

Full suite: 395 passed
```
