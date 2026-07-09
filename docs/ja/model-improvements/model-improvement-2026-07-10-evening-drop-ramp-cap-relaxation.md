# 2026-07-10 夕方下落局面の ramp cap 緩和

言語: [English](../../en/model-improvements/model-improvement-2026-07-10-evening-drop-ramp-cap-relaxation.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-10-evening-drop-ramp-cap-relaxation.md)

## 背景

2026-07-09 の予測では、夕方後半の shape に明確な問題が出た。13:00-16:00 はおおむね許容範囲だったが、21:00 は当日実績がすでに下落していたにもかかわらず高く残った。

重要なのは、既存の下落防御が無かったわけではない点である。20:22 JST の運用補正スナップショットでは、すでに以下が適用されていた。

- `afternoon_positive_residual_carryover_damping`
- `evening_decline_continuity_guard`

21:00 の pre-calibration 予測はすでに低めの夕方パスに近く、evening decline guard もさらに引き下げていた。しかし最後の `ramp_guard` が直近実績を基準に近距離の下限を強く適用し、配信予測線を再び持ち上げた。つまり、下落ガードは機能していたが、最終 ramp cap が下落幅を過度に制限した構造だった。

## 変更内容

既存の observed-drop relaxation 経路に `ramp_guard.observed_drop_relaxation.decline_support` を追加した。

このルールは予測を直接下げるものではない。以下をすべて満たす場合に限り、ramp guard の drop cap を少し広げる。

- 実績需要がすでに速く下落しており、`observed_drop_relaxation` が有効
- 予測 lead time が 2 時間以上
- 営業日
- 対象時間の shape 信号がどちらも強い下落を支持
  - `lag_24h_hourly_delta`
  - `recent_same_business_type_delta_mean`

標準の運用設定:

| Config key | 値 |
| --- | ---: |
| `enabled` | `true` |
| `business_day_only` | `true` |
| `min_lead_hours` | `2` |
| `max_support_delta_mw` | `-1000` |
| `max_decrease_mw_by_lead_hour` | `[1600, 4000, 5600]` |

## 期待効果

夕方の実績がすでに下落しており、対象時間の lag/recent shape も下向きを示す場合、最後の ramp guard が予測線を直近実績水準へ過度に戻す問題を抑える。

保守性は維持している。

- lead-1 予測は従来の近距離 cap を維持
- 非営業日には適用しない
- lag と recent same-business shape の両方が下落を支持する必要がある
- TEPCO 予測値は入力特徴量として使用しない

## 観測性

運用補正メタデータに以下を追加した。

- `rampGuardDeclineSupportRelaxationApplied`
- `rampGuardDeclineSupportRelaxationMaxExtraDropMw`

AI 運用レポートの fact packet にも同じ制御フラグを渡す。これにより、今後のレポートで「下落ガードが無効だった」のか、「下落ガードは有効だったが最後の ramp cap が配信線を制限した」のかを区別できる。

## 検証

- `python -m pytest tests/test_intraday_correction.py -k "ramp_guard_relaxes_drop_cap or ramp_guard_keeps_drop_cap or observed_demand_drop"`

結果:

- `3 passed`

## メモ

これは 21:00 専用のハードコードではない。実績需要がすでに下落し、独立した lag/recent shape 信号が強い夕方下落を支持する場合だけ、最終 cap を緩和する後処理の安全装置である。
