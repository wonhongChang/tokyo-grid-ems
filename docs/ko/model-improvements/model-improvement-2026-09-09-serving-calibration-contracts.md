# 2026-09-09 서빙 보정 계약 정비

Languages: [English](../../en/model-improvements/model-improvement-2026-09-09-serving-calibration-contracts.md) · [日本語](../../ja/model-improvements/model-improvement-2026-09-09-serving-calibration-contracts.md)

## 배경과 범위

[9월 8일 모델 점검](../model-reviews/model-review-2026-09-08.md)에서 확인한 세 가지 운영 결함을 수정했다. 중심선이 틀린 이유를 예측선 보존 정책으로 돌리거나, TEPCO 예측을 입력으로 넣는 수정은 하지 않았다.

| 문제 | 이번 변경 | 변경하지 않은 것 |
|---|---|---|
| 최종 공개선 오차로 모든 리드의 밴드를 계산 | 실제 사전 발행본의 리드별 오차 사용 | 원천 quantile 학습과 q50 |
| 다른 레짐의 최신 기록으로 오래된 보정 표본까지 통과 | 실제 같은 레짐 표본의 날짜·D-1 출처 검증 | 기존 shrinkage 0.25와 cap 1,000MW |
| 최종 shape/ramp 변동이 잔차 로그에 드러나지 않음 | 끝단 보정량을 분리 기록하고 AI 팩트에 전달 | 해당 가드의 예측 계산식 |

학습 artifact는 `v14-r2-source-robust-day-ahead` 그대로다. 다만 D-1 보정을 D0에 적용하지 않으므로 **서빙 중심선은 바뀔 수 있다**. 이 변경을 새 모델 승격이나 전체 MAE 개선 완료로 취급하지 않는다.

## 1. 리드별 예측 밴드

`rolling_interval_calibration.py`의 `build_lead_conformal_profile()`이 다음 기준으로 표본을 구성한다.

1. `forecast_snapshots/`와 `forecast_origins/`의 실제 사전 발행본을 읽는다. 덮어쓴 최종 `forecast/` 값은 사용하지 않는다.
2. 학습 artifact SHA와 `servingPolicyFingerprint`가 현재 계약과 일치해야 한다. 시각은 timezone-aware여야 하며 JST로 해석한다.
3. 대상 시간 시작 전 발행된 양수 리드만 사용한다. 리드는 `(0,2]`, `(2,4]`, `(4,8]`, `(8,24]`, `(24,48]`시간으로 나눈다.
4. ETL `okDates`에 있고 진짜 실측 24개가 있는 날짜만 사용한다. TEPCO 예측 대체값은 실측이 아니다.
5. 발행일 D 기준 D-2까지, 최근 28일 범위만 사용한다. 과거 CSV의 실제 확정 시각이 없으므로 D-1 자료가 자정에도 있었던 것처럼 재현하지 않기 위한 보수적 제한이다.
6. 같은 날짜·대상 시간·리드 구간의 중복 실행은 마지막 사전 발행본 하나로 줄인다. 실행 횟수가 많은 날에 표본 가중치가 몰리지 않게 한다.

대상 시간대는 기존 `overnight` 00~05, `morning` 06~10, `daytime` 11~15, `late_afternoon` 16~18, `evening` 19~23을 사용한다. 이는 밴드 오차 집계 구간이며 수요를 강제로 올리거나 내리는 조건이 아니다.

각 리드·시간대에서 같은 레짐 집계와 전체 레짐 집계를 별도로 만든다. **집계별 최소 24표본·4개 날짜**를 통과한 q95 중 큰 값에 1.05를 곱한다. 같은 레짐 표본이 부족하면 유효한 전체 레짐 집계만 사용할 수 있지만, 다른 리드의 표본으로 채우지는 않는다.

### 도입 초기와 실패 조건

