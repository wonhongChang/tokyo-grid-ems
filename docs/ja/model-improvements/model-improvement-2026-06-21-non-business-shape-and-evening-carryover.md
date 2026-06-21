# 2026-06-21 非営業日の shape と夕方 carryover

言語: [English](../../en/model-improvements/model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-21-non-business-shape-and-evening-carryover.md)

## 問題

2026-06-21 日曜日の配信予測は、一つの residual loop だけの失敗ではなく、時間帯ごとに異なる問題が混在したケースだった。

- 朝: 06:00 は約 `1.37 GW` の過小予測だった。`lag_24h_hourly_delta` と `recent_same_business_type_delta_mean` は横ばい、または緩やかな低下しか示していなかったが、予測線は 05:00 から 06:00 にかけて過度に落ち込んだ。
- 午後: 14:00-15:00 は過小予測だった。raw LightGBM の水準は比較的近かったが、`analog_adjusted` が非営業日の午後を過度に下げた。既存の非営業日 analog downshift guard は 13:00 までだったため、午後 plateau を保護できなかった。
- 夕方: 18:00-19:00 はやや高めだった。17:01 の実行で 14:00-16:00 の過小予測 residual が夕方へ carryover されたが、non-business evening damping の発動しきい値がやや高く作動しなかった。

TEPCO 予測は分析用の外部比較としてのみ使用した。補正入力には使っていない。

## 変更

- `PostHolidayTimeBandGuard` に `non_business_morning_shape_floor_guard` を追加した。
  - 非営業日の朝の遷移バケットだけで作動する。
  - forecast slope が lag-24h および最近の同一営業形態 slope の支えと矛盾しているかを見る。
  - 根拠のない急落だけを shrinkage と lift cap の範囲で緩和する。
- `non_business_analog_downshift_guard` の範囲を 07:00-13:00 から 07:00-15:00 に拡張した。
  - raw 需要が最近の非営業日 anchor 近辺にある場合、午後 plateau を analog の下方 shift で消さないようにする。
  - anchor が plateau を支えない下降型の午後では、従来どおり analog の下方 shift を維持できる。
- `non_business_evening_positive_residual_damping.min_base_adjustment_mw` を `500 MW` から `350 MW` に下げた。
  - 午後の過小予測 residual が極端でなくても、夕方 carryover のブレーキが入るようにした。
- AI 運用レポートの feature catalog に新しいガード名を追加した。

## リスク制御

- 朝のガードは 06:00 の値を固定しない。最近の非営業日 shape 根拠と合わない深い trough だけを制限する。
- 午後 analog guard は、raw 予測が非営業日 anchor より十分高い場合や lag/recent delta が下落を支える場合、下方 shift をそのまま許容する。
- 夕方の変更は正の residual carryover だけを減衰する。raw model 自体を直接下げるわけではない。

## 検証

```text
tests/test_adjustment.py::test_guard_lifts_non_business_morning_shape_floor_when_drop_is_unsupported
tests/test_adjustment.py::test_guard_caps_non_business_afternoon_analog_downshift_when_anchor_supports_plateau
tests/test_adjustment.py::test_guard_keeps_non_business_analog_downshift_without_shape_support
tests/test_intraday_correction.py::test_intraday_damps_non_business_evening_positive_carryover_when_shape_is_weak
```
