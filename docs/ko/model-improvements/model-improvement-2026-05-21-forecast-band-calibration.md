# 2026-05-21 예측 밴드 보정

> 한쪽 quantile 불확실성이 반대쪽 예측 밴드까지 그대로 복사되는 문제를 막은 개선 기록.

언어: [English](../../en/model-improvements/model-improvement-2026-05-21-forecast-band-calibration.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-21-forecast-band-calibration.md)

---

## 왜 필요했나

2026-05-21 intraday 예측에서 14:00 예측 밴드가 시각적으로 비정상적으로 커졌다. 중심 예측선 자체가 핵심 문제는 아니었다. LightGBM quantile이 아래처럼 강하게 비대칭이었다.

- q50은 예상 수요선 근처에 있었다.
- q025는 q50에 매우 가깝게 붙었다.
- q975는 훨씬 높은 쪽에 있었다.

기존 interval calibration은 아래쪽이 q50에 붙은 것을 이상하게 보고, 위쪽의 큰 half-width를 아래쪽에도 그대로 복사했다. 그 결과 표시되는 하단 밴드가 모델의 실제 하단 quantile보다 훨씬 아래로 떨어졌다.

---

## 변경 내용

운영 config에서 `interval_calibration.mirror_collapsed_side`를 비활성화했다.

밴드가 선처럼 붙지 않도록 p95 half-width 최소값은 계속 유지한다. 다만 큰 상방 불확실성을 하방으로 복사하거나, 반대로 큰 하방 불확실성을 상방으로 복사하지 않는다.

```yaml
interval_calibration:
  min_p95_half_width_mw: 500
  mirror_collapsed_side: false
```

---

## 기대 효과

quantile 모델이 한쪽 방향의 불확실성만 크게 표현해도 예측 밴드가 읽기 쉬운 형태로 유지된다.

재현한 2026-05-21 14:00 케이스에서는 p95 폭이 약 `9,260 MW`에서 약 `5,130 MW`로 줄었다. 상방 불확실성은 남기지만, 근거 없는 하방 범위를 표시하지 않게 된다.

---

## 테스트

추가/수정한 테스트는 아래를 확인한다.

- 기본 calibration은 collapse된 방향에 최소 폭만 유지한다.
- 기존 mirroring 동작은 명시적으로 설정한 경우에만 사용할 수 있다.
