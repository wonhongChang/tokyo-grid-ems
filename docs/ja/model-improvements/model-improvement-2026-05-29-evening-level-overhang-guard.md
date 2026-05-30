# 2026-05-29 夕方レベル overhang ガード
> ローカルな反発 spike がなくても、夕方下落局面で予測線が高い水準に残り続けるケースを抑える evening decline continuity guard の拡張です。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-29-evening-level-overhang-guard.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-29-evening-level-overhang-guard.md)

---

## 背景

2026-05-29 の確定予測では、夕方時間帯に継続的な過大予測が発生しました。

モデルの日次 MAE は `1106.2 MW`、TEPCO MAE は `755.0 MW` でした。大きな誤差は夕方下落区間に集中しました。

| 時刻 | 実績 MW | モデル MW | モデル誤差 MW | TEPCO誤差 MW |
|---:|---:|---:|---:|---:|
| 15 | 35270 | 37451.7 | +2181.7 | +1040 |
| 16 | 34450 | 36690.0 | +2240.0 | +1170 |
| 17 | 33240 | 35375.0 | +2135.0 | +120 |
| 18 | 32520 | 34571.7 | +2051.7 | +200 |
| 19 | 31620 | 33686.6 | +2066.6 | +590 |

これは 2026-05-27 の夕方 rebound spike とは異なる形でした。2026-05-29 では、予測線が直前値から大きく反発しなくても既に外れていました。当日実績需要が下がっているのに、予測レベル自体が高く残り続けたためです。

## 原因

raw LightGBM 予測線と warm-day 文脈が、夕方まで高需要の慣性を残しすぎました。Intraday residual correction はすでに強い負の補正を適用していましたが、最終serving lineは当日実績の下落経路より上に残りました。

従来の `evening_decline_continuity_guard` は、近い未来予測が `min_forecast_rebound_mw` 以上に反発する場合だけ作動しました。この方式は spike 型の shape risk には有効でしたが、次のような high-level overhang は捕捉できませんでした。

- 当日実績需要が明確に下落中
- 対象が近い未来 bucket
- lag と same-business delta が上昇を支持しない
- 最終予測線が最新実績および same-business anchor 基準より大きく高い

## 変更内容

`evening_decline_continuity_guard` に第2モード `level_overhang` を追加しました。

既存の `rebound` モードはローカルな upward spike を処理します。新しい `level_overhang` モードは、高い水準に残る夕方予測線を処理します。最新実績需要と same-business anchor を基準レベルとし、許容 buffer を超えた部分だけを近い未来 bucket で削ります。

このガードは TEPCO 予測を追従しません。TEPCO 値は事後比較指標としてのみ使用しました。

## 運用パラメータ

追加または調整した設定:

- `min_reference_hour`: 15
- `level_overhang_enabled`: true
- `min_level_overhang_mw`: 500
- `level_overhang_shrinkage`: 0.75

既存の夕方ガード制約も維持します。

- `target_hours`: 16-20
- `max_lead_hours`: 2
- `max_reduction_mw`: 900
- `actual_reference_slack_mw`: 300
- `temp_delta_1h` ベースの weather allowance

これにより介入範囲を近い未来に限定し、保守的に維持します。夕方曲線全体を強制的に下げるのではなく、下落が確認された後のレベル超過分だけを削ります。

## 診断メタデータ

時間別 calibration log で夕方ガードのモードを区別します。

- `eveningDeclineContinuityMode`: `rebound` または `level_overhang`
- `eveningDeclineContinuityCapMw`
- `eveningDeclineContinuityReductionMw`
- `eveningDeclineContinuityWeatherAllowanceMw`

これにより Ops Report は、夕方補正が spike 型反発によるものか、高水準 overhang によるものかを分けて説明できます。

## テスト

2026-05-29 型の level-overhang 回帰テストを追加しました。

- 夕方実績需要が下落中
- 次の予測 bucket がローカル反発していない
- serving line が許容レベル基準より高く残る
- ガードが超過分を削り、metadata に `level_overhang` を記録する
