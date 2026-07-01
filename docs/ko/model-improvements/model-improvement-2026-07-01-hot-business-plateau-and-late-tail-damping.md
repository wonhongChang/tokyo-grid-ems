# 2026-07-01 고온다습 영업일 plateau와 늦은 저녁 tail 감쇠

언어: [English](../../en/model-improvements/model-improvement-2026-07-01-hot-business-plateau-and-late-tail-damping.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-01-hot-business-plateau-and-late-tail-damping.md)

## 배경

2026-06-30 영업일 예측에서는 명확한 실패 모드가 있었다.

- 02:18 JST intraday 스냅샷에서는 오후 피크가 실제에 가까운 수준이었다.
- 07:31 JST ETL 재생성 이후 raw LGBM 곡선이 오후를 훨씬 낮게 다시 해석했다.
- 이후 14~17시 고온다습 plateau를 과소예측했다.
- 오후 miss 뒤에는 양수 잔차가 21~23시까지 이월됐고, 이때 lag/recent shape는 이미 하락을 가리키고 있었다.

이번 수정도 TEPCO 독립 원칙을 유지한다. TEPCO는 진단용 외부 기준으로만 사용한다.

## 변경 사항

### 영업일 daytime lift에 절대 heat context 추가

`intraday_correction.daytime_sustained_underforecast_lift`가 영업일에서도 다음 절대 고온다습 조건을 볼 수 있게 했다.

- `business_min_discomfort_index`
- `business_min_apparent_temp_c`

기존 영업일 경로는 주로 24시간 기상 delta에 의존했다. 그래서 이미 충분히 고온다습해서 오후 plateau가 지속되는 날에도, 해당 시간의 delta가 강하지 않으면 lift가 켜지기 어려웠다.

단, 실측 residual 근거는 여전히 필수다. 습하거나 덥다는 이유만으로 forecast를 올리지는 않는다.

### 오후 handoff를 더 늦은 시간까지 허용

daytime underforecast lift가 15시 실측까지 참고하고, 17시까지 보호할 수 있게 했다. 2026-06-30처럼 14~15시 실측이 들어온 뒤에야 sustained peak가 명확해지는 케이스를 겨냥한다.

### 20시 이후 늦은 저녁 positive carryover 감쇠

`afternoon_positive_residual_carryover_damping`을 조정했다.

- 23시까지 대상에 포함
- 최신 실측이 20시인 경우에도 damping context 유지

오후 과소예측으로 생긴 양수 잔차가, lag/recent shape가 하락하는 늦은 저녁 tail까지 기계적으로 전파되는 것을 막는다.

## 검증

다음 회귀 테스트를 추가했다.

- 2026-06-30과 유사한 고온다습 영업일 plateau에서, 실측 과소예측 근거가 확인된 뒤에만 16~17시를 lift
- 20시 실측 이후 21~23시 positive residual carryover를 감쇠

검증 명령:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_daytime_lift_uses_business_discomfort_plateau_after_hot_afternoon_miss tests/test_intraday_correction.py::test_intraday_damps_business_late_evening_positive_carryover_after_20_observed_hour -q
```

결과: `2 passed`.

## 운영 메모

2026-06-30의 중요한 교훈은 ETL 재생성이 raw LGBM 곡선을 크게 바꿀 수 있다는 점이다. 보존된 forecast snapshot 덕분에, 초기 intraday 곡선은 최종 오후 피크에 더 가까웠고 ETL 이후 곡선이 피크를 과하게 낮춘 것을 확인할 수 있었다.

다음에는 AI/Ops 리포트가 아래 세 가지를 더 명확히 분리해서 설명하는지 확인해야 한다.

- freeze 때문에 남은 served forecast 오차
- 최신 재계산 forecast 오차
- ETL 재생성 이후 raw LGBM shape 오차
