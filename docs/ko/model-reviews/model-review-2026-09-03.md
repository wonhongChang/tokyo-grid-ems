# 2026-09-03 v14-r2 운영 모델 점검

언어: [English](../../en/model-reviews/model-review-2026-09-03.md) / [日本語](../../ja/model-reviews/model-review-2026-09-03.md)

점검일: 2026-09-03 JST

근거 범위: v14-r2가 온전히 서빙된 2026-08-22~09-02 확정 실측 288시간, 2026-09-03 00~20시 실측 21시간, 동일 실행 시점 forecast snapshot, 운영 calibration snapshot, 진단 피처, 예측 밴드

재현 기준: `origin/data` commit `cb4e9c6d5`, forecast contract `v14-r2-source-robust-day-ahead`, artifact SHA `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`

상태: 완료 - v14-r2 임시 유지, 운영 상태를 `review_required`로 판단, P0 정합성 수정과 v15 Challenger 실험 필요, 이번 점검에서는 예측 동작 변경 없음

## 결론

- v14-r2는 바로 롤백하지 않는다. 현재 기간에 동일 조건으로 검증된 대체 모델이 없고, Intraday 보정은 전체적으로 오차를 줄이고 있다.
- 그러나 현재 Champion을 `healthy`로 볼 수는 없다. 8월 22일~9월 2일 확정 구간의 서빙 MAE는 693.6MW였지만, 동일 실행 시점 기준으로는 모든 lead bucket에서 TEPCO보다 26~51% 큰 오차를 보였다.
- 9월 3일 00~20시는 MAE 925.8MW, bias +821.9MW다. 특히 16~17시가 +3.11~+3.48GW 과대예측으로 무너졌다.
- 가장 큰 문제는 Intraday나 Freeze보다 raw q50이다. 0~2시간 lead에서 raw MAE 1,201.7MW가 후처리 및 Intraday를 거쳐 1,004.9MW로 줄었다.
- 현재 예측 밴드는 정확하다기보다 지나치게 넓다. P95 coverage는 100%지만 평균 반폭이 약 3.70GW이고, 관측 시간의 88%가 설정 상한에 닿았다.
- 즉시 수정할 것은 모델 수치가 아니라 평가와 calibration 기반이다. `same_regime_day_level_calibration`의 snapshot schema 오류, 보존 snapshot을 origin으로 간주하는 불안정성, 서로 다른 모델 계약이 섞인 Champion health를 먼저 바로잡아야 한다.
- 그 다음 v15 Challenger를 만들어 lag/동일 영업유형 anchor 의존도와 기상 전환 피처를 재검증한다. 검증 없이 cap이나 특정 시간 guard를 추가하지 않는다.

## 평가 원칙

이번 점검에서는 서로 다른 세 종류의 수치를 구분했다.

| 구분 | 용도 | 주의점 |
|---|---|---|
| 최종 서빙선 | 사용자가 실제로 본 예측 품질 평가 | Published Forecast Freeze가 적용된 운영 결과 |
| 동일 vintage 비교 | 같은 `capturedAt`에서 모델과 TEPCO 예측을 비교 | 현재 가능한 가장 공정한 외부 비교 |
| 최신 TEPCO 값 | 대시보드의 최신 TEPCO 예측과 비교 | TEPCO가 과거 예측도 수정하므로 공식 우열 판정에 사용하지 않음 |

TEPCO 예측은 모델 입력이나 보정값으로 사용하지 않는다. 이 문서의 TEPCO 수치는 외부 benchmark로만 사용한다.

## 데이터 무결성

| 점검 | 결과 | 근거 |
|---|---|---|
| v14-r2 적용 범위 | 통과 | 8월 21일은 전환일이라 제외하고 8월 22일부터 동일 artifact SHA 사용 |
| 확정 실측 | 통과 | 8월 22일~9월 2일 12일, 288시간 확보 |
| 당일 실측 | 통과 | 9월 3일 00~20시 21시간 확보 |
| 핵심 진단 피처 | 통과 | 확정 288시간에서 수요, 기온, 습도, lag, 영업유형 anchor 결측 없음 |
| 단계 복원 | 통과 | 215개 calibration snapshot, 미래 예측 2,851행을 최대 17초 차이로 forecast snapshot과 연결 |
| 기상 vintage 추적 | 미흡 | 시간별 값은 있으나 예보 발행시각과 source lineage가 충분히 보존되지 않음 |
| 고정 origin 보존 | 실패 | 하루 snapshot 상한 때문에 진짜 최초 발행본이 삭제될 수 있음 |

