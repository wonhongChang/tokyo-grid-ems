# 2026-06-16 朝floorのshape支持と午後carryover減衰

Languages: [English](../../en/model-improvements/model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-16-morning-floor-shape-support-and-afternoon-carryover.md)

## 問題

2026-06-16の配信チャートでは、別々の2つの制御問題が見えました。

- 10時付近では、`morning_observed_anchor_cap` が小さな負の残差に強く反応しすぎ、公開予測線を後続の再計算線より低く押し下げました。
- 11時付近では、`morning_observed_ramp_floor` が当日の実績ランプを強く見て近未来バケットを過度に持ち上げました。一方で、その対象時刻の `lag_24h_hourly_delta` と `recent_same_business_type_delta_mean` はそこまで大きな上昇を支持していませんでした。
- 午後は12-14時に積み上がった正の intraday 残差が15-19時へ持ち越され、対象時刻の lag/recent shape 支持が弱い、または負の区間でも上方向の圧力が残りました。

10-11時の最終再計算 raw/pre-calibration 線は、公開済みの固定線より実績に近い状態でした。したがって今回の問題は LightGBM の raw 曲線だけではなく、制御レイヤー間の衝突と予測線固定ポリシーの組み合わせと判断しました。

## 変更

- `morning_observed_anchor_cap.min_latest_overforecast_mw` を `200 MW` から `500 MW` に引き上げました。
  - 小さな最新残差だけでは、朝の anchor cap が近未来を大きく削れないようにしました。
- `morning_observed_ramp_floor` に `max_floor_delta_over_support_mw` を追加しました。
  - 実績の朝ランプが強い場合、floor は引き続き動作します。
  - ただし floor が使う時間あたり上昇幅は、対象時刻の `lag_24h_hourly_delta` / `recent_same_business_type_delta_mean` の支持値に小さな余裕を足した範囲で制限します。
  - これにより、11時が直近の観測 slope だけを追って過度に跳ねることを抑えます。
- `afternoon_positive_residual_carryover_damping` を追加しました。
  - 正の residual carryover だけを減衰します。
  - 運用設定では営業日のみに限定し、非営業日夕方専用ガードと二重に減衰しないようにしました。
  - base adjustment が正で、15-19時の対象時刻の lag/recent shape 支持が弱い場合のみ動作します。
  - raw モデルを直接 cap せず、TEPCO 予測も補正ターゲットとして使いません。

## 期待効果

2026-06-16のパターンでは、次を期待します。

- 10時は小さな残差によって早すぎる下方向 cap を受けるリスクが下がります。
- 11時は当日のランプ実績を反映しつつ、対象時刻の shape 支持を超えた過剰な持ち上げを抑えます。
- 15-19時は、午後/夕方の shape 支持が弱いときに、前の時間帯の正の残差がそのまま乗る現象を減らします。

今回の変更は保守的です。制御レイヤーが作った sawtooth を減らすことが目的であり、すべての日中 raw モデル誤差を解消したとは見ていません。

## 検証

```text
tests/test_intraday_correction.py::test_intraday_correction_caps_observed_morning_ramp_floor_by_target_shape_support
tests/test_intraday_correction.py::test_intraday_damps_afternoon_positive_carryover_when_shape_support_is_weak

Full suite: 398 passed
```
