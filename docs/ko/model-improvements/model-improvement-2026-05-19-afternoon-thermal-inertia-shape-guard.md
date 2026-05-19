# 2026-05-19 오후 thermal inertia와 shape guard

> 14:00-18:00 예측선이 실측 수요 흐름보다 빠르게 내려간 문제에 대한 후속 개선 기록.

언어: [English](../../en/model-improvements/model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md)

---

## 어떤 문제가 있었나

2026-05-19 intraday refresh 이후 모델 예측선이 오후에 급하게 내려갔다.

방향 자체가 완전히 이상한 것은 아니었다. TEPCO도 오후에서 저녁으로 갈수록 수요 하락을 예상했다. 문제는 shape였다. 모델은 14:00-16:00 부근에서 너무 빠르게 내려갔고, 18:00 lead-time에서도 낮은 쪽에 머물렀다.

운영 관점에서는 위험한 형태다. 더운 날의 전력 수요는 열 관성이 있어서, 기온이 피크 이후 내려가기 시작해도 냉방 수요가 바로 사라지지 않을 수 있다.

---

## 진단

기존 모델에는 시간별 기온, cooling degree, weather-delta 피처가 있었다. 하지만 이 피처들은 대부분 현재 시각 또는 같은 시각 기준의 변화량을 설명한다.

모델에게 직접 전달되지 않았던 정보는 다음과 같다.

- 직전 몇 시간도 계속 더웠는지
- 기온 피크 이후에도 냉방 수요가 남을 수 있는지
- 예보 기온이 내려가기 시작해도 오후 수요가 높은 상태로 유지될 수 있는지

intraday ramp guard는 가까운 미래 1시간이 하드한 범위 아래로 무너지는 것은 막았지만, 오후 전체 shape를 부드럽게 만들지는 못했다.

---

## 변경 사항

### 1. Thermal inertia 피처

다음 rolling weather-load 피처를 추가했다.

- `cooling_degree_3h_mean`
- `cooling_degree_6h_mean`
- `heating_degree_3h_mean`
- `heating_degree_6h_mean`

이 피처는 여름 전용 규칙이 아니라 일반적인 수요 반응 피처다. cooling inertia는 더운 날에, heating inertia는 추운 겨울 오전/저녁에 도움을 줄 수 있다.

LightGBM feature version도 올려서 다음 ETL/intraday 실행 시 모델이 다시 학습되도록 했다.

### 2. Intraday 오후 shape guard

`intraday_correction.shape_guard`를 추가했다.

기본 동작은 다음과 같다.

- 12:00 이후의 당일 관측 context가 있을 때 활성화
- target hour `15-19`를 감시
- 시간 간 예측 하락폭을 `1000 MW`로 제한

TEPCO 예측을 따라가게 만드는 규칙은 아니다. 이미 당일 context가 생긴 상태에서, 공개 예측선이 운영적으로 설명하기 어려운 절벽 모양을 만드는 것을 막는 안전장치다.

---

## 기대 효과

더운 평일 오후에 모델이 높은 주간 수요에서 낮은 저녁 수요로 한두 시간 만에 과하게 내려가는 경향을 줄인다.

이 변경이 매일 TEPCO를 이긴다는 뜻은 아니다. 다만 수요가 아직 높은데 예측선만 너무 빠르게 꺾이는 특정 실패 패턴을 줄이는 것이 목적이다.

---

## 안전 메모

- 새 피처는 cooling과 heating을 모두 포함한다.
- shape guard는 범위가 좁고, 당일 관측값이 어느 정도 생긴 뒤에만 작동한다.
- guard는 daily peak level이 아니라 예측선 모양의 극단값을 제한한다.
- 과거 평가는 published forecast snapshot과 daily report를 기준으로 계속 확인한다.

---

## 테스트

다음을 검증했다.

- training/inference에서 thermal inertia 피처 생성
- inference가 같은 날 직전 시간대 기온을 반영하는지
- LightGBM feature-version 재학습 트리거
- 오후 예측선 급락 shape guard
- 기준 시각 전에는 shape guard가 비활성 상태로 남는지
