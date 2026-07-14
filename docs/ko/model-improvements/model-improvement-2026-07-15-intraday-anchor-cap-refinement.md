# 2026-07-15 intraday anchor cap 정교화

언어: [English](../../en/model-improvements/model-improvement-2026-07-15-intraday-anchor-cap-refinement.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-15-intraday-anchor-cap-refinement.md)

## 배경

warm-day lag24 기상 허용폭을 반영한 뒤에도 2026-07-14 차트는 전체적으로 좋지 않았습니다. 스냅샷을 분해해 보니 원인은 둘로 나뉘었습니다.

- 10:00~12:00의 가짜 골짜기는 기존 warm-day lag24 cap이 늦게 풀리면서 생긴 freeze 영향이 컸습니다.
- 09:00 스파이크와 14:00~18:00 plateau 과대예측은 별도의 intraday 제어 공백이었습니다.

2026-07-14 관측 완료 구간 기준 성능은 다음과 같았습니다.

| 구간 | 모델 MAE | TEPCO MAE |
| --- | ---: | ---: |
| 관측 21시간 | 815 MW | 478 MW |
| 09:00~19:00 | 1,104 MW | 578 MW |
| 13:00~18:00 | 1,114 MW | 657 MW |

주요 오차는 다음과 같습니다.

- 09:00: +2,162 MW
- 14:00: +1,485 MW
- 16:00: +1,242 MW
- 18:00: +1,536 MW

## 원인

### 오전 09:00 스파이크

08:00 실측은 모델과 거의 비슷했기 때문에 기존 `morning_observed_anchor_cap`은 작동하지 않았습니다. 하지만 09:00 예측은 `직전 실측 + lag/recent ramp support`로 설명 가능한 수준보다 훨씬 위로 뛰었습니다.

즉 최신 residual이 아직 음수가 아니더라도, 강한 기온 상승 신호와 함께 가까운 미래 예측이 ramp support를 과하게 초과하는 케이스를 별도로 막아야 했습니다.

### 오후 plateau 과대예측

13:00 실측은 점심 이후 반등했기 때문에 기존 afternoon anchor cap은 회복 국면으로 판단하고 14:00 cap을 건너뛰었습니다. 하지만 13:00 예측 자체가 이미 실측보다 약 +1.65GW 높았습니다. 따라서 최근 slope가 양수여도, residual이 매우 크게 음수인 경우에는 severe-overforecast override가 필요했습니다.

## 변경 내용

### Morning Support-Overhang Mode

`morning_observed_anchor_cap`에 `support_overhang` 모드를 추가했습니다. 다음 조건에서만 작동합니다.

- 영업일 오전 target hour
- 최신 관측 residual이 중립이거나 아주 작은 과소예측 수준
- 전날 대비 기온/냉방 delta가 뚜렷하게 양수
- target 예측이 `latest actual + lag/recent ramp support + buffer`보다 설정 임계치 이상 높음

이제 최신 관측 bucket이 아직 과대예측이 아니더라도, 09:00 근거리 점프가 support를 크게 벗어나면 보수적으로 낮춥니다.

### Afternoon Severe-Overforecast Mode

`afternoon_observed_anchor_cap`에 `severe_overforecast` 모드를 추가했습니다. 다음 조건에서만 작동합니다.

- 최신 residual과 평균 residual이 모두 큰 음수
- 최근 실측 slope가 반등 중이더라도 보수적 상한 안에 있음
- lag/recent support가 raw plateau 레벨을 설명하지 못함

이 모드는 일반 오후 cap보다 더 낮은 support fraction과 cap buffer를 사용합니다.

## 운영 효과

2026-07-14 스냅샷 재시뮬레이션 결과:

- 09:32 스냅샷: `support_overhang`으로 09:00 예측을 약 1.0GW 낮춤
- 14:15 스냅샷: `severe_overforecast`로 14:00~16:00 plateau를 약 0.7~1.3GW 낮춤
- 16:03 스냅샷: 14:00 과대예측 실측 확인 후 15:00~16:00 plateau를 더 강하게 낮춤

이미 freeze된 과거 지점은 되돌리지 않습니다. 대신 같은 패턴이 다음 intraday 실행에서 다시 서빙되는 것을 막습니다.

## 검증

- `python -m pytest tests/test_intraday_correction.py`

결과:

- `83 passed`

