# 2026-05-27 점심 전환 가드 재활성화
> 12시 점심 시간대의 단발성 dip을 보수적으로 반영하기 위해 영업일 lunch-shape 가드를 다시 켰습니다.

언어: [English](../../en/model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md) / [日本語](../../ja/model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md)

---

## 왜 필요했나

최근 영업일 실시간 예측에서 최근 같은 영업일 패턴은 점심 시간대 하락을 보여주는데, 모델 예측선은 12시 bucket을 너무 완만하게 유지하는 문제가 있었습니다.

점심 dip은 오후 전체 추세가 아니라 한 시간대에 가까운 shape 효과입니다. 따라서 intraday residual 기울기를 오후로 밀고 가는 방식으로 해결하면 안 되고, TEPCO 예측을 따라가서도 안 됩니다. 더 안전한 방법은 점심 bucket에서만 같은 영업일 shape context와 모델 예측선을 비교하는 좁은 가드입니다.

## 변경 내용

adjustment 레이어의 `midday_transition_guard`를 다시 활성화했습니다.

이 가드는 설정된 점심 시간에만 작동합니다. 최근 같은 영업일 context가 충분히 음수인 점심 전환을 보이고, 모델 예측이 shape 기준보다 설정 allowance 이상 높을 때만 일부 하방 조정을 적용합니다.

## 운영 파라미터

기본 설정:

- `hours`: [12]
- `min_negative_delta_mw`: 500
- `min_excess_mw`: 300
- `shrinkage`: 0.5
- `triggered_shrinkage`: 0.75
- `max_downward_adjustment_mw`: 900
- `triggered_max_downward_adjustment_mw`: 1200
- `same_day_softening_min_latest_hour`: 10
- `same_day_softening_delta_mw`: -300
- `use_recent_quantile_when_softening`: true

## 적용 범위

이 가드는 하루 전체 잔차 제어기가 아닙니다. 영업일 점심 shape만 다루는 좁은 가드이므로, 13시 이후 회복 구간을 오염시키지 않는 것이 핵심입니다.