- 호환 이력이 부족하거나 리드가 범위 밖이면 `native_fallback`으로 기존 native 밴드 정규화·상한 처리를 유지한다.
- 필요한 반폭이 3,750MW보다 크면 `native_fallback_cap_exceeded`와 `requiredHalfWidthMw`를 기록한다. 상한으로 잘라놓고 목표 포함률을 달성했다고 표시하지 않는다.
- 정책 fingerprint 없는 과거 스냅샷에 새 fingerprint를 소급 부여하지 않는다. 점검 자료에는 새 계약의 호환 표본이 0개였으므로 초기에는 새 target이 활성화되지 않는다. 기존보다 밴드가 넓어질 수 있다.
- `availability: ok`는 일부 시간에 target을 계산했다는 뜻이다. 시간별 `detailsByHour`가 실제 적용 상태를 결정한다. p95라는 이름은 실증된 95% 포함률 보증이 아니다.
- 기본 보존 모드에서 관측 완료한 공개 예측의 p95/p99도 그대로 보존한다. 과거 폭을 새 정책으로 다시 만들어 성능을 좋게 보이지 않는다.

`servingPolicyFingerprint`는 q50 관련 설정과 `servingSemanticsVersion`을 식별한다. 밴드 폭 설정은 포함하지 않는다. 설정 변경 없이 q50 서빙 코드의 의미가 바뀌면 semantics version도 올려야 한다.

## 2. 같은 레짐 보정의 출처와 적용 범위

`SameRegimeDayLevelCalibrator`는 `application: day_ahead_only`, `require_day_ahead_origin: true`로 동작한다.

- 보정 대상은 JST 전날 발행하는 D-1 예측이다. 당일 예측은 `origin_horizon_mismatch`로 이 레이어를 우회하지만 intraday 잔차 보정은 계속 적용한다.
- 이력은 동일 artifact의 `immutable_day_ahead_origin`에 연결된 확정 실측 잔차만 인정한다. D0 holdout seed나 오래된 retained snapshot은 이 정책의 증거로 사용하지 않는다.
- 발행 당일 이후의 최종 실측은 이력에서 제외한다. 최신 전체 이력은 발행일 기준 2일 이내여야 한다.
- 그와 별개로 일본 영업일·휴일 달력상 최근에 있어야 할 같은 레짐 3일을 구하고, 실제 선택한 날짜가 여기에 속하는지 검사한다. 다른 레짐의 최신 기록만 있다고 오래된 평일 표본을 통과시키지 않는다. 정상적인 주말 간격은 달력으로 처리한다.
- 부족하면 `insufficient_same_regime_history`, 오래되면 `stale_same_regime_history`로 보정량 0을 반환한다. `expectedHistoryDates`, `rejectedOriginEntries`로 원인을 남긴다.

유효할 때만 일평균 잔차 3개의 중앙값 × 0.25를 +/-1,000MW 범위에서 적용한다. D-1 prior의 D0 재사용 중단은 중심선에 영향을 주므로, 이후 성능 평가는 D0/D-1을 분리해야 한다.

## 3. 최종 가드 변동량과 AI 입력

각 operational-calibration 시간 행에 `terminalAdjustments`를 남긴다. 상단 metadata에는 `terminalAdjustmentsByHour`가 있다.

| 필드 | 의미 |
|---|---|
| `preCalibrationMw` | intraday 직전 값 |
| `preTerminalAdjustmentMw` | 끝단 shape/ramp 전까지의 전체 변동. 순수 잔차만을 뜻하지 않음 |
| `shapeGuardDeltaMw` | 최종 shape 가드의 변동 |
| `rampGuardDeltaMw` | 최종 ramp 가드의 변동 |
| `postCalibrationMw` | 끝단 가드를 거친 값 |
| `totalAdjustmentMw` | intraday 직전부터의 총변동 |

```text
preCalibrationMw + preTerminalAdjustmentMw
  + shapeGuardDeltaMw + rampGuardDeltaMw = postCalibrationMw
```

