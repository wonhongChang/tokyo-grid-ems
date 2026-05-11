# 모델 평가 리포트

Tokyo Grid EMS는 예측 성능을 두 관점으로 분리해서 평가합니다.

1. **오프라인 백테스트**: 모델 자체가 과거 데이터에서 안정적으로 예측하는지 확인합니다.
2. **운영 비교**: 실제 대시보드 운영 상황에서 TEPCO 예측과 자체 모델 중 어느 쪽이 실적에 더 가까웠는지 확인합니다.

두 결과는 `web/public/metrics/` 아래 JSON으로 생성되며, GitHub Pages 대시보드의 **검증** 탭에서 표시됩니다.

---

## 1. 오프라인 백테스트

출력 파일:

```text
web/public/metrics/model_backtest.json
```

평가 방식:

- 기준일(`testStart`, 기본 `2026-01-01`) 이전 데이터만 학습에 사용합니다.
- 테스트 기간의 각 날짜를 예측할 때는 해당 날짜 이전의 캐시만 사용합니다.
- 시간별 실적 전력(`actual_mw`)을 타깃으로 평가합니다.
- 비교 대상은 동일 요일/시간 베이스라인과 LightGBM 모델입니다.

주요 지표:

| 지표 | 의미 |
|---|---|
| `MAE` | 평균 절대 오차. 실무 대시보드에서 가장 직관적인 지표입니다. |
| `RMSE` | 큰 오차를 더 강하게 벌점 처리합니다. 피크 실패에 민감합니다. |
| `MAPE` | 실제값 대비 상대 오차입니다. |
| `improvementPct` | 베이스라인 대비 LightGBM 개선율입니다. 양수면 LightGBM이 더 좋습니다. |

재현 명령:

```bash
python python/eval/compare_models.py \
  --cache web/public/.hourly_cache.parquet \
  --out web/public/metrics/model_backtest.json \
  --test-start 2026-01-01
```

---

## 2. TEPCO 예측 대비 운영 비교

출력 파일:

```text
web/public/metrics/forecast_accuracy.json
```

평가 방식:

- 최근 `windowDays`일 중 아래 세 값이 모두 존재하는 시간만 비교합니다.
  - 실적 전력
  - 자체 모델 예측
  - TEPCO 제공 예측
- 각 시간별 절대 오차를 계산합니다.
- 일별/시간대별 MAE와 승패 카운트를 집계합니다.
- 전체 요약(`summary`)은 최신 운영 모델 계열만 포함합니다.
  - 예: 현재 운영 모델이 LightGBM이면 과거 baseline 산출일은 전체 승률에서 제외합니다.

주요 지표:

| 지표 | 의미 |
|---|---|
| `modelMaeMw` | 자체 모델의 평균 절대 오차(MW) |
| `tepcoMaeMw` | TEPCO 예측의 평균 절대 오차(MW) |
| `modelWins` | 자체 모델의 절대 오차가 TEPCO보다 작았던 시간 수 |
| `tepcoWins` | TEPCO 예측의 절대 오차가 자체 모델보다 작았던 시간 수 |
| `modelWinRate` | `modelWins / comparableHours` |

해석 시 주의점:

- TEPCO 예측은 공식 운영 예측이며, 당일 갱신 시점에 따라 매우 강한 기준선이 됩니다.
- 자체 모델은 GitHub Actions 기반 정적 대시보드 운영을 목표로 하며, 최근 실적이 들어온 경우 intraday residual correction을 적용합니다.
- 따라서 이 비교는 논문식 순수 모델 비교라기보다, 사용자가 실제 화면에서 보게 되는 운영 성능 비교입니다.
- 엄격한 학습/평가 분리 기준의 모델 성능은 `model_backtest.json`를 기준으로 봅니다.

---

## 대시보드 표시 기준

검증 탭은 다음 순서로 읽으면 됩니다.

1. **TEPCO 예측 대비 운영 비교**: 최근 운영 구간에서 어떤 예측이 더 실제 수요에 가까웠는지 봅니다.
2. **최근 일별 MAE**: 특정 날짜에 자체 모델이 강했는지, TEPCO가 강했는지 확인합니다.
3. **모델 백테스트**: LightGBM이 기존 베이스라인 대비 실제로 개선되는지 확인합니다.

이 구조는 “모델이 좋아 보인다”가 아니라, **운영 중인 예측 시스템을 어떻게 검증하고 설명하는지**를 보여주기 위한 것입니다.