## 확정 일별 성능

| 날짜 | 구분 | MAE MW | WAPE | RMSE MW | Bias MW | 최대 오차 MW |
|---|---|---:|---:|---:|---:|---:|
| 2026-08-22 | 토요일 | 682.6 | 2.08% | 903.2 | -98.0 | 1,966.2 |
| 2026-08-23 | 일요일 | 503.0 | 1.64% | 721.1 | +95.5 | 2,510.0 |
| 2026-08-24 | 영업일 | 687.7 | 1.79% | 866.1 | -129.7 | 1,973.9 |
| 2026-08-25 | 영업일 | 446.3 | 1.09% | 601.1 | +19.0 | 1,810.0 |
| 2026-08-26 | 영업일 | 698.4 | 1.68% | 877.5 | +114.8 | 2,170.7 |
| 2026-08-27 | 영업일 | 1,140.3 | 3.18% | 1,473.4 | +1,037.7 | 3,634.7 |
| 2026-08-28 | 영업일 | 972.1 | 2.66% | 1,113.2 | -218.4 | 2,150.9 |
| 2026-08-29 | 토요일 | 1,173.3 | 4.15% | 1,355.5 | +763.6 | 2,490.0 |
| 2026-08-30 | 일요일 | 473.1 | 1.79% | 651.9 | +9.4 | 1,507.3 |
| 2026-08-31 | 영업일 | 815.7 | 2.60% | 1,007.8 | +341.8 | 2,129.3 |
| 2026-09-01 | 영업일 | 334.7 | 1.02% | 491.6 | +43.5 | 1,635.1 |
| 2026-09-02 | 영업일 | 395.6 | 1.11% | 557.4 | -159.7 | 1,650.0 |

확정 12일 합계는 MAE 693.6MW, WAPE 2.02%, RMSE 933.5MW, bias +151.6MW다. 첫 5일의 MAE는 603.6MW, 최근 7일은 757.8MW였지만 최근 3일은 다시 515.3MW였다. 단순한 지속 열화보다 특정 레짐에서 크게 실패하는 변동성 문제가 더 강하다.

## 9월 3일 00~20시 잠정 평가

| 지표 | 결과 |
|---|---:|
| 관측 시간 | 21시간 |
| MAE | 925.8MW |
| WAPE | 2.62% |
| RMSE | 1,292.8MW |
| Bias | +821.9MW |
| 최대 오차 | +3,480.0MW, 17시 |
| Shape delta MAE | 782.1MW |

주요 오차는 11시 +1.95GW, 15시 +1.45GW, 16시 +3.11GW, 17시 +3.48GW다. 18시 이후에는 예측이 급히 내려오며 오차가 +0.34GW까지 줄었다.

9월 3일 snapshot을 시간순으로 보면 16시 예측은 00:25부터 +4.31GW 높았고 05:30 이후에는 +6.05GW까지 벌어졌다. 17시도 오전부터 +4.73~+5.40GW 높았다. 따라서 16~17시 실패를 직전 Intraday 한 번의 문제로 설명할 수 없다.

17:37 실행에서는 18시 raw q50이 42,359.6MW에서 38,768.6MW로, 19시는 40,181.9MW에서 37,709.8MW로 크게 내려갔다. 같은 시점에 기상 delta도 18시 -0.7°C에서 -3.2°C, 19시 -0.5°C에서 -2.2°C로 수정됐다. 최신 기상 정보는 뒤 시간대를 구했지만 이미 닫힌 16~17시에는 늦었다. 다만 예보 발행시각과 출처가 snapshot에 완전히 남지 않아 기상 API 자체의 오류로 단정하지 않는다.

## 시간대별 성능

8월 22일~9월 3일 20시까지의 실제 서빙선을 시간대로 집계했다.

