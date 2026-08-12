# 영업일 복귀 보정의 실측 과대예측 Veto

언어: [English](../../en/model-improvements/model-improvement-2026-08-12-business-return-observed-overforecast-veto.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-12-business-return-observed-overforecast-veto.md)

## 현상

2026-08-12는 산의 날 다음 첫 영업일이어서 영업일 복귀 anchor가 lag-24의 휴일 패턴을 올바르게 인식했습니다. 하지만 당일 실측은 이미 예측 수준이 높다는 반대 증거를 보여주고 있었습니다.

- 07시 shortfall 보정 전 예측은 27,498.3 MW, 실측은 25,380 MW로 2,118.3 MW 과대예측이었습니다.
- 그런데도 anchor-shortfall 레이어는 08시와 09시에 각각 1,000 MW를 추가했습니다.
- 그 결과 post-holiday 단계의 08시 오차는 3,899 MW였고, 이후 확정된 09시 실측 기준 단계 오차는 3,364.6 MW였습니다.

휴일에서 영업일로 복귀한다는 사전 정보와 당일 실측 증거가 서로 반대 방향을 가리킨 사례입니다. 오전 램프 실측이 없을 때는 기존 prior가 유효하지만, 큰 과대예측이 확인된 뒤에는 추가 상승 보정의 근거가 약해집니다.

## 변경

추론 전용 문맥에 `same_day_latest_actual_hour`와 함께 `same_day_latest_actual_mw`를 추가했습니다. `business_return_anchor_shortfall` 레이어는 상승 보정 전에 `observed_overforecast_veto`를 평가합니다.

다음 조건을 모두 만족할 때만 veto가 작동합니다.

- 기존 영업일 복귀 shortfall 조건을 먼저 통과할 것
- 최신 실측 기준 시간이 07시 이후일 것
- 대상 시간이 기준 실측보다 1~3시간 뒤일 것
- 기준 시간의 shortfall 보정 전 예측이 실측보다 1,200 MW 이상 높을 것

작동 시 해당 시간의 영업일 복귀 추가 상승분만 생략합니다. raw LightGBM 출력, 유사일 결과, 예측 밴드, 전역 intraday 잔차 cap은 변경하지 않으며 TEPCO 예측값도 사용하지 않습니다.

## 설정

```yaml
observed_overforecast_veto:
  enabled: true
  min_reference_hour: 7
  max_lead_hours: 3
  min_overforecast_mw: 1200
```

높은 증거 임계값과 짧은 lead 범위로 개입을 국소화했습니다. 오차가 작으면 기존 anchor-shortfall 보정이 그대로 유지됩니다.

## 운영 Replay

보존 중인 최근 21일 forecast snapshot에서 새 조건을 만족하면서 실측까지 확정된 대상은 한 시간뿐이었습니다. 추가 상승분만 제거한 post-holiday 단계 반사실 결과는 다음과 같습니다.

| 날짜 / 시간 | 기존 단계 오차 | veto 반사실 오차 | 변화 |
|---|---:|---:|---:|
| 2026-08-12 08시 | 3,899 MW | 2,899 MW | -1,000 MW |

09시 실측이 29,370 MW로 확정된 뒤 같은 단계 반사실을 적용하면 09시 오차도 3,364.6 MW에서 2,364.6 MW로 줄어듭니다. 이는 당일 제어기의 좁은 충돌을 고친 결과이지, 모델 전체의 성능 향상을 입증한 것은 아닙니다. 보존 구간의 다른 전환일에는 veto 임계값을 만족한 기록이 없어 과거 개입 회귀는 없었지만, 여러 레짐에 대한 검증이 끝났다는 의미도 아닙니다.

## 검증과 범위

- feature builder와 adjustment 집중 테스트: `139 passed`
- 전체 저장소 테스트: `502 passed`
- 큰 과대예측에서는 상승 보정을 취소하고, 작은 오차에서는 기존 보정을 유지하는 양쪽 경로를 검증했습니다.
- v11 Champion, 학습 피처 집합, raw quantile 모델, 밴드 calibration, 점심 보정, 게시 예측 freeze 정책은 변경하지 않았습니다.
