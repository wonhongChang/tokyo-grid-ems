# 2026-08-18 동일 시점 TEPCO 평가와 모델 승격 거버넌스

언어: [English](../../en/model-improvements/model-improvement-2026-08-18-matched-vintage-promotion-governance.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-18-matched-vintage-promotion-governance.md)

## 문제

TEPCO는 당일 예측을 계속 갱신하고 과거 시간의 값도 바꿀 수 있다. 기존 `forecast_accuracy.json`은 확정 실측과 파일에 마지막으로 남은 TEPCO 예측을 비교하므로, 자체 모델의 당시 게시값과 TEPCO의 사후 수정값이 섞일 수 있었다. 또한 기존 승격 게이트는 Challenger를 seasonal baseline과 절대 상한에 주로 비교하여, 성능이 저하된 Champion을 교체하는 절차가 불명확했다.

## 변경

- ETL/Intraday 실행마다 아직 지나지 않은 시간의 자체 모델과 TEPCO 예측을 같은 실행에서 함께 캡처한다.
- 장부는 `reports/internal/forecast-vintages/YYYY-MM-DD.json`에 append-only로 저장하고 이후 TEPCO 수정값으로 과거 캡처를 덮어쓰지 않는다.
- TEPCO가 별도 `issuedAt`을 제공하지 않으므로 프로젝트의 `capturedAt`을 관측 vintage로 사용한다.
- 평가는 `0~2h`, `2~4h`, `4~8h`, `8~24h` lead bucket과 시간대로 분리한다.
- `metrics/forecast_vintage_accuracy.json`에 MAE, WAPE, RMSE, 최대 오차, 모델/TEPCO 비율 및 날짜 block bootstrap 신뢰구간을 기록한다.
- 공식 자격 판정은 모든 lead bucket과 시간대에서 paired-hour coverage 80% 이상을 요구한다. RMSE 비율, 최대 오차 비율, paired bootstrap MAE 비율 신뢰구간 상한도 gate에 포함해 유리한 점추정치 하나만으로 통과하지 못하게 한다.
- 기존 forecast/calibration 스냅샷은 대상 날짜가 같고 생성 시각 차이가 120초 이내인 경우에만 초기 장부로 가져온다.
- Champion과 Challenger를 같은 학습 cutoff와 holdout에서 재현하고, 정상 승격과 성능 저하 Champion의 복구 승격을 분리한다.
- 복구 후보는 28일에서 MAE/WAPE 10% 이상 개선하고, 위험 및 주요 구간 퇴행이 5% 이내이며, 56/84일 방향도 일치해야 한다.
- 큰 prediction drift나 명시적 승인 전 후보는 shadow artifact로 보존한다. 승격 시 이전 Champion은 rollback artifact로 남긴다.
- 복구 승격은 `metrics/model_shadow_evaluation.json`이 최소 72개 shadow forecast-hour와 2개 확정일을 확인하기 전까지 fail-closed로 멈춘다. 그 뒤에도 명시적 승인 flag가 필요하다.
- 비평가일 ETL이 마지막 상세 승격 결과를 지우지 않도록 `lastEvaluation`을 유지한다.

## 실제 검증 결과

동일 학습 cutoff에서 v13 계약과 v11 계약을 비교했다.

| 기간 | v13 MAE | v11 계약 MAE | v13 개선 | 판단 |
|---|---:|---:|---:|---|
| 28일 | 1,275.8MW | 1,351.7MW | 5.62% | 복구 기준 10% 미달 |
| 56일 | 983.8MW | 1,016.0MW | 3.17% | 장기 방향은 개선 |
| 84일 | 891.6MW | 916.8MW | 2.75% | 장기 방향은 개선 |

최근 365일 학습과 보수적인 LightGBM 복잡도 조합도 별도로 시험했다. 가장 나은 28일 후보는 MAE 1,207.9MW였지만 동일 학습 데이터의 v11 계약 대비 개선은 3.58%였고 WAPE 3.456%로 승격 기준을 통과하지 못했다. 따라서 v13 또는 실험 후보를 강제 승격하지 않고 v11을 임시 유지한다.

## 초기 matched-vintage 상태

과거 동일 실행 스냅샷 204개를 엄격하게 매칭해 14일, 911개 비교 행을 복원했다. 초기 lead bucket별 모델/TEPCO MAE 비율은 약 1.84~2.20이었다. 아직 28일과 84일 표본이 차지 않았으므로 상태는 `collecting`이며 공식 parity 판정에는 사용하지 않는다.

## 영향

이번 변경은 현재 서빙 q50이나 예측 밴드를 바꾸지 않는다. 핵심 효과는 잘못된 비교 시점과 무리한 승격을 차단하고, 이후 모델이 TEPCO 동급인지 재현 가능한 기준으로 판단할 수 있게 한 것이다.
