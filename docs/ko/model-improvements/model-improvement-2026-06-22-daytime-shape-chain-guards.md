# 2026-06-22 낮 시간 shape 연쇄 가드

언어: [English](../../en/model-improvements/model-improvement-2026-06-22-daytime-shape-chain-guards.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-22-daytime-shape-chain-guards.md)

## 배경

2026-06-22 라이브 예측 실패는 한 시간대의 단일 문제가 아니라 연쇄 문제였습니다.

- 09:00-11:00 JST는 과소예측이 발생했습니다. 최근 같은 영업일 shape는 강한 월요일 오전 램프를 지지했지만, business-return excess cap이 analogous-day 선을 약 700-900MW 깎았습니다.
- 12:00 JST는 점심 가드로 내려갔지만, 오전 과소예측 때문에 만들어진 양수 intraday residual이 13:00-14:00까지 이어졌습니다.
- 13:00-15:00은 과대예측으로 반전됐습니다. 오후 shape 지지가 약하거나 이미 둔화 중인데도 analogous-day 보정이 raw LightGBM 선을 700-1,100MW 정도 들어 올렸습니다.

TEPCO 값은 실패 원인을 비교하는 외부 기준으로만 확인했습니다. 모델 입력이나 보정값에는 섞지 않았습니다.

## 변경 내용

### Business-return excess cap 완화

`PostHolidayTimeBandGuard.business_return_anchor_excess_cap`이 이제 target hour의 램프 지지를 확인합니다.

- `lag_24h_hourly_delta`
- `recent_same_business_type_delta_mean`

영업일 복귀 09:00-11:00 구간에서 shape 지지가 강하면 제한된 추가 allowance를 주고 cap shrinkage를 낮춥니다. 정상적인 월요일 오전 램프를 guard가 지워버리지 않게 하기 위한 조정입니다.

### Business afternoon analog excess cap

`PostHolidayTimeBandGuard`에 `business_afternoon_analog_excess_cap`을 추가했습니다.

다음 조건이 모두 맞을 때만 positive analogous-day uplift를 제한합니다.

- 영업일 오후 시간대
- analogous-day shift가 의미 있게 양수
- lag/recent same-business delta가 상승을 강하게 지지하지 않음
- 날씨/냉방 변화 맥락이 존재함

일반적인 benign analog 상승은 건드리지 않고, 근거가 약한 오후 plateau만 줄이는 목적입니다.

### Post-lunch decline continuity guard

`IntradayResidualCorrector`에 `post_lunch_decline_continuity_guard`를 추가했습니다.

영업일 11:00 -> 12:00 실측 하락이 이미 확인됐을 때, 13:00-14:00 근거리 미래 선이 실측 기준선 위로 과하게 튀면 제한합니다. 오전 양수 residual이 점심 dip을 덮고 오후 초반을 끌어올리는 문제를 줄입니다.

### Daytime sustained under-forecast lift shape gate

`daytime_sustained_underforecast_lift`에 `post_midday_shape_gate`를 추가했습니다.

영업일 12:00-14:00 구간에서는 lag와 최근 같은 영업일 delta가 둘 다 회복을 지지할 때만 lift가 켜집니다. 오전 과소예측 residual이 점심 이후 구간을 무리하게 들어 올리는 것을 막습니다.

## 검증

다음 회귀 테스트를 추가했습니다.

- shape가 지지하는 월요일 오전 램프에서는 cap을 완화
- 지지가 약한 오후 analogous-day uplift는 제한
- post-midday shape gate가 `daytime_sustained_underforecast_lift`를 차단
- 13:00-14:00 post-lunch decline continuity cap 검증

전체 로컬 테스트:

```text
413 passed
```

## 운영 메모

이번 변경은 보수적으로 설계했습니다. TEPCO 추종은 하지 않고, 이미 게시된 과거 예측 슬롯도 되돌리지 않습니다. 대신 다음 실행의 pre-calibration과 근거리 residual 처리를 개선하여, 오전 과소예측이 오후 과대예측으로 번지는 연쇄를 줄입니다.
