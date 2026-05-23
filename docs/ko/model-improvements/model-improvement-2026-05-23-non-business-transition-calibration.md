# 2026-05-23 비영업일 전환 보정
> 전날 평일 lag가 토요일/휴일 예측선을 과도하게 끌어올리는 경우를 위한 운영 보정입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md)

---

## 왜 필요했나

2026-05-23 토요일 예측은 주말 플래그가 빠진 상태가 아니었습니다. `is_weekend=1`, `is_non_business_day=1`은 정상으로 들어갔지만, raw LightGBM 예측선은 평일형 곡선에 가깝게 보였습니다.

원인은 `lag_24h`였습니다. 토요일의 24시간 전 lag는 금요일 실측이고, 이 값이 최근 같은 시간대 비영업일 평균보다 수천 MW 높았습니다. 이 구간에서는 주말 플래그가 있어도 Friday lag 관성이 모델을 강하게 끌어올릴 수 있습니다.

기존 intraday residual 보정은 오늘 실측 오차를 보고 예측선을 낮추고 있었지만, 금요일 lag 관성을 충분히 제거하기에는 약했습니다.

## 변경 내용

intraday 보정 레이어에 `business_type_transition` 보정을 추가했습니다.

다음 조건을 모두 만족할 때만 작동합니다.

- 대상일이 비영업일입니다.
- 전날 lag와 대상일의 영업/비영업 타입이 다릅니다.
- 당일 실측 residual이 이미 모델 과대예측을 보여줍니다.
- `lag_24h`가 최근 같은 비영업일 평균보다 충분히 높습니다.
- 현재 예측이 비영업일 anchor보다 설정된 허용 폭 이상 높습니다.

보정은 미래 시간에만 적용됩니다. 이미 실측이 들어온 시간이나 공개된 과거 예측선은 건드리지 않습니다.

## 운영 관점

이 보정은 고정된 토요일 곡선을 만드는 로직이 아닙니다. TEPCO 예측을 목표값으로 쓰지도 않습니다. 프로젝트 내부의 최근 같은 비영업일 anchor와 당일 실측 residual만 이용합니다.

따뜻한 주말에는 기온 anomaly와 cooling degree에 따라 허용 폭을 더 주기 때문에, 실제로 더운 주말 수요를 무리하게 누르지 않도록 했습니다.

## 진단 메타데이터

운영 보정 JSON에는 다음 값이 추가됩니다.

- `businessTypeTransitionApplied`
- `businessTypeTransitionBiasMw`
- `business_type_transition_lag_overheat` (`appliedRegimeReason`)

이를 통해 주말/휴일 예측선이 일반 residual 보정으로 내려간 것인지, 영업일→비영업일 전환 보정으로 내려간 것인지 추적할 수 있습니다.

## 테스트

전날 평일 lag가 비영업일 anchor보다 과도하게 높고, 당일 오전 실측이 모델 과대예측을 보여주는 토요일 케이스를 단위 테스트로 추가했습니다.
