# 非営業日レジーム q50 アンサンブル

作成日: 2026-07-31 (JST)

## 背景

7月28日から31日までの運用予測には、単一方向のbiasでは説明できない誤差がありました。7月30日は日中の過小予測が続き、7月31日は時間ごとに誤差の符号が変わってshapeが不安定でした。そのため、新しい一律の上方・下方guardではなく、q50が営業日と非営業日を一つのモデルで扱う構造を先に検証しました。

直近30日の配信予測ではモデルMAEが643.9 MW、TEPCO参考MAEが366.0 MWでした。7月3日から30日までの運用replayではserved MAEが639.4 MW、shape delta MAEが560.5 MWでした。TEPCO予測は外部比較にのみ使用し、特徴量や補正targetには使用しません。

## 原因分析

- 従来の絶対需要q50は営業日と非営業日を一つのモデルで学習していました。
- `humidity_delta_24h`、`discomfort_delta_24h`と二つの朝interactionは最近の重要度が高い一方、週末境界でのsource変更や補完値によってq50 shapeを不安定にする可能性がありました。
- 4特徴量を全q50経路から除外すると一部の平均誤差は減りましたが、営業日の最大誤差と日中riskが増加しました。
- 非営業日専用q50へ100%置換する方式も、blendより安定しませんでした。
- 営業タイプ遷移時にlag-24残差アンサンブルを完全に止める案は、28日検証で悪化したため採用しませんでした。

## 変更内容

interval contractを`q025_q50_q975_p95_v12_regime_q50`へ更新しました。

- q025、q975、統合q50、lag-24残差q50は従来の63特徴量を維持します。
- 非営業日専用q50を別に学習します。
- 専用モデルだけ次の4つのsource-sensitive deltaを除外します。
  - `humidity_delta_24h`
  - `discomfort_delta_24h`
  - `business_morning_x_humidity_delta_24h`
  - `business_morning_x_discomfort_delta_24h`
- 土曜、日曜、祝日の中心線は統合q50と非営業日q50を50:50で合成します。
- interval modelと営業日q50経路は変更しません。
- v11 Championとのload互換性を維持し、昇格拒否時にbaselineへ落ちないようにします。

## 28日時間順検証

検証期間は2026-07-03から2026-07-30までの672時間です。両contractは同じ学習cutoffと最終観測気象contextを使用しました。

| 指標 | 従来contract | v12 Challenger | 変化 |
|---|---:|---:|---:|
| 全体MAE | 951.7 MW | 931.7 MW | -2.1% |
| 全体WAPE | 2.700% | 2.644% | -0.056%p |
| 全体RMSE | 1,292.5 MW | 1,267.9 MW | -1.9% |
| Shape delta MAE | 574.9 MW | 547.2 MW | -4.8% |
| 最大誤差 | 4,873.4 MW | 4,873.4 MW | 同一 |
| 営業日MAE | 975.8 MW | 975.8 MW | 同一 |
| 非営業日MAE | 900.8 MW | 838.5 MW | -6.9% |
| 朝MAE | 965.9 MW | 921.7 MW | -4.6% |
| 夜MAE | 973.6 MW | 944.1 MW | -3.0% |

候補は絶対MAE、WAPE、shape、最大誤差、全segment上限を通過しました。seasonal baselineに対するMAE改善率は73.21%でした。

### 予測バンド

同じfrozen-origin検証でp95 coverageは従来84.4%、候補84.2%となり、改善しませんでした。朝は89.3%から90.0%、遅い午後は83.3%から84.5%、夜は88.6%から90.0%へ改善しましたが、日中は72.9%から72.1%へ少し低下しました。

一方、実際のserved replayでは直近28日の全体coverageが96.1%、朝と日中が各92.9%、夜が99.3%です。q50レジーム精度とinterval calibrationは別の問題です。一律に幅を広げると、すでに広い夜間bandをさらに過大にするため、今回band設定は変更しませんでした。

## 8月1日の週末遷移確認

8月1日の入力気象は最高37.0°Cで、夜まで高温が続きます。v12 shadow q50は08時36.84 GW、12時46.07 GW、16時46.40 GW、19時44.82 GW、22時38.17 GWです。v11にあった17時と19時の深い谷を減らし、過去の高温週末に近いshapeになりました。

これはTEPCO予測を追従した値ではなく、昇格済みの公開予測でもありません。

## 昇格状態

現行v11 Championに対する今日・明日48時間のdriftは平均943.1 MW、最大3,579.7 MWでした。運用上限の平均900 MW、時間最大2,500 MWを超えるため、強制昇格しません。

この変更は検証済みChallenger contractとして準備されますが、prediction drift gateも通過するまでは現行Championを維持します。1日の予測を修正するためにgateを緩和したり、model artifactを手動置換したりしません。

## 検証

- LightGBMおよび昇格unit test 43件通過
- Python全体test 486件通過
- temporal holdout 672/672時間
- Challenger絶対品質gate: 通過
- Champion対比prediction drift gate: 拒否
