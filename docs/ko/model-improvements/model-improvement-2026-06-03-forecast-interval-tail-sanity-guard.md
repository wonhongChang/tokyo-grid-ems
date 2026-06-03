# 2026-06-03 예측 구간 상단 tail 안정화

> q50 수요 예측선은 유지하면서, p95 상단 밴드가 한쪽으로 과도하게 벌어지는 드문 케이스를 제한한 개선 기록입니다.

언어: [English](../../en/model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)

---

## 왜 필요했나

2026-06-03 intraday 예측에서 q50 예측선 자체는 대체로 정상 범위였지만, 대시보드의 예측 밴드가 시각적으로 비정상적으로 보였습니다.

문제는 p95 상단 쪽에 집중되었습니다.

- 12:00 상단 half-width: 약 `+4,831 MW`
- 13:00 상단 half-width: 약 `+5,939 MW`
- 14:00 상단 half-width: 약 `+6,108 MW`
- 15:00 상단 half-width: 약 `+6,187 MW`

하단 폭은 훨씬 좁게 유지되어, 화면상으로는 위쪽 risk cone만 과도하게 열린 형태가 되었습니다. 스냅샷을 비교하면 이 변화는 11:14 JST intraday 실행부터 시작되었습니다.

이전 스냅샷과 비정상 스냅샷 사이에 모델 파일은 바뀌지 않았습니다. 크게 바뀐 입력은 날씨였습니다. 12:00-14:00 미래 기온이 약 `21.0 C`에서 약 `18.0 C`로 바뀌었고, q50 모델은 작게 반응했지만 독립 q975 모델은 이 날씨 regime 변화를 큰 상단 tail risk로 해석했습니다.

---

## 원인

Tokyo Grid EMS는 q025, q50, q975를 서로 다른 LightGBM quantile regressor로 학습합니다. 각 quantile이 서로 다른 위험 형태를 학습할 수 있다는 장점이 있지만, 특정 입력 조합에서는 q975가 q50/q025 대비 과도하게 넓어질 수 있습니다.

기존 interval calibration은 밴드 붕괴를 막고, 한쪽 불확실성을 반대편으로 그대로 복사하지 않도록 만들었습니다. 하지만 날씨 regime 변화 후 상단 tail 자체가 드물게 폭주하는 경우를 제한하는 장치는 부족했습니다.

또 forecast freeze 정책 때문에 이 현상이 화면에 더 오래 남았습니다. 공정한 평가를 위해 관측 완료 시간대의 forecast를 보존하는데, 이때 비정상 밴드까지 함께 보존되었기 때문입니다.

---

## 변경 내용

공통 interval calibration helper를 추가했습니다.

```text
python/forecast/interval_calibration.py
```

이 helper는 다음을 보장합니다.

- p95 최소 half-width 유지
- p95 최대 half-width 제한
- 상단/하단 비대칭 비율 제한
- 보정된 p95 폭을 기준으로 p99 구간 재구성

동일한 보정을 두 곳에 적용했습니다.

- `LGBMForecaster.predict()`: 새 q025/q50/q975 출력 단계
- `build_forecast_json()`: forecast JSON 저장/스냅샷 직전 단계

운영 설정은 다음과 같습니다.

```yaml
interval_calibration:
  min_p95_half_width_mw: 500
  max_p95_half_width_mw: 4500
  max_p95_asymmetry_ratio: 4.0
  asymmetry_reference_half_width_mw: 1000
  mirror_collapsed_side: false
```

---

## 기대 효과

중심 예측값(q50)은 바꾸지 않습니다. 말이 안 되게 벌어지는 예측 구간 tail만 제한합니다.

2026-06-03 재현 케이스 기준 효과는 다음과 같습니다.

| 시간 | 적용 전 상단 half-width | 적용 후 상단 half-width |
|---|---:|---:|
| 12:00 | `+4,830.8 MW` | `+4,500.0 MW` |
| 13:00 | `+5,939.2 MW` | `+4,500.0 MW` |
| 14:00 | `+6,107.7 MW` | `+4,380.8 MW` |
| 15:00 | `+6,187.2 MW` | `+4,000.0 MW` |

불확실성 자체는 계속 표시하되, 대시보드가 한쪽으로 과장된 risk cone을 보여주는 상황을 막습니다.

---

## 테스트

다음 회귀 테스트를 추가했습니다.

- LGBM 원천 quantile 출력에서 상단 interval이 과도하게 벌어지는 케이스
- 이미 생성되었거나 freeze로 보존된 forecast point가 JSON 직전 단계에서 정규화되는 케이스

검증 결과:

```text
369 passed
```
