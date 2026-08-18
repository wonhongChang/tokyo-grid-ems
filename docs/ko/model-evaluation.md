# 모델 평가 리포트

언어: [English](../en/model-evaluation.md) · [日本語](../ja/model-evaluation.md)

Tokyo Grid EMS는 예측 성능을 세 관점으로 분리해서 평가합니다.

1. **오프라인 백테스트**: 모델 자체가 과거 데이터에서 안정적으로 예측하는지 확인합니다.
2. **운영 비교**: 실제 대시보드 운영 상황에서 TEPCO 예측과 자체 모델 중 어느 쪽이 실적에 더 가까웠는지 확인합니다.
3. **동일 vintage 비교**: 같은 실행, 같은 lead-time에 관측한 자체 모델과 TEPCO 예측을 공정하게 비교합니다.

세 결과는 `web/public/metrics/` 아래 JSON으로 생성됩니다. 현재 **검증** 탭은 오프라인 백테스트와 최신 게시값 운영 비교를 표시하고, 동일 vintage 비교는 이력이 충분해질 때까지 내부 승격·자격 판정 자료로만 유지합니다.

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
- `actualSource`가 `tepco_forecast_fallback`인 행은 제외합니다.
- 전체 요약(`summary`)은 최신 운영 모델 계열만 포함합니다.
  - 예: 현재 운영 모델이 LightGBM이면 과거 baseline 산출일은 전체 승률에서 제외합니다.

주요 지표:

| 지표 | 의미 |
|---|---|
| `modelMaeMw`, `tepcoMaeMw` | 평균 절대 오차(MW). 운영자가 체감하기 쉬운 대표 지표입니다. |
| `modelWapePct`, `tepcoWapePct` | 총 실적 수요 대비 절대 오차율. 하루 전체 수요 규모 대비 어느 쪽이 더 안정적인지 봅니다. |
| `modelRmseMw`, `tepcoRmseMw` | 큰 오차를 더 강하게 반영하는 리스크 지표입니다. |
| `modelMaxErrorMw`, `tepcoMaxErrorMw` | 단일 시간대에서 발생한 최대 오차입니다. |
| `modelAdvantageHours`, `tepcoAdvantageHours` | 시간별 절대 오차가 상대보다 작았던 시간 수입니다. 기존 `modelWins`, `tepcoWins`와 같은 값이지만 UI에서는 운영 용어인 “우위 시간”으로 표시합니다. |
| `verdict` | `MAE`, `WAPE`, `RMSE`를 함께 본 운영 판단입니다. `model_better`, `tepco_better`, `close`, `mixed`, `insufficient` 중 하나입니다. |

해석 시 주의점:

- TEPCO 예측은 공식 운영 예측이며, 당일 갱신 시점에 따라 매우 강한 기준선이 됩니다.
- TEPCO는 지나간 시간의 예측값도 수정할 수 있으므로 `forecast_accuracy.json`은 `latest_published_value_reference` 운영 참고치이며 공식 parity 판정에는 사용하지 않습니다.
- 자체 모델은 GitHub Actions 기반 정적 대시보드 운영을 목표로 하며, 최근 실적이 들어온 경우 intraday residual correction을 적용합니다.
- 따라서 이 비교는 논문식 순수 모델 비교라기보다, 사용자가 실제 화면에서 보게 되는 운영 성능 비교입니다.
- 엄격한 학습/평가 분리 기준의 모델 성능은 `model_backtest.json`를 기준으로 봅니다.
- 시간별 “우위 시간”은 보조 정보입니다. 전체 판단은 단순 승률보다 `WAPE`와 대형 오차 리스크를 우선합니다.

---

## 대시보드 표시 기준

검증 탭은 다음 순서로 읽으면 됩니다.

1. **TEPCO 예측 대비 운영 비교**: 최근 운영 구간에서 어떤 예측이 더 실제 수요에 가까웠는지 봅니다.
2. **최근 일별 MAE/WAPE/RMSE**: 특정 날짜에 평균 오차, 전체 오차율, 큰 오차 리스크가 어떻게 달랐는지 확인합니다.
3. **모델 백테스트**: LightGBM이 기존 베이스라인 대비 실제로 개선되는지 확인합니다.

이 구조는 “모델이 좋아 보인다”가 아니라, **운영 중인 예측 시스템을 어떻게 검증하고 설명하는지**를 보여주기 위한 것입니다.

---

## 3. 동일 vintage TEPCO 벤치마크

출력 파일:

```text
web/public/metrics/forecast_vintage_accuracy.json
```

- 각 ETL/Intraday 실행에서 아직 지나지 않은 시간의 모델/TEPCO 값을 함께 `reports/internal/forecast-vintages/`에 저장합니다.
- 이후 TEPCO 수정값은 앞선 캡처를 덮어쓸 수 없습니다.
- TEPCO가 불변 발행 시각을 제공하지 않으므로 프로젝트의 `capturedAt`을 관측 가능한 vintage로 사용합니다.
- `0~2h`, `2~4h`, `4~8h`, `8~24h` lead bucket과 운영 시간대로 나눠 계산합니다.
- 공식 자격 판정은 28일과 84일 창이 모두 차고, 전체 MAE/WAPE 비율이 1.10 이하이며, 표본이 충분한 각 시간대 MAE 비율이 1.25 이하일 때만 통과합니다.
- 날짜 단위 paired block bootstrap으로 모델과 TEPCO 절대 오차 차이의 불확실성도 표시합니다.

`collecting`은 기능은 정상이나 이력이 부족하다는 뜻이며 합격이나 실패로 해석하지 않습니다.
