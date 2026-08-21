# 2026-08-21 v14-r2 출처 강건형 다음날 예측 Champion

언어: [English](../../en/model-improvements/model-improvement-2026-08-21-v14-r2-source-robust-day-ahead.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-21-v14-r2-source-robust-day-ahead.md)

## 결정

`v14-r2-source-robust-day-ahead`가 성능이 저하된 v11 Champion을 교체했다. 앞선 v14-r1 staging 후보는 배포하지 않았다. 예측 대상일의 수요 lag가 대부분 아직 존재하지 않을 때 v11의 결측 분기를 그대로 사용하거나, 안전하지 않은 하루 공통 이동을 적용하는 구조였기 때문이다. v14-r2는 D-1 예측 시점에 실제로 존재하는 정보만 사용하는 전용 q50 경로를 학습한다.

승격 artifact는 TEPCO 예측과 독립적이다. TEPCO 값은 외부 비교 기준과 23시 임시 lag 연속성 fallback으로만 사용하며, 학습 target이나 보정 anchor로 사용하지 않는다.

## 모델 계약

- 일반 D0 경로는 절대수요, lag-24 잔차, 비영업일 q50 구조를 유지한다.
- 과거 습도 결측과 단기 기상 필드에 대한 민감도를 줄이는 두 개의 source view를 사용한다. 이들의 출력은 기존 q50에서 최대 500MW까지만 이동할 수 있다.
- 예측 시점에 `lag_24h`, 최근 영업일 수요 또는 최근 비영업일 수요가 없으면 전용 source-robust q50 모델이 작동한다. 이 모델은 아직 확정되지 않은 수요 lag 피처 6개와 D-1에서 일관되게 재현할 수 없는 기상 피처를 제외한다.
- D-1 비영업일 전용 모델은 7월 개발 구간에서 먼저 선택했으며 가중치 1.0을 사용한다. 8월 holdout을 보고 선택하지 않았다.
- same-regime 일간 잔차 보정은 최근 확정 3일, shrinkage 0.25, 절대 상한 1,000MW를 사용한다. artifact에 귀속되며 대상일을 학습하지 않는다.
- interval sanity 보정 후 p95 half-width에 1.25를 곱한다. 보정 전 상한은 3,000MW, 최종 상한은 3,750MW이며 q50은 바꾸지 않는다.

## 고정 시점 검증

모든 replay는 모의 게시 시점에 알 수 없던 관측치를 제거한다. 대상일 actual을 비우고, 모의 시각보다 늦게 캡처된 source commit의 미래 actual도 차단한다. holdout은 현재 코드로 재학습한 유사 모델이 아니라 실제 배포 v11 artifact SHA를 기준으로 비교한다.

| 평가 | 기간 | v14-r2 MAE 개선 | RMSE 개선 | 최대오차 개선 | Shape 개선 | 우세 일수 |
|---|---|---:|---:|---:|---:|---:|
| D0 개발 | 2026-07-01~2026-07-31 | 5.13% | 4.63% | 2.03% | 10.16% | 24 / 31 |
| D0 실제 Champion holdout | 2026-08-01~2026-08-20 | 18.76% | 16.54% | 15.51% | 16.01% | 16 / 20 |
| D-1 개발 | 2026-07-01~2026-07-31 | 68.87% | 64.32% | 55.87% | 44.84% | 31 / 31 |
| D-1 실제 Champion holdout | 2026-08-01~2026-08-20 | 39.82% | 46.96% | 44.39% | 30.22% | 13 / 20 |

D0 holdout MAE는 1,725.4MW에서 1,401.8MW로 줄었다. D-1 holdout은 5,018.9MW에서 3,020.3MW로 줄었다. 운영 구간 중 비퇴행 상한을 넘은 곳은 없었다. 날짜 단위 paired bootstrap의 MAE 비율 95% 상한은 각각 0.9095와 0.8383이었다.

별도 84일 확정 기상 보조 replay에서는 중심선 MAE가 902.3MW에서 883.9MW로, shape 오차가 534.7MW에서 512.6MW로 줄었고 모든 시간대가 개선됐다. 단일 시간 최대오차는 437.1MW 늘었지만 500MW source-view trust region 안이며, D0와 D-1 고정 시점 holdout의 최대오차는 모두 감소했다.

## 승격과 감시

오늘·내일 drift가 큰 이유는 v11 다음날 곡선이 구조적으로 잘못된 결측 lag 분기를 사용했기 때문이다. 최대 교정량은 +9,654.8MW였다. 따라서 대규모 drift 승인은 D0와 D-1 실제 Champion holdout이 모두 strict recovery gate를 통과하고, 별도 기준인 D0 8%와 D-1 20% MAE 개선을 넘은 경우에만 허용했다.

| 항목 | 값 |
|---|---|
| 계약 | `v14-r2-source-robust-day-ahead` |
| 구간 계약 | `q025_q50_q975_p95_v14_source_robust_day_ahead` |
| 학습 cutoff | `2026-08-01` |
| Champion SHA-256 | `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3` |
| Rollback v11 SHA-256 | `28b75352b8b13713aba04880111dd11b3450864a3580f355081072af4266a640` |
| 승격 상태 | `recovery_promoted` |
| 안정화 검토 | 확정 운영 3일 후 |

D-1 holdout WAPE는 아직 약 9.15%다. 따라서 이번 승격은 TEPCO 동등성 달성이 아니라 v11의 구조적 결함에서 벗어난 복구 승격이다. 안정화 기간에는 이전 artifact를 보존한다. 데이터 출처 무결성 실패, 비정상·불완전 예측, 또는 확정 근거에서 v11 shadow 대비 유의한 퇴행이 확인되면 즉시 rollback을 검토한다.
