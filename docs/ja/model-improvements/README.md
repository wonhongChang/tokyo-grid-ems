# モデル改善ログ

運用予測モデルの改善履歴です。ルート README には選択した最近の変更だけを表示し、この文書では全履歴を新しい順に保持します。

Languages: [English](../../en/model-improvements/README.md) / [한국어](../../ko/model-improvements/README.md)

---

## 2026-06

- [2026-06-22 日中 shape 連鎖ガード](model-improvement-2026-06-22-daytime-shape-chain-guards.md)
- [2026-06-21 非営業日の shape と夕方 carryover](model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md)
- [2026-06-20 非営業日の prior と plateau ガード](model-improvement-2026-06-20-non-business-prior-and-plateau-guards.md)
- [2026-06-19 昼間の継続的な過小予測リフト](model-improvement-2026-06-19-daytime-sustained-underforecast-lift.md)
- [2026-06-19 バンド再配分とガード条件の引き締め](model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md)
- [2026-06-18 早朝early observed residual carryover](model-improvement-2026-06-18-early-observed-residual-carryover.md)
- [2026-06-16 朝floorのshape支持と午後carryover減衰](model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md)
- [2026-06-15 朝ramp floor過大予測veto](model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md)
- [2026-06-14 非営業日のshapeおよびresidualガード](model-improvement-2026-06-14-non-business-shape-and-residual-guards.md)
- [2026-06-13 非営業日のanalogおよびcarryoverガード](model-improvement-2026-06-13-non-business-analog-and-carryover-guards.md)
- [2026-06-12 朝の実績ランプ floor と予測バンド tail 縮小](model-improvement-2026-06-12-morning-ramp-floor-and-band-tail-tightening.md)
- [2026-06-11 湿度/不快指数特徴量と局所shape spikeガード](model-improvement-2026-06-11-humidity-discomfort-shape-spike-guard.md)
- [2026-06-09 午後実績 anchor cap](model-improvement-2026-06-09-afternoon-observed-anchor-cap.md)
- [2026-06-09 午前の実績アンカー上限制御](model-improvement-2026-06-09-morning-observed-anchor-cap.md)

- [2026-06-08 営業日復帰 shape veto](model-improvement-2026-06-08-business-return-shape-veto.md)
- [2026-06-07 actual JSON キャッシュ永続化](model-improvement-2026-06-07-actual-cache-persistence.md)
- [2026-06-05 朝の正の残差 carryover 減衰](model-improvement-2026-06-05-morning-positive-carryover-damping.md)

- [2026-06-04 朝の warm-lag 過反応ガード](model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md)
- [2026-06-03 予測区間の上側 tail 安定化](model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)

## 2026-05

- [2026-05-30 負の残差連続性 floor](model-improvement-2026-05-30-negative-residual-continuity-floor.md)
- [2026-05-29 夕方レベル overhang ガード](model-improvement-2026-05-29-evening-level-overhang-guard.md)
- [2026-05-27 夕方下落継続ガード](model-improvement-2026-05-27-evening-decline-continuity-guard.md)
- [2026-05-27 朝ランプ継続ガード](model-improvement-2026-05-27-morning-ramp-continuity-guard.md)
- [2026-05-27 昼休み遷移ガード再有効化](model-improvement-2026-05-27-midday-transition-guard-reenabled.md)

- [2026-05-25 正の残差スロープ減衰](model-improvement-2026-05-25-positive-residual-slope-damping.md)

- [2026-05-25 営業日復帰 anchor 不足分 guard](model-improvement-2026-05-25-business-return-anchor-shortfall.md)
- [2026-05-25 営業日復帰 lag24 cap 修正](model-improvement-2026-05-25-business-return-lag24-cap.md)
- [2026-05-23 負の残差回復ダンピング](model-improvement-2026-05-23-negative-residual-recovery-damping.md)
- [2026-05-23 非営業日遷移補正](model-improvement-2026-05-23-non-business-transition-calibration.md)
- [2026-05-22 検証指標スコアカード](model-improvement-2026-05-22-validation-metrics-scorecard.md)
- [2026-05-22 運用補正レイヤー](model-improvement-2026-05-22-operational-calibration-layer.md)
- [2026-05-22 日単位lag/天気regime診断](model-improvement-2026-05-22-day-level-regime-diagnostics.md)
- [2026-05-21 営業日の昼休み単発ショック guard](model-improvement-2026-05-21-midday-shock-guard.md)
- [2026-05-21 予測バンド補正](model-improvement-2026-05-21-forecast-band-calibration.md)
- [2026-05-21 公式JMA気温とハイブリッド湿度補完](model-improvement-2026-05-21-official-jma-humidity-correction.md)
- [2026-05-20 午後の気温方向性特徴量](model-improvement-2026-05-20-afternoon-weather-direction-features.md)
- [2026-05-20 昼時間帯の遷移 guard](model-improvement-2026-05-20-midday-transition-features.md)
- [2026-05-20 相対気温と熱蓄積特徴量](model-improvement-2026-05-20-relative-morning-weather-features.md)
- [2026-05-19 実測需要低下に基づく緩和](model-improvement-2026-05-19-observed-demand-drop-relaxation.md)
- [2026-05-19 午後の熱慣性と shape guard](model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md)
- [2026-05-19 予測スナップショットと shape 診断](model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md)
- [2026-05-19 運用 intraday 低下 guard](model-improvement-2026-05-19-operational-intraday-drop-guard.md)
- [2026-05-19 気象 bias と intraday ramp guard](model-improvement-2026-05-19-weather-bias-and-ramp-guards.md)
- [2026-05-18 公式JMA気象予報入力](model-improvement-2026-05-18-official-jma-weather.md)
- [2026-05-18 lag gap 特徴量と観測気象補正](model-improvement-2026-05-18-lag-gap-and-observed-weather.md)
- [2026-05-17 intraday 気象 bias 補正と過去予測固定](model-improvement-2026-05-17-intraday-weather-bias-correction.md)
- [2026-05-16 営業/非営業遷移 lag 特徴量](model-improvement-2026-05-16-business-type-lag-features.md)
- [2026-05-15 24時間気象変化量と体感温度特徴量](model-improvement-2026-05-15-24h-weather-apparent-features.md)
- [2026-05-14 lag 気温 regime 特徴量](model-improvement-2026-05-14-lag-temperature-regime-features.md)
- [2026-05-14 暖かい昼間の過小予測補正](model-improvement-2026-05-14-warm-daytime-bias-guard.md)
- [2026-05-13 昼間高温 guard 改善](model-improvement-2026-05-13-daytime-heat-guard.md)
