# 2026-05-27 昼休み遷移ガード再有効化
> 12時の昼休み dip を保守的に反映するため、営業日の lunch-shape ガードを再度有効にしました。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-27-midday-transition-guard-reenabled.md)

---

## 背景

最近の営業日ライブ予測では、直近の同一営業日タイプの履歴が昼休み時間帯の低下を示しているにもかかわらず、モデル予測線が12時 bucket を滑らかに保ちすぎるケースがありました。

昼休み dip は午後全体のトレンドではなく、ほぼ単一時間帯の shape 効果です。そのため、intraday residual の傾きを午後へ押し流して解決すべきではなく、TEPCO 予測を追従すべきでもありません。より安全な補正は、昼休み bucket だけで同一営業日タイプの shape context とモデル予測を比較する狭いガードです。

## 変更内容

adjustment レイヤーの `midday_transition_guard` を再度有効にしました。

このガードは設定された昼休み時刻だけで動作します。直近の同一営業日タイプ context が十分に負の昼休み遷移を示し、モデル予測が shape 基準より設定 allowance 以上高い場合に限り、一部の下方調整を適用します。

## 運用パラメータ

デフォルト設定:

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

## 適用範囲

このガードは一日全体の残差制御器ではありません。営業日の昼休み shape だけを扱う狭いガードであり、13時以降の回復区間を汚染しないことが重要です。