| 구간 | 표본 | MAE MW | Bias MW | RMSE MW | 절대오차 P95 MW |
|---|---:|---:|---:|---:|---:|
| 00~05시 | 78 | 474.3 | +24.6 | 610.1 | 1,264.4 |
| 06~10시 | 65 | 670.3 | -17.7 | 896.5 | 1,907.0 |
| 11~15시 | 65 | 793.0 | +364.5 | 1,023.7 | 2,170.7 |
| 16~18시 | 39 | 1,048.7 | +544.0 | 1,335.2 | 3,110.0 |
| 19~23시 | 62 | 744.9 | +245.9 | 1,040.9 | 2,133.7 |

취약 구간은 16~18시, 11~15시, 19~23시 순이다. 개별 시각 MAE도 18시 1,263.7MW, 19시 1,108.9MW, 17시 1,055.5MW, 14시 958.0MW, 09시 897.6MW 순으로 높다.

## 동일 Vintage 외부 비교

확정 12일의 forecast snapshot에서 같은 `capturedAt`과 같은 미래 시각을 맞춰 비교했다.

| Lead | 표본 | 모델 MAE MW | 모델 WAPE | TEPCO MAE MW | 모델/TEPCO |
|---|---:|---:|---:|---:|---:|
| 0~2시간 | 396 | 954.3 | 2.71% | 631.9 | 1.51 |
| 2~4시간 | 375 | 1,277.5 | 3.50% | 928.3 | 1.38 |
| 4~8시간 | 685 | 1,604.7 | 4.24% | 1,228.8 | 1.31 |
| 8~24시간 | 1,221 | 1,634.7 | 4.46% | 1,296.4 | 1.26 |

0~2시간 lead의 날짜 단위 bootstrap에서 모델과 TEPCO의 절대오차 차이는 평균 +315.8MW였고 95% CI는 +130.0~+506.4MW였다. 모델이 더 좋았던 날은 12일 중 3일이다. 기간은 아직 짧지만, 현재 모델이 동일 시점 benchmark보다 뒤처진다는 방향은 명확하다.

대시보드에 남은 최신 TEPCO 예측으로 계산한 12일 MAE는 410.2MW다. 이 값은 TEPCO가 과거 예측을 사후 수정할 수 있어 공정한 승격 기준으로 사용하지 않는다.

## 운영 단계 분해

동일 시점 snapshot으로 raw LightGBM부터 최종 서빙선까지 복원했다.

| Lead | Raw q50 MAE | Intraday 전 MAE | 최종 MAE | 최종 Bias | Intraday 개선/악화 |
|---|---:|---:|---:|---:|---:|
| 0~2시간 | 1,201.7 | 1,231.1 | 1,004.9 | +458.2 | 281 / 144 |
| 2~4시간 | 1,538.5 | 1,526.0 | 1,393.2 | +871.0 | 257 / 147 |
| 4~8시간 | 1,847.7 | 1,820.2 | 1,754.6 | +1,227.8 | 416 / 319 |
| 8~24시간 | 1,818.1 | 1,805.6 | 1,774.9 | +1,047.3 | 731 / 554 |

Intraday는 대체로 도움이 되므로 끄거나 상한을 일괄 확대하지 않는다. 동시에 lead별 34~43%에서는 오히려 악화됐으므로, 더 강한 보정을 넣는 것도 근거가 없다. 개선의 중심은 raw q50과 입력 레짐 표현이어야 한다.

0~2시간 오전 구간은 raw MAE 1,074.3MW, Intraday 전 1,154.0MW, 최종 1,096.8MW였다. Post-holiday와 timeband 계열 가드가 이 구간을 평균적으로 악화시켰을 가능성이 있으므로, 실제 trigger가 발생한 행만 분리한 shadow disable replay가 필요하다. 전체 guard를 바로 제거하지 않는다.

Published Forecast Freeze도 유지한다. 하루 종료 후 최신 정보로 재계산한 선보다 실제 당시 서빙선이 더 정확한 시간이 194개, 덜 정확한 시간이 113개였다. Freeze는 예측 시점의 기록과 공정성을 보존하며, 오늘 16~17시 실패의 원인은 Freeze가 아니라 그 시각 이전부터 높았던 예측이다.

