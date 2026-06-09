# 2026-06-09 오전 실측 앵커 상한 가드

## 문제

2026-06-09 라이브 예측에서 오전 후반 예측선이 크게 높아졌습니다.

- 10시는 실측이 30,690 MW로 정체했지만, 공개된 모델 예측선은 약 32,081 MW까지 올라갔습니다.
- 11시와 12시도 실측 경로보다 높았고, 예측 밴드 하단 이탈이 발생했습니다.
- 06:10 intraday 스냅샷은 10~12시에 훨씬 가까웠지만, 07:30 ETL 재생성 이후 같은 날짜의 미래 예측선이 충분한 당일 실측 근거 없이 900~1,200 MW가량 상승했습니다.

## 기각한 방향

처음에는 active-day 예측선이 이전 스냅샷보다 급격히 움직이면 제한하는 drift limiter를 검토했습니다. 하지만 최근 스냅샷으로 가상 검증해보니, 2026-06-09에는 도움이 되지만 실제 오전 ramp가 살아나는 다른 날에는 악화 위험이 있었습니다.

그래서 예측선 이동 자체를 제한하는 방식은 기각했습니다.

## 구현한 레이어

`intraday_correction.morning_observed_anchor_cap`을 추가했습니다.

이 레이어는 TEPCO 예측을 따라가지 않습니다. 또한 오전 예측을 무조건 누르지도 않습니다. 마지막 당일 실측이 이미 모델보다 낮게 들어왔고, 가까운 미래 예측선이 lag/recent shape로 설명 가능한 상한보다 높을 때만 보수적으로 줄입니다.

## 작동 조건

아래 조건이 모두 맞을 때만 작동합니다.

- 영업일만 대상.
- 마지막 관측 시간이 08~12시.
- 마지막 관측 잔차가 모델 대비 -200 MW 이하.
- 대상 시간은 10~13시이며 lead time은 4시간 이내.
- 예측값이 `마지막 실측 + 누적 shape support + 250 MW`를 초과.

`누적 shape support`는 각 시간의 아래 두 값 중 큰 값을 사용합니다.

- `lag_24h_hourly_delta`
- `recent_same_business_type_delta_mean`

상한을 초과한 부분만 75% 비율로 줄이며, 최대 감산량은 800 MW입니다.

## 진단 메타데이터

운영 calibration JSON에 아래 필드를 남깁니다.

- `morningObservedAnchorCapApplied`
- `morningObservedAnchorCapMaxReductionMw`
- `morningObservedAnchorCapReductionMw`
- `morningObservedAnchorCapMw`
- `morningObservedAnchorCapCumulativeSupportMw`
- `morningObservedAnchorCapLatestResidualMw`

AI 일일 리포트의 feature catalog에도 `intraday_correction.morning_observed_anchor_cap`을 추가했습니다.

## 검증

- 2026-06-09 오전 후반 과대예측 패턴을 재현하는 회귀 테스트를 추가했습니다.
- 마지막 실측 잔차가 충분히 음수가 아니면 작동하지 않는 no-op 테스트를 추가했습니다.
- 대상 테스트: `tests/test_intraday_correction.py` 통과.
