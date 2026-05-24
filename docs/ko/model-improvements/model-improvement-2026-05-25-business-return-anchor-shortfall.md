# 2026-05-25 영업일 복귀 anchor 부족분 가드
> 비영업일 전날 lag가 영업일 아침 복귀 수요를 과도하게 낮출 때만 보수적으로 보완합니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-25-business-return-anchor-shortfall.md)

---

## 왜 필요했나

2026-05-25 월요일 오전 09시 예측에서 구조적인 과소예측이 보였습니다. 모델에는 영업일 전환 피처가 들어가 있었지만, 24시간 lag가 일요일에서 왔고 같은 시간대 최근 영업일 anchor보다 크게 낮았습니다.

09시 진단 값은 다음과 같았습니다.

- `lag_24h`: 22,830 MW
- `recent_same_business_type_mean`: 31,795 MW
- 모델 예측: 29,570 MW

모델이 일요일 lag 관성을 일부 극복하긴 했지만, 따뜻한 영업일 복귀 아침을 충분히 살리지는 못했습니다.

## 변경 내용

`PostHolidayTimeBandGuard` 내부에 `business_return_anchor_shortfall` 가드를 추가했습니다.

이 가드는 다음 조건에서만 작동합니다.

- 대상일이 영업일입니다.
- `lag_24h_business_type_mismatch > 0`입니다.
- `recent_same_business_type_mean - lag_24h`가 설정 임계치보다 큽니다.
- 현재 보정 후 예측값이 `recent_same_business_type_mean - allowance_mw`보다 낮습니다.

조건을 만족하면 부족분 일부만 올립니다.

```text
shortfall = recent_same_business_type_mean - allowance_mw - forecast
adjustment = min(shortfall * shrinkage_by_hour, max_clipping_mw)
```

예측선을 anchor까지 강제로 끌어올리지 않습니다. 비영업일 lag가 영업일 복귀 곡선을 과도하게 누를 때만 제한된 범위에서 보완합니다.

## 기본값

- `target_hours`: 06:00-11:00
- `gap_threshold_mw`: 6,000
- `allowance_mw`: 1,000
- `max_clipping_mw`: 1,000
- `shrinkage_map`: 06시 0.25, 07시 0.35, 08시 0.45, 09시 0.50, 10시 0.30, 11시 0.20

## 테스트

다음 단위 테스트를 추가했습니다.

- 2026-05-25 09시 산술 케이스: 1,225 MW 부족분에 612.5 MW 보정이 적용됩니다.
- `lag_24h_business_type_mismatch == 0`인 일반 영업일 연속 구간에서는 개입하지 않습니다.
- `enabled: false`일 때 이 가드만 꺼지고 기존 warm-day 가드는 독립적으로 계속 작동합니다.
