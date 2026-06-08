# 2026-06-08 영업일 복귀 shape veto

언어: [English](../../en/model-improvements/model-improvement-2026-06-08-business-return-shape-veto.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-08-business-return-shape-veto.md)

---

## 문제

2026-06-08 라이브 예측에서는 raw LightGBM 선이 이미 월요일 영업일 복귀 램프를 어느 정도 잘 살리고 있었습니다. 그런데 후처리 레이어의 `business_return_anchor_shortfall`이 최근 평일 anchor 레벨과 전날 주말 `lag_24h` 레벨 차이만 보고 추가 상방 보정을 적용했습니다.

그 결과 08:00-11:00 구간의 served 예측선이 raw보다 더 높아져 오차가 커졌습니다. 이날의 핵심 문제는 원천 모델이 약해서가 아니라, 레벨 anchor 가드가 이미 충분한 shape를 가진 예측선에도 개입한 것입니다.

## 변경

`business_return_anchor_shortfall`에 shape 기반 veto 조건을 추가했습니다.

이제 가드는 현재 예측선의 시간별 램프를 `recent_same_business_type_delta_mean`과 비교합니다. 최근 같은 영업 타입의 램프보다 예측 램프가 의미 있게 부족할 때만 레벨 anchor 리프트를 적용합니다.

새 설정:

```yaml
business_return_anchor_shortfall:
  min_shape_shortfall_mw: 800
```

또한 11:00 전환 구간의 과열을 방어하기 위해 late-morning excess cap 범위를 11:00까지 확장했습니다.

```yaml
business_return_anchor_excess_cap:
  target_hours: [8, 9, 10, 11]
```

## 운영 효과

진짜 월요일/휴일 이후 복귀 under-ramp에는 기존처럼 보수적으로 상방 보정을 허용합니다. 반대로 raw 또는 유사일 보정선이 이미 충분한 램프 shape를 갖고 있으면 불필요한 추가 리프트를 막습니다.

이 변경은 TEPCO 예측을 보정 입력으로 사용하지 않습니다. TEPCO는 성능 비교 기준으로만 둡니다.

## 검증

- 실제 09:00 영업일 복귀 부족분은 여전히 리프트되는 회귀 테스트를 추가했습니다.
- 오전 램프 shape가 이미 충분하면 리프트를 건너뛰는 회귀 테스트를 추가했습니다.
- 11:00에도 business-return excess cap이 적용되는 회귀 테스트를 추가했습니다.
- 전체 테스트: `383 passed`.
