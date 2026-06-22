# 모델 개선 이력

운영 예측 모델 개선 전체 기록입니다. 루트 README에는 선별된 최근 변경만 표시하고, 이 문서에는 전체 이력을 최신순으로 보관합니다.

언어: [English](../../en/model-improvements/README.md) / [日本語](../../ja/model-improvements/README.md)

---

## 2026-06

- [2026-06-22 낮 시간 shape 연쇄 가드](model-improvement-2026-06-22-daytime-shape-chain-guards.md)
- [2026-06-21 비영업일 shape와 저녁 carryover](model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md)
- [2026-06-20 비영업일 prior 및 plateau 가드](model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md)
- [2026-06-19 낮 시간 지속 과소예측 리프트](model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md)
- [2026-06-19 밴드 재정렬과 가드 조건 강화](model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md)
- [2026-06-18 새벽 early observed residual carryover](model-improvement-2026-06-18-early-observed-residual-carryover.md)
- [2026-06-16 오전 floor shape 지지와 오후 carryover 감쇠](model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md)
- [2026-06-15 오전 ramp floor 과대예측 veto](model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md)
- [2026-06-14 비영업일 shape 및 residual 가드](model-improvement-2026-06-14-non-business-shape-and-residual-guards.md)
- [2026-06-13 비영업일 analog 및 carryover 가드](model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md)
- [2026-06-12 오전 실측 램프 floor와 밴드 tail 축소](model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md)
- [2026-06-11 습도/불쾌지수 피처와 국소 shape spike 가드](model-improvement-2026-06-11-humidity-discomfort-shape-spike-guard.md)
- [2026-06-09 오후 실측 anchor cap](model-improvement-2026-06-09-afternoon-observed-anchor-cap.md)
- [2026-06-09 오전 실측 앵커 상한 가드](model-improvement-2026-06-09-morning-observed-anchor-cap.md)

- [2026-06-08 영업일 복귀 shape veto](model-improvement-2026-06-08-business-return-shape-veto.md)
- [2026-06-07 actual JSON 캐시 영속화](model-improvement-2026-06-07-actual-cache-persistence.md)
- [2026-06-05 오전 양수 잔차 carryover 감쇠](model-improvement-2026-06-05-morning-positive-carryover-damping.md)

- [2026-06-04 오전 warm-lag 과반응 가드](model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md)
- [2026-06-03 예측 구간 상단 tail 안정화](model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)

## 2026-05

- [2026-05-30 음수 잔차 연속성 floor](model-improvement-2026-05-30-negative-residual-continuity-floor.md)
- [2026-05-29 저녁 레벨 overhang 가드](model-improvement-2026-05-29-evening-level-overhang-guard.md)
- [2026-05-27 저녁 하락 연속성 가드](model-improvement-2026-05-27-evening-decline-continuity-guard.md)
- [2026-05-27 오전 램프 연속성 가드](model-improvement-2026-05-27-morning-ramp-continuity-guard.md)
- [2026-05-27 점심 전환 가드 재활성화](model-improvement-2026-05-27-midday-transition-guard-reenabled.md)

- [2026-05-25 양수 잔차 슬로프 감쇠](model-improvement-2026-05-25-positive-residual-slope-damping.md)

- [2026-05-25 영업일 복귀 anchor 부족분 가드](model-improvement-2026-05-25-business-return-anchor-shortfall.md)
- [2026-05-25 영업일 복귀 lag24 cap 수정](model-improvement-2026-05-25-business-return-lag24-cap.md)
- [2026-05-23 음수 잔차 회복 감쇄](model-improvement-2026-05-23-negative-residual-recovery-damping.md)
- [2026-05-23 비영업일 전환 보정](model-improvement-2026-05-23-non-business-transition-calibration.md)
- [2026-05-22 검증 지표 스코어카드](model-improvement-2026-05-22-validation-metrics-scorecard.md)
- [2026-05-22 운영 보정 레이어](model-improvement-2026-05-22-operational-calibration-layer.md)
- [2026-05-22 하루 단위 lag/날씨 regime 진단](model-improvement-2026-05-22-day-level-regime-diagnostics.md)
- [2026-05-21 영업일 점심 단발성 하락 guard](model-improvement-2026-05-21-midday-shock-guard.md)
- [2026-05-21 예측 밴드 보정](model-improvement-2026-05-21-forecast-band-calibration.md)
- [2026-05-21 공식 JMA 기온과 하이브리드 습도 보완](model-improvement-2026-05-21-official-jma-humidity-correction.md)
- [2026-05-20 오후 기온 방향성 피처](model-improvement-2026-05-20-afternoon-weather-direction-features.md)
- [2026-05-20 점심 시간대 전환 guard](model-improvement-2026-05-20-midday-transition-features.md)
- [2026-05-20 상대 기온과 열 누적 피처](model-improvement-2026-05-20-relative-morning-weather-features.md)
- [2026-05-19 실측 수요 하락 기반 완화](model-improvement-2026-05-19-observed-demand-drop-relaxation.md)
- [2026-05-19 오후 열 관성 및 shape guard](model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md)
- [2026-05-19 예측 스냅샷과 shape 진단](model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md)
- [2026-05-19 운영 intraday 하락 guard](model-improvement-2026-05-19-operational-intraday-drop-guard.md)
- [2026-05-19 기상 bias와 intraday ramp guard](model-improvement-2026-05-19-weather-bias-and-ramp-guards.md)
- [2026-05-18 공식 JMA 기상 예보 입력](model-improvement-2026-05-18-official-jma-weather.md)
- [2026-05-18 lag gap 피처와 관측 기상 보정](model-improvement-2026-05-18-lag-gap-and-observed-weather.md)
- [2026-05-17 intraday 기상 bias 보정과 과거 예측 고정](model-improvement-2026-05-17-intraday-weather-bias-correction.md)
- [2026-05-16 영업/비영업 전환 lag 피처](model-improvement-2026-05-16-business-type-lag-features.md)
- [2026-05-15 24시간 기상 변화량과 체감온도 피처](model-improvement-2026-05-15-24h-weather-apparent-features.md)
- [2026-05-14 lag 기온 regime 피처](model-improvement-2026-05-14-lag-temperature-regime-features.md)
- [2026-05-14 따뜻한 낮 과소예측 보정](model-improvement-2026-05-14-warm-daytime-bias-guard.md)
- [2026-05-13 주간 고온 보호 보정](model-improvement-2026-05-13-daytime-heat-guard.md)
