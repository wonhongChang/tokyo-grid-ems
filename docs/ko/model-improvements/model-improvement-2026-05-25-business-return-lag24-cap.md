# 2026-05-25 영업일 복귀 lag24 cap 수정
> 따뜻한 월요일 예측을 일요일의 낮은 `lag_24h` 기준으로 눌러버리는 후처리 cap을 방지합니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-25-business-return-lag24-cap.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-25-business-return-lag24-cap.md)

---

## 왜 필요했나

2026-05-25 월요일 예측에서 후처리 단계의 실패 패턴이 드러났습니다. raw LightGBM은 여전히 영업일 낮 피크를 보고 있었지만, `post_holiday_timeband_guard` 단계에서 warm-day cap이 작동하면서 공개 예측선이 과도하게 낮아졌습니다.

문제는 cap 기준이었습니다. `lag24_warm_day_cap`은 따뜻한 날 예측이 `lag_24h + 설정 허용폭`을 지나치게 넘지 못하게 제한합니다. 전날이 같은 영업 타입이면 합리적이지만, 월요일의 `lag_24h`는 일요일 수요입니다. 일요일 수요를 월요일 영업일 회복 곡선의 상한 기준으로 쓰면서 낮 시간대 예측이 잘못 눌렸습니다.

## 변경 내용

`PostHolidayTimeBandGuard`에서 `lag_24h_business_type_mismatch > 0`인 경우 `lag24_warm_day_cap`을 건너뛰도록 수정했습니다.

평일→평일처럼 비교 가능한 날에는 기존 cap이 그대로 유지됩니다. 반대로 일요일→월요일, 휴일→영업일처럼 24시간 lag가 다른 운영 체계에서 온 경우에는 그 lag를 상한 기준으로 쓰지 않습니다.

## 운영 관점

이 수정은 월요일 수요를 강제로 올리는 로직이 아니고, TEPCO 예측을 추종하지도 않습니다. 잘못된 기준의 cap 하나를 제거하는 방식입니다. 실제 예측 수준은 여전히 모델, analogous-day 조정, 기상 피처, intraday residual 보정이 결정합니다.

## 테스트

비영업일 다음 따뜻한 월요일 케이스를 단위 테스트로 추가했습니다. 비교 가능한 날에는 warm-day lag24 cap이 유지되고, 영업일 복귀일에는 일요일의 낮은 `lag_24h`로 예측선을 누르지 않는지 검증합니다.
