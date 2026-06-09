# 2026-06-09 오후 실측 anchor cap

> 영업일 오후 plateau 구간에서 당일 실측이 이미 모델 과대예측을 확인했을 때, 가까운 미래 예측선만 보수적으로 낮추는 intraday cap입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-06-09-afternoon-observed-anchor-cap.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-09-afternoon-observed-anchor-cap.md)

---

## 배경

2026-06-09 라이브 예측에서는 오전 ramp 문제와 다른 실패 패턴이 나타났습니다.

기존 `morning_observed_anchor_cap`은 의도적으로 오전 후반 구간만 보도록 제한되어 있었습니다. 그래서 13:00-15:00 plateau에는 적용되지 않았습니다. 하지만 12:00-15:00 동안 당일 실측은 반복적으로 모델보다 낮았고, raw/analog-adjusted 예측선은 높은 오후 plateau를 계속 유지했습니다.

이 문제는 저녁 하락 국면도 아닙니다. 실측이 강하게 하락하는 상황이라기보다, 당일 실측이 이미 부정한 높은 낮 시간대 레벨을 모델이 계속 유지한 케이스입니다.

## 변경

`intraday_correction.afternoon_observed_anchor_cap`을 추가했습니다.

이 가드는 영업일 오후의 가까운 미래 시간대에만 동작하며, 최근 실측 residual이 지속적인 과대예측을 보여줄 때만 켜집니다. TEPCO 예측값은 사용하지 않고, 이미 실측/고정된 시간대도 다시 쓰지 않습니다.

각 대상 미래 시간에 대해 다음 cap을 계산합니다.

```text
마지막 실측
+ lag/recent shape support의 일부
+ buffer
```

현재 예측선이 이 cap을 넘을 때만 초과분 일부를 줄이고, 최대 reduction으로 상한을 둡니다.

## 안전 조건

- 오후 구간의 당일 실측 근거가 필요합니다.
- 최신 overforecast와 최근 평균 overforecast가 모두 필요합니다.
- 설정된 가까운 미래 시간대만 대상으로 합니다.
- 이 실패 패턴은 lag/recent shape support를 모델이 과신한 경우이므로, positive support 전체가 아니라 일부만 cap 계산에 사용합니다.
- 점심 한 슬롯만 꺼진 경우에는 가드를 켜지 않고, 최근 residual 문맥이 지속적인 high bias를 확인할 때만 동작합니다.

## 설정

```yaml
intraday_correction:
  afternoon_observed_anchor_cap:
    enabled: true
    business_day_only: true
    target_hours: [14, 15, 16]
    min_reference_hour: 12
    max_reference_hour: 15
    max_lead_hours: 3
    lookback_observed_hours: 3
    min_latest_overforecast_mw: 500
    min_mean_overforecast_mw: 500
    cap_buffer_mw: 350
    support_fraction: 0.6
    shrinkage: 0.75
    max_reduction_mw: 1200
    min_reduction_mw: 100
```

## 진단 필드

운영 보정 메타데이터에 다음 필드를 추가했습니다.

- `afternoonObservedAnchorCapApplied`
- `afternoonObservedAnchorCapMaxReductionMw`
- `afternoonObservedAnchorCapReductionMw`
- `afternoonObservedAnchorCapMw`
- `afternoonObservedAnchorCapCumulativeSupportMw`
- `afternoonObservedAnchorCapLatestResidualMw`
- `afternoonObservedAnchorCapMeanResidualMw`

AI 일일 리포트의 feature catalog에도 `intraday_correction.afternoon_observed_anchor_cap`을 추가했습니다.

## 검증

- 2026-06-09와 유사한 오후 plateau 과대예측 regression test를 추가했습니다.
- 점심 한 슬롯 하락만으로는 가드가 켜지지 않는 counter-test를 추가했습니다.
- 대상 테스트: `tests/test_intraday_correction.py` 통과.
