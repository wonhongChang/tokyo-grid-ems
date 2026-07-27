# モデル昇格ゲートのFail-Closed化

作成日: 2026-07-27 (JST)

## 障害

2026-07-27 07:31 JSTの定期再学習で、`predictionDrift.meanAbsDeltaMw`と`maxAbsDeltaMw`が`NaN`であるにもかかわらず、Challengerが`promoted`と記録されました。Pythonでは`NaN > threshold`がfalseになるためdrift上限を迂回し、非標準JSON tokenも公開されました。

追加監査では次も確認しました。

- timestamp重複により28日検証が672時間ではなく696時間になった
- Challenger学習にtarget dateの部分実績が入り、`trainingCutoff`が2026-07-27になった
- 今日・明日のdriftが実配信と異なるweather/lag cacheで計算された
- lag-24 residual ensembleでlagがない場合にq50が`NaN`になり得た

## 修正

- 昇格学習は`target_date`より前の行だけを使用します。
- 保存済みhourly cacheを再読込し、timestampごとに1行へ正規化して検証します。
- 28日検証は正確に`28 × 24 = 672`時間を要求します。
- driftは実配信と同じweather/lag cacheを使い、今日・明日の48個の有限値を要求します。
- 欠落、`NaN`、無限値が1つでもあれば`prediction_drift_invalid`で昇格を拒否します。
- lag-24がない時間はresidual ensembleではなく独立q50へfallbackします。
- public JSONは`allow_nan=False`でatomic writeし、公開前validatorも非有限tokenを拒否します。
- Challenger artifactは一時pathへ保存・再読込検証してからChampionを置換します。

## 実データ再検証

07:31以前のChampionを隔離worktreeで復元し、同じ運用入力を再実行しました。

| 項目 | 修正前 | 修正後 |
|---|---:|---:|
| 検証時間 | 696 | 672 |
| 有限drift時間 | 一部`NaN` | 48 / 48 |
| 平均絶対drift | `NaN` | 1,104.4 MW |
| 最大絶対drift | `NaN` | 4,763.6 MW |
| 最終判断 | 誤った昇格 | 拒否 |

設定上限は平均900MW、時間最大2,500MWです。修正後のゲートは`mean_prediction_drift_exceeded`と`hour_prediction_drift_exceeded`を記録し、以前のChampionを維持しました。

## 検証

- 全test: 480件通過
- 実データ28日temporal validation: 672時間
- 実配信相当の今日・明日drift: 48個の有限値
- public artifact validation通過

## 運用原則

非有限値と不完全なvalidation coverageはwarningではなく昇格拒否条件です。見かけ上のモデル品質で昇格契約を迂回しません。