## 원인 진단

### 1. Raw 모델의 lag와 anchor 의존

배포 q50 모델의 gain importance에서 `recent_same_business_type_mean`은 23.59%, `lag_24h`는 20.78%로 합계 44.37%다. 중요도는 인과관계가 아니지만, 최근 실패 레짐과 함께 보면 의존도가 높다.

`lag_24h`가 같은 영업유형 anchor보다 5,000MW 이상 높은 시간은 MAE 970.5MW, bias +667.0MW였다. 정상보다 뜨거웠던 전날 수요가 다음 날 예측을 위로 끄는 현상과 일치한다.

### 2. 냉각 전환과 습도 상승 레짐

전날 대비 기온이 2°C 이상 하락한 표본은 MAE 1,091.8MW, bias +930.5MW였다. 습도가 10%p 이상 상승한 표본은 MAE 1,122.9MW, bias +794.8MW였다.

8월 27일 19시는 기온 delta -7.9°C, 습도 99%, 습도 delta +29%p에서 +3.63GW 과대예측이었다. 8월 29일 12시도 기온 delta -9.7°C, 습도 delta +29%p, 과열된 lag 조건에서 +2.49GW였다. `temp_delta_24h`, `cooling_delta_24h`, `humidity_delta_24h`, `discomfort_delta_24h`의 비선형 결합을 다시 검증해야 한다.

### 3. Same-regime calibration 갱신 결함

`python/forecast/same_regime_calibration.py`의 origin raw forecast 판독은 `forecastBuild.hourly`를 찾지만 실제 snapshot은 `forecastBuild.series`를 사용한다. 이 때문에 `metrics/same_regime_day_level_calibration.json`은 8월 21일 이후 갱신되지 않았고, 영업일 +133MW 및 비영업일 -486.5MW의 오래된 adjustment가 계속 적용됐다.

8월 22일~9월 2일 counterfactual에서는 이 오류를 고쳐도 aggregate raw MAE 개선이 약 12.5MW에 그쳤다. 따라서 이것이 전체 오차의 주원인은 아니지만, calibration이 조용히 stale 상태로 작동한다는 점은 P0 운영 결함이다.

또한 하루당 snapshot을 16개만 보존하므로 가장 오래된 보존본이 진짜 고정 origin이 아닐 수 있다. 8월 22일의 최초 보존본은 당일 03:33, 9월 3일은 당일 01:33이었다. 현재의 "가장 이른 파일" 선택은 고정 발행 시점 계약이 아니다.

### 4. Champion health의 모델 계약 혼합

현재 `model_promotion.json`은 Champion을 `healthy`로 기록하지만, 28일 운영 replay는 8월 6일~9월 2일로 v11과 v14-r2를 함께 집계한다. v14-r2의 배포 이후 성능을 이전 모델 날짜가 희석한다.

모델 health, 승격 gate, 회귀 경보는 artifact SHA와 forecast contract별로 집계해야 한다. 현재 계약의 표본 수와 기간도 함께 노출해야 한다.

### 5. 기상 예보 Vintage 추적 부족

9월 3일 늦은 오후처럼 forecast weather가 실행 중 크게 수정될 때 원인은 값만으로 완전히 재현할 수 없다. 각 예측 실행에 `weather_source`, `forecast_issued_at`, `fetched_at`, AMeDAS 대비 residual, fallback 여부를 함께 저장해야 한다.

## 예측 밴드 평가

8월 22일~9월 3일 20시까지 P95와 P99 coverage는 모두 100%다. 그러나 P95 평균 반폭은 3,703MW이고 309개 중 272개, 88.0%가 3,750MW 상한에 닿았다.

이는 좋은 calibration이 아니라 분별력이 낮은 과대 폭이다. 현재 rolling conformal은 최소 폭 floor만 올릴 수 있고, native quantile 폭이 과대해도 줄일 수 없다.

다음 후보는 v14-r2 전용 표본으로 lead와 timeband를 함께 나눈 conformal interval이어야 한다. 운영 적용 전 목표는 전체 P95 coverage 93~97%, 모든 주요 구간 90% 이상, 평균 폭 15% 이상 축소다. 표본 부족 구간은 넓은 상위 그룹으로 backoff한다.

