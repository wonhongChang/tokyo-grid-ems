# 2026-06-15 오전 ramp floor 과대예측 veto

Languages: [English](../../en/model-improvements/model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md)

## 문제

2026-06-15 05:00-12:00 서빙 차트의 오전 문제는 하나의 raw 모델 오차가 아니었습니다.

- 05:00은 주로 이른 시점의 입력/서빙선 freeze 문제였습니다. 이후 입력이 갱신된 사후 재계산선은 훨씬 가까웠지만, 공개 차트의 해당 시간은 이미 고정된 상태였습니다.
- 08:00-10:00은 전날보다 훨씬 시원한 날인데도 높게 잡혔습니다. 특히 09:32 JST 실행에서 `morning_observed_ramp_floor`가 06:00-08:00의 강한 실측 램프업만 보고 10:00을 약 +1,150MW 들어올렸습니다.
- 이 10:00 lift는 이후 관측된 10시 과대예측을 만들었고, 다음 intraday 실행에서 음수 residual이 11:00으로 전파되어 11:00을 너무 낮게 만들었습니다.

즉 floor guard가 실측 ramp 강도는 봤지만, 최신 관측 버킷에서 모델이 이미 충분히 높게 틀렸는지는 확인하지 않았습니다.

## 변경 사항

`morning_observed_ramp_floor`에 `max_latest_overforecast_mw`를 추가했습니다.

- 기본값: `500MW`.
- 최신 관측 시간이 이미 이 기준 이상으로 과대예측이면, floor guard가 가까운 미래 ramp를 추가로 들어올리지 않습니다.
- 최신 관측 버킷이 과하게 높지 않은 정상적인 강한 ramp 케이스에서는 기존 lift 동작을 유지합니다.

이 변경은 raw 모델을 새로 누르는 cap이 아니라, 보조 lift에 대한 veto입니다. 가장 최근 실측 증거가 “이미 모델이 높다”고 말할 때 추가 상방 압력을 넣지 않게 합니다.

## 기대 효과

2026-06-15 패턴 기준 기대 효과는 다음과 같습니다.

- 08:00이 이미 약 1,000MW 과대예측된 상태에서는 10:00에 추가 ramp-floor lift를 넣지 않습니다.
- 그 결과 다음 intraday 실행에서 lift된 10:00 때문에 인위적인 음수 residual이 생길 가능성이 줄어듭니다.
- 11:00이 controller-induced downward swing에 노출되는 정도가 낮아집니다.

05:00의 stale input/freeze 문제와 08:00 raw 모델 높이는 별도 과제로 남습니다.

## 검증

```text
tests/test_intraday_correction.py::test_intraday_correction_lifts_near_future_when_observed_morning_ramp_is_strong
tests/test_intraday_correction.py::test_intraday_correction_skips_morning_ramp_floor_when_latest_observed_bucket_is_already_high

Full suite: 396 passed
```
