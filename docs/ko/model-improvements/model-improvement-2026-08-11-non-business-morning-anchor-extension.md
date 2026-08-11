# 비영업일 오전 실측 Anchor 확장

언어: [English](../../en/model-improvements/model-improvement-2026-08-11-non-business-morning-anchor-extension.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-11-non-business-morning-anchor-extension.md)

## 현상

2026-08-11 산의 날에는 캘린더가 비영업일 경로를 정상 선택했지만 오전 raw q50이 높았다. 09시 pre-calibration 수요는 약 33.0GW, 실측은 28.56GW였다. Intraday residual 보정은 전역 -1.2GW 상한에 도달했지만 근거리 미래에 의미 있는 overhang이 남았다.

기존 `morning_observed_anchor_cap`은 영업일 전용이었다. 따라서 주말·공휴일에는 당일 실측이 과대예측을 이미 확인한 뒤에도 같은 성격의 최종 근거리 cap을 사용할 수 없었다.

## 변경

기존 anchor-cap controller에 독립적인 `non_business_extension` 설정을 추가했다. 고정 주말 shape를 만들지 않고 raw LightGBM 출력도 수정하지 않는다. 아래 조건을 모두 만족할 때 남아 있는 근거리 운영 보정만 제한한다.

- 대상 날짜가 주말 또는 일본 공휴일;
- 최신 유효 실측이 08시 또는 09시;
- 최신 model residual이 최소 400MW 과대예측을 확인;
- 대상이 최대 네 시간 lead 이내;
- lag-24 또는 최근 같은 영업 유형 delta가 유효한 shape 경로를 제공;
- 예측이 최신 실측과 누적 shape support의 합보다 여전히 높음.

초과분은 0.75 shrinkage로 줄이고 최대 감액은 1,000MW로 제한한다. 최신 실측이 09시를 지나면 확장을 종료하고 이후 당일 controller에 인계한다.

## 강한 Ramp Veto

주말·공휴일에도 실제 늦은 ramp가 나타날 수 있다. 아래 세 조건을 모두 만족하면 cap을 건너뛴다.

- 최신 실측 slope가 4,000MW 이상;
- 최근 두 실측 slope 평균이 2,500MW 이상;
- 누적 lag/recent shape support가 2,500MW 이상.

Replay에서 실제 ramp가 강했던 2026-08-08 오전을 이 veto가 보호했다.

## Replay

2026-07-18~2026-08-09 비영업일 오전 9일의 과거 calibration snapshot에서 비교 가능한 forecast-hour 68개를 복원했다.

| 지표 | 기존 | 후보 |
|---|---:|---:|
| 오전 snapshot MAE | 1,456.2 MW | 1,282.9 MW |
| MAE 변화 | - | -173.3 MW (-11.9%) |
| 변경 record | 0 | 13 |
| 최대 감액 | 0 MW | 1,000 MW |

영향을 받은 7월 18일 record 하나는 소폭 악화됐다. 전체 오차 개선, 적은 개입, 감액 상한, 강한 ramp veto, 빠른 handoff를 근거로 변경을 채택했다. 모든 비영업일 시간에서 개선된다고 주장하지 않는다.

## 기각한 대안

- v13 Challenger는 최근 28일 MAE 1,208.1MW, WAPE 3.256%로 고정 기준을 초과해 승격하지 않았다.
- 730일, 548일, 365일로 줄인 학습 기간은 최근 replay를 악화시켰다.
- q50 blend 및 영업일 residual weight 변경은 안정적인 개선을 만들지 못했다.
- 전역 intraday residual 상한 확대는 raw 예측이 회복된 이후 큰 회귀를 만들었다.
- 날짜별 조건, 고정 공휴일 offset, TEPCO 예측 calibration은 도입하지 않았다.

## 검증과 범위

- 별도 밴드 변경까지 포함한 intraday/batch/interval 집중 테스트 `155개` 통과.
- 메인 작업공간 전체 테스트 `500 passed`.
- 공개 artifact validator와 운영 동등 status 생성 통과.
- v11 Champion, raw quantile 모델, 평일 점심 로직, 승격 threshold는 변경하지 않았다. 별도 interval floor 변경은 같은 날짜의 밴드 문서에 기록했다.
- 다음 정기 점검은 다음 주말 확정치가 들어오는 2026-08-17이다.
