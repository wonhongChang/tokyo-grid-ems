# 2026-07-06 주말 positive-tail lift와 17시 감쇠

언어: [English](../../en/model-improvements/model-improvement-2026-07-06-weekend-positive-tail-and-evening-damping.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-06-weekend-positive-tail-and-evening-damping.md)

## 배경

2026-07-04 토요일 예측은 전반적으로 양호했다. 공개 JSON 기준 모델 MAE는 약 245MW였고, TEPCO의 약 268MW보다 조금 좋았다.

문제가 명확했던 날은 2026-07-05 일요일이었다.

- 12시 JST는 약 1.5GW 과소예측이었다. 10시와 11시 잔차는 이미 양수였지만, 09시 과대예측이 rolling residual gate를 지나치게 보수적으로 만들었다.
- 17시 JST는 약 0.9GW 과대예측이었다. raw/pre-calibration 예측은 실제와 가까웠지만, 점심~오후에 생긴 양수 잔차 carryover가 서빙선을 너무 올렸다.

2026-07-06 월요일은 분석 시점에 00시 실측만 있었기 때문에, 불완전한 근거만으로 월요일 전용 보정을 추가하지 않았다.

이번 변경은 TEPCO 예측을 입력으로 쓰지 않는다. TEPCO는 외부 비교 기준으로만 사용한다.

## 변경 사항

### 비영업일 positive-tail override 기반 daytime lift

`intraday_correction.daytime_sustained_underforecast_lift`에 좁은 범위의 비영업일 positive-tail override를 추가했다.

주말 당일 최신 실측 잔차가 연속 양수라면, 한 시간 앞의 과대예측이 rolling mean 전체를 억누르지 않도록 최신 positive tail만 따로 평가할 수 있다. 2026-07-05처럼 10시와 11시는 모두 과소예측이었지만 09시가 과대예측이었던 상황을 겨냥한다.

이 override는 여전히 아래 조건을 통과해야 한다.

- 비영업일 문맥
- 연속 양수 잔차
- 최신/평균/최대 잔차 임계값
- 대상 시간의 열/습도 문맥
- 기존 시간별 lift cap

운영 스냅샷에는 `daytimeSustainedUnderforecastPositiveTailOverrideActive`를 남겨 AI/Ops 리포트가 lift 허용 이유를 설명할 수 있게 했다.

### 비영업일 17시 positive residual damping

`intraday_correction.non_business_evening_positive_residual_damping`의 대상에 17시 JST를 추가하고, lead hour 2부터 작동할 수 있게 했다.

2026-07-05의 17시처럼 대상 시간의 lag/recent shape 지지가 약한데도 오후 양수 잔차가 밀려 들어오는 사각지대를 닫기 위한 수정이다. damping은 여전히 아래 조건을 요구한다.

- 비영업일 문맥
- 충분히 큰 양수 base adjustment
- 대상 시간의 약한 lag/recent support
- 최소 감쇠 MW 기준

## 검증

다음 회귀 테스트를 추가했다.

- 2026-07-05와 유사한 주말 점심 케이스에서, 앞선 한 시간 과대예측이 있어도 최신 positive tail이 daytime lift를 켜는지
- 주말 17시 weak-shape 케이스에서 positive residual carryover가 감쇠되는지

대상 테스트:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_weekend_daytime_lift_uses_positive_tail_after_one_earlier_overforecast tests/test_intraday_correction.py::test_intraday_damps_non_business_17h_positive_carryover_when_shape_is_weak -q
```

결과: `2 passed`.

관련 테스트:

```powershell
python -m pytest tests/test_intraday_correction.py tests/test_ai_daily_report.py -q
```

결과: `105 passed`.

## 운영 메모

이번 변경은 주말 전용 운영 보정 개선이지, 주말 수요를 전반적으로 올리는 수정이 아니다. 당일 실측 잔차 근거가 쌓인 뒤에만 반응한다.

2026-07-06은 오전~낮 실측이 더 쌓인 뒤 다시 평가해야 한다. 00시 한 시간만으로 월요일 전용 guard를 추가하기에는 근거가 부족했다.
