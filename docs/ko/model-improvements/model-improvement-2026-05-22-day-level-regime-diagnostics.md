# 2026-05-22 하루 단위 lag/날씨 regime 진단

> 특정 시간대 guard를 더 얹기 전에, 하루 전체 곡선에서 차가운 날씨와 전날 고수요 lag가 어떻게 충돌했는지 내부 진단으로 남기는 개선 기록.

언어: [English](../../en/model-improvements/model-improvement-2026-05-22-day-level-regime-diagnostics.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-22-day-level-regime-diagnostics.md)

---

## 왜 필요했나

최근 예측 오차는 단순히 07~10시 아침 문제로 고정해서 보면 위험하다. 더 큰 운영 질문은 “오늘이 어제보다 훨씬 서늘할 때, 모델이 전날 고수요 `lag_24h`의 관성에서 하루 전체 곡선으로 충분히 벗어나는가”이다.

시간대별 guard를 계속 추가하면 예측선이 패치처럼 보일 수 있다. 그래서 새 보정이나 피처를 바로 넣기 전에, 내부 진단 JSON에 하루 단위 regime 요약을 기록하도록 했다.

---

## 변경 내용

내부 일일 진단에 `diagnosticSummary.dayLevelRegime`을 추가했다.

- 하루 전체 모델 bias와 MAE
- 평균 `lag_24h_to_same_business_type_gap`
- 최근 같은 영업/비영업 유형 대비 `lag_24h` 과열 평균과 시간 수
- 평균 `temp_delta_24h`
- 어제 대비 평균 기온 하락폭
- 평균 `cooling_delta_24h`
- 평균 `temp_anomaly_7d`
- 72시간 냉방 관성 평균
- `cool_lag_overheat_regime` 같은 flags

이 변경은 진단 전용이다. 예측 곡선 자체는 바꾸지 않는다.

---

## 기대 활용

ETL이 하루를 마감한 뒤 내부 리포트에서 다음을 같이 볼 수 있다.

- 전날 lag가 최근 같은 유형 평균보다 높았는지
- 오늘이 어제보다 전반적으로 서늘했는지
- 냉방 부하가 줄어드는 조건이었는지
- 72시간 열 관성이 아직 남아 있었는지
- 모델이 과대 예측했는지, 과소 예측했는지

이후 시간대를 하드코딩하지 않는 하루 단위 lag/날씨 상호작용 피처를 넣을지 판단하는 근거로 사용한다.

---

## 테스트

내부 진단 테스트를 갱신해 `dayLevelRegime`에 lag, 날씨, flag 필드가 생성되는지 확인한다.

전체 회귀 테스트: `308 passed`