## 수정 과제

| 우선순위 | 수정 내용 | 이유 | 완료 기준 |
|---|---|---|---|
| P0 | `forecastBuild.series`를 읽도록 same-regime parser 수정 | calibration state가 8월 21일 이후 stale | 24개 raw row 파싱 테스트 통과, 최신 확정일로 state 갱신 |
| P0 | 고정 origin snapshot을 rolling cap 밖에 별도 보존 | 가장 이른 보존 파일은 고정 vintage가 아님 | 각 날짜의 origin ID와 발행시각 불변, prune 후에도 유지 |
| P0 | calibration freshness guard와 경보 추가 | stale adjustment의 조용한 적용 방지 | stale 시 적용 중단 또는 명시적 degraded 상태, 리포트에 age 표시 |
| P0 | Champion health를 artifact/contract별로 분리 | v11과 v14-r2 혼합으로 현재 상태가 가려짐 | 배포일 이후 동일 SHA만 집계, coverage와 표본 수 노출 |
| P1 | v15 Challenger 재학습 및 ablation | raw q50가 주된 오차 원인 | v14와 동일 cutoff/replay에서 lag 및 기상 후보별 비교 |
| P1 | lag와 동일 영업유형 anchor의 동적 혼합 실험 | 과열 lag 레짐에서 +667MW bias | 큰 lag-anchor gap에서만 완만한 regularization, 정상 레짐 회귀 없음 |
| P1 | 기상 delta 및 습도 피처 ablation | 냉각·습도 상승 레짐의 반복 과대예측 | source-robust, no-humidity, clipped/signed transform 후보 비교 |
| P1 | 기상 source와 issue-time lineage 저장 | 늦은 예보 수정의 원인 재현 불가 | 모든 snapshot에 source, issued/fetched time, fallback, residual 기록 |
| P1 | Post-holiday/timeband trigger shadow disable replay | 오전 0~2h에서 평균 악화 가능성 | trigger 행만 matched replay, 구간별 개선과 회귀 동시 제시 |
| P1 | v14 전용 interval recalibration shadow | P95가 88% 상한 포화 | coverage gate를 지키며 평균 반폭 15% 이상 축소 |
| P2 | D-1 고정 예측용 24~48h lead bucket 추가 | 내일 예측 품질과 Intraday 품질 분리 | 고정 D-1 origin을 별도 보존하고 독립 지표 제공 |

## v15 실험 원칙

1. 학습 cutoff를 2026-09-02까지 확장하되, 현재 v14-r2와 동일한 데이터 계약으로 비교한다.
2. 기본 후보, lag regularization 후보, 기상 delta clipping 후보, no-humidity/source-robust 후보를 분리한다. 여러 변경을 한 번에 묶지 않는다.
3. 전체 MAE/WAPE 외에 06~10시, 11~15시, 16~18시, 19~23시와 영업/비영업을 각각 평가한다.
4. 기존 v14-r2와 paired date/hour 비교 및 bootstrap CI를 사용한다. 최신 TEPCO MAE는 승격 gate가 아니다.
5. 특정 실패일만 고치는 후보는 거부한다. 최소 28/56/84일 replay와 v14-r2 배포 이후 고정 origin 구간을 함께 본다.
6. 자동 승격은 재활성화하지 않는다. 주간 Challenger 생성은 shadow로 재개할 수 있지만 최종 승격은 별도 승인으로 한다.

## 다음 점검

달력만 기다릴 필요는 없다. P0 수정과 v15 replay가 준비되는 즉시 기술 검토를 진행한다.

운영 상태 재평가는 현재 계약과 설정을 바꾸지 않는다는 전제에서 확정 실측 7일이 더 쌓인 2026-09-10 오전 ETL 이후가 적절하다. 그 전에 serving 코드를 바꾸면 변경 시점부터 새 관측 창을 시작한다.

이번 점검은 평가와 수정 계획만 작성했다. 모델 artifact, config, guard, 배포 데이터는 변경하지 않았다.
