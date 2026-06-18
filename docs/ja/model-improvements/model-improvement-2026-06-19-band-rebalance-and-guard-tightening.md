# 2026-06-19 バンド再配分とガード条件の引き締め

言語: [English](../../en/model-improvements/model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-19-band-rebalance-and-guard-tightening.md)

## 問題

2026-06-19 の朝予測で、2つの運用上の問題が見えた。

- 09:00-11:00 の p95 バンドが大きく片側に偏っていた。たとえば 09:00 と 10:00 は q50 に対しておよそ `-2250 / +500 MW` で、画面上ではバンドが中央予測を自然に包んでいなかった。
- 2026-06-18 10:00 の serving snapshot では、`morning_observed_ramp_floor` が positive residual carryover の上に過剰な lift を重ねていた。
- 2026-06-18 午後の snapshot では、当日実績がすでに回復しているにもかかわらず、`afternoon_observed_anchor_cap` が 14:00-16:00 を強く抑えすぎていた。

## 変更

- 極端な p95 非対称を再配分するオプションを追加した。p95 の総幅は維持しつつ、片側 tail が小さくなりすぎた場合に下側/上側 half-width を再配分する。
- `morning_positive_residual_carryover_damping.weak_support_delta_mw` を引き上げ、10:00-13:00 の target slot で lag/recent shape support が弱い場合に positive carryover をより保守的に減衰させる。
- `morning_observed_ramp_floor.max_floor_delta_over_support_mw` を `0` に下げ、floor が target-hour の lag/recent shape support を超えて持ち上げないようにした。
- `afternoon_observed_anchor_cap.max_latest_slope_mw` を追加し、直近の当日実績が強く回復している場合は cap を適用しないようにした。

## 期待効果

バンド再配分は中央予測(q50)を変更しない。後処理で q50 が動いた場合や quantile の片側 tail が崩れた場合でも、ダッシュボード上のバンドが不自然に片寄って見える問題を抑える。

朝の ramp 保護は維持するが、target slot の lag/recent shape 根拠が弱い場合は過剰に持ち上げない。午後の plateau cap も維持するが、明確な当日回復 slope と衝突しないようにした。

## 検証

```text
tests/test_run_batch.py::test_build_forecast_json_rebalances_extreme_one_sided_band
tests/test_intraday_correction.py::test_intraday_damps_morning_positive_carryover_before_ramp_floor_lift
tests/test_intraday_correction.py::test_intraday_afternoon_observed_anchor_cap_skips_when_actuals_are_recovering

Full suite: 402 passed
```
