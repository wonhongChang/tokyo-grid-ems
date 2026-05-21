# 이상탐지 기준

언어: [English](../en/anomaly-criteria.md) / [日本語](../ja/anomaly-criteria.md)

Tokyo Grid EMS는 대시보드에서 왜 알림이 발생했는지 설명할 수 있도록 이상탐지를 세 가지 이벤트로 나눕니다.

| 이벤트 | 목적 | 입력 |
|---|---|---|
| Reserve Risk | 공급 여유가 줄어드는 구간 감지 | 사용률, 공급력 |
| Spike / Drop | 예측 외곽 구간을 벗어난 수요 감지 | 실측 수요, 예측 구간 |
| Drift | 여러 시간 동안 지속되는 모델 편향 감지 | 실측-예측 잔차 |

기준값은 `config.yaml`의 `anomaly` 블록에서 관리합니다.

---

## 1. Reserve Risk

TEPCO 사용률이 기준치에 도달하면 이벤트를 생성합니다.

| Severity | 조건 |
|---|---|
| 안정 | `usage_pct < 92.0` |
| warning | `92.0 <= usage_pct < 97.0` |
| 위험 (`critical`) | `usage_pct >= 97.0` |

이 이벤트는 예측 모델의 정확도와 별개로 전력 수급 KPI 자체가 위험 구간에 들어왔는지 보여줍니다.

---

## 2. Spike / Drop

실측 수요가 예측 구간의 바깥쪽, 즉 p99 범위를 벗어났는지 확인합니다.

| 이벤트 | warning | critical |
|---|---|---|
| Spike | 실측이 `p99Upper`를 넘고, 초과 폭이 warning MW 또는 % 기준 이상 | 실측이 `p99Upper`를 넘고, 초과 폭이 critical MW 또는 % 기준 이상 |
| Drop | 실측이 `p99Lower`를 밑돌고, 초과 폭이 warning MW 또는 % 기준 이상 | 실측이 `p99Lower`를 밑돌고, 초과 폭이 critical MW 또는 % 기준 이상 |

p95만 살짝 벗어난 경우는 spike/drop 이벤트로 만들지 않습니다. p99를 아주 조금 벗어난 경우도 운영상 의미 있는 초과 폭이 아니면 제외합니다. 이런 경우는 운영상 급등/급락이라기보다 일반적인 모델 밴드 오차에 가깝고, 여러 시간 동안 같은 방향으로 지속되면 drift 탐지가 별도로 잡습니다.

기본 기준:

```yaml
spike_drop:
  warning_breach_mw: 300
  warning_breach_pct: 1.0
  critical_breach_mw: 500
  critical_breach_pct: 2.0
```

대시보드 표현:

- Spike: `실측 수요가 예측 범위 상단을 크게 벗어났습니다.`
- Drop: `실측 수요가 예측 범위 하단을 크게 벗어났습니다.`
- 지표 칩: 실측, 모델 예측, 예측 상한/하한

---

## 3. Drift

한 시간의 급격한 오차보다, 여러 시간 동안 같은 방향으로 누적되는 편향을 감지합니다.

계산 방식:

1. 시간별 잔차를 계산합니다.
   - `residual = actual_mw - forecast_mw`
2. 잔차에 EWMA를 적용합니다.
   - 기본 `ewma_alpha = 0.3`
3. EWMA가 기준값을 연속 시간 이상 넘으면 drift 이벤트를 생성합니다.
   - 기본 `threshold_mw = 800`
   - 기본 `sustained_hours = 3`

| 방향 | 의미 |
|---|---|
| positive drift | 실측 수요가 모델 예측보다 지속적으로 높음 |
| negative drift | 실측 수요가 모델 예측보다 지속적으로 낮음 |

Drift는 모델의 장기 보정 필요성을 알려주는 신호이며, intraday residual correction과도 연결됩니다.

---

## 설계 원칙

- 경고 문장은 짧게 유지합니다.
- 숫자는 지표 칩으로 분리합니다.
- 모델 오차와 수급 위험은 별도 이벤트로 구분합니다.
- `tepco_forecast_fallback` 행은 실측 기반 이상탐지에서 제외합니다.
- 운영 기준은 코드가 아니라 config와 문서에서 추적합니다.
