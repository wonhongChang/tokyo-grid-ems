# 2026-06-07 actual JSON 캐시 영속화

언어: [English](../../en/model-improvements/model-improvement-2026-06-07-actual-cache-persistence.md) / [日本語](../../ja/model-improvements/model-improvement-2026-06-07-actual-cache-persistence.md)

---

## 문제

주말 예측 점검에서 두 문제가 분리되어 확인되었습니다.

2026-06-06 토요일 확정 리포트에는 실제 shape 문제가 있었습니다. 모델은 오전 ramp를 높게 잡은 뒤 10:00-13:00은 낮게 누르고, 15:00 부근에서는 다시 과하게 위로 튀었습니다. 이 부분은 후처리 제어와 원천 모델 shape 양쪽에서 계속 관찰해야 할 케이스입니다.

2026-06-07 일요일 예측에는 별도의 데이터 연속성 문제가 겹쳐 있었습니다. `actual/2026-06-06.json`에는 토요일 실측이 이미 들어 있었지만, `.hourly_cache.parquet`에는 2026-06-06이 기상 예보용 가상 행으로 남아 있고 `actual_mw`가 모두 비어 있었습니다. 그 결과 일요일 추론에서 `lag_24h`가 비고, 모델이 더 오래된 lag, 최근 같은 영업 타입 평균, 따뜻한 날씨 신호에 과하게 의존할 수 있었습니다.

## 변경 내용

두 실행 경로에서 hourly cache 저장 시점을 actual JSON 주입 이후로 옮겼습니다.

- status/intraday refresh
- full ETL

기존 파이프라인도 예측 직전에는 최근 actual JSON을 메모리에 주입하고 있었습니다. 문제는 저장된 캐시가 주입 전 상태였다는 점입니다. 이제 `.hourly_cache.parquet`에 저장되는 캐시도 실제 예측 실행에 사용한 관측값 또는 임시 fallback actual을 포함합니다.

## 운영 효과

TEPCO 월별 ZIP이 아직 어제 CSV를 확정하지 않은 구간에서도, 시스템은 `actual/YYYY-MM-DD.json`을 lag 피처 연속성의 다리로 사용합니다. 따라서 다음날 `lag_24h` 입력이 대시보드에 표시되는 actual series와 맞춰집니다.

이 변경은 TEPCO-aware calibration layer가 아닙니다. TEPCO 예측값으로 모델을 튜닝하거나 TEPCO 곡선을 추종하지 않습니다. 단, 늦은 밤 실측이 확정 CSV로 들어오기 전까지 비어 있는 actual 행을 임시로 메우는 기존 운영 fallback 규칙은 유지합니다.

## 진단 근거

이번 케이스의 특징은 다음과 같았습니다.

- `actual/2026-06-06.json`: 24개 actual 값 존재
- `.hourly_cache.parquet`: 2026-06-06 행은 존재하지만 `actual_mw` count는 0
- 2026-06-07 추론: 모든 시간대에서 `lag_24h` 사용 불가

회귀 테스트는 actual JSON을 주입한 뒤 hourly cache를 저장하고 다시 로드하여, 수요, TEPCO forecast reference, 사용률, 공급력, 기상 필드가 함께 보존되는지 검증합니다.

## 검증

- `test_injected_actuals_can_be_persisted_to_hourly_cache`를 추가했습니다.
- `_inject_today_actuals(...)` 이후에 캐시가 저장되도록 실행 순서를 검증했습니다.