기존 `residualCarryover.finalAdjustmentMw`의 의미는 바꾸지 않았다. 예를 들어 9월 8일 13:32 실행의 14시 행은 pre 42,870.1MW, 기록된 잔차 -112.1MW만으로 post 40,880MW를 설명할 수 없었다. 저장된 입력을 이용한 끝단 재구성에서 추가 -1,878.0MW가 ramp 가드에서 확인됐다. 이 재구성은 당시 공개 예측을 다시 쓰지 않는다.

AI factPacket의 제한된 `focusedRows`에 네 변동량만 추가한다. 자연어 결론을 주입하지 않고, 호출 횟수·모델·전체 24시간 전송 범위를 늘리지 않는다. 이전 AI 리포트가 자동으로 재작성되지는 않는다.

## 4. 검증 결과와 한계

- 전체 테스트 609개 통과. 외부 네트워크를 차단한 테스트 프로세스에서 검증했으며 유료 API 호출은 없었다.
- 리드 분리, 중복 표본, 미래/무시간대 시각, artifact·정책 불일치, 미확정/대체 실측, UTC→JST 시간 정합성, 과거 밴드 보존을 검증했다.
- D0 seed 배제, 같은 레짐 최신성, 정상 주말 간격, D-1/D0 적용 분리, shape/ramp 합계와 AI 팩트 전달을 검증했다.
- 고정한 data revision `0e9a67dcb`에서 끝단을 재구성할 수 있는 **61회 실행·1,464행이 기존 결과와 반올림 오차 0.2MW 이내로 일치**했다. 8회는 이전 로그에서 선행 prior를 분리할 수 없어 제외했다. 비영(非零) 끝단 변동은 7행이었다.

이는 **끝단 로그의 재구성 검증**이지 새 전체 파이프라인의 반사실 MAE 백테스트가 아니다. 새 정책 호환 이력이 없던 점검 표본에서 밴드 포함률 개선도 증명하지 않았다. raw 기상 민감도와 오전 anchor/잔차 가드의 불필요한 추가 보정 여부는 후속 실험이다.

## 5. 반영과 다음 점검

코드 배포 후 다음 Intraday/ETL부터 새 출처·리드·끝단 로그가 쌓인다. 모델 재학습이나 과거 예측 재계산 옵션을 켤 필요는 없다. 이번 검증에서는 라이브·로컬 공개 JSON을 덮어쓰지 않았다.

1. `intervalCalibration.servedTarget.detailsByHour`에서 리드별 native/target 상태와 표본·날짜 수를 확인한다.
2. D0에는 D-1 prior가 꺼지고, D-1에는 실제 사용 이력과 `expectedHistoryDates`가 맞는지 확인한다.
3. 끝단 델타 합계, q50/밴드 보존, artifact 동일성을 점검한다.
4. 호환 이력이 쌓이면 같은 발행 시각 기준으로 리드별 포함률·폭·MAE를 평가한다. 이전 계약의 이력을 현재 계약으로 재명명하지 않는다.
5. raw 기상 입력 변화에 대한 민감도와 개별 가드 on/off를 별도 replay로 비교한다. 점심 dip, 휴일 전환, 저녁 하락을 함께 평가하고 TEPCO 예측은 비교용으로만 사용한다.

되돌릴 때도 과거 최종 공개선 오차로 모든 리드의 폭을 줄이는 방식이나 D0 seed 혼합을 다시 허용해서는 안 된다. native 유지 상태를 먼저 관찰하고, 중심선 가드 조정은 별도 증거와 변경으로 관리한다.

관련 코드: [`rolling_interval_calibration.py`](../../../python/forecast/rolling_interval_calibration.py), [`same_regime_calibration.py`](../../../python/forecast/same_regime_calibration.py), [`intraday_correction.py`](../../../python/forecast/intraday_correction.py), [`run_batch.py`](../../../python/etl/run_batch.py), [`ai_daily_report.py`](../../../python/eval/ai_daily_report.py).
