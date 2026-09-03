# 2026-09-04 운영 증거 무결성과 보정 상태 Fail-Closed

언어: [English](../../en/model-improvements/model-improvement-2026-09-04-operational-evidence-integrity.md) / [日本語](../../ja/model-improvements/model-improvement-2026-09-04-operational-evidence-integrity.md)

## 문제

9월 운영 검토에서 `same_regime_day_level_calibration` 상태가 8월 22일 이후 갱신되지 않은 사실을 확인했다. 원인은 보정기가 스냅샷의 실제 표준 필드인 `forecastBuild.series`가 아니라 과거 필드명 `forecastBuild.hourly`를 읽고 있었기 때문이다. 더구나 날짜별 스냅샷은 최대 개수 제한으로 정리되므로, 버그를 고친 뒤에도 최초 D-1 예측을 과거 전체에 대해 안전하게 복원할 수 없었다.

운영 replay의 건강도 역시 최근 28일 전체를 한데 합쳐 사용했다. 이 값에는 이전 모델 계약과 전환일의 혼합 예측이 포함될 수 있어 현재 Champion의 성능으로 간주하기 어려웠다.

## 변경

- 보정기가 표준 `forecastBuild.series`를 읽고, 기존 `hourly`는 이전 형식 호환용으로만 허용한다.
- 각 대상일에 대해 최초 D-1 raw LightGBM 예측을 `forecast_origins/<date>/<artifact>.json`에 한 번만 저장한다.
- 고정 원점은 일반 intraday 스냅샷 개수 제한과 분리하고 120일간 유지한다.
- 같은 날짜의 재계산 결과를 D-1 원점으로 승격하지 않으며, 모델 계약과 artifact hash가 모두 일치할 때만 잔차 상태에 편입한다.
- 최신 확정 잔차가 `max_state_lag_days`를 넘으면 보정을 적용하지 않는 fail-closed 정책을 도입했다.
- 운영 replay에 현재 모델 계약과 artifact가 정확히 일치하는 `championScope`를 추가했다. 승격 당일은 이전 모델의 고정 시간이 섞일 수 있으므로 다음 완전한 날짜부터 집계한다.
- Champion 건강도는 계약 범위 성능과 보정 상태의 호환성 및 최신성을 함께 검사한다.
- 각 예측 스냅샷에 보정 상태, 최신 잔차 날짜, 지연 일수와 실제 적용량을 남긴다.

## 마이그레이션

이미 롤링 정리로 삭제된 D-1 원점은 같은 날 재계산선으로 대체하지 않는다. 배포 직후에는 충분한 새 고정 원점과 확정 실적이 쌓일 때까지 동일 레짐 보정이 `stale_state` 또는 `insufficient_same_regime_history`로 우회될 수 있다. 이는 출처가 불명확한 과거 예측을 실측 전 잔차로 오인하는 것보다 안전하다.

## 영향

이 변경은 LightGBM 가중치, q50, 밴드 또는 후처리 계수를 조정하지 않는다. 목적은 v15 실험 전에 평가 원점과 현재 Champion 건강도를 재현 가능하게 만들고, 오래된 상태가 조용히 예측을 이동시키는 일을 막는 것이다.

## 검증

- 표준 `series` 기반 잔차 상태 갱신
- 고정 D-1 원점의 최초 기록 불변성 및 롤링 스냅샷 정리와의 분리
- 오래된 보정 상태의 fail-closed 동작
- 모델 계약 및 artifact별 운영 replay 격리
- 승격 상태 점검에서 보정 최신성 검증
- 전체 테스트: 577개 통과
