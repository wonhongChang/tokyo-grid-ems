# 2026-05-21 気象庁公式予報と湿度ベース体感温度補正

> Open-Meteo JMAを運用予報fallbackから外し、気象庁AMeDASの公式湿度観測を短期の体感温度補正に使う改善メモ。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md)

---

## なぜ必要だったか

最近のintraday予測では、モデルが当日の体感よりも涼しい気象条件として解釈するケースがあった。気象庁公式予報は気温ガイダンスを提供するが、時間別湿度は提供しない。Open-Meteo JMAは体感温度や湿度系の信号を提供できるが、東京の時間別予報が気象庁公式の見立てとずれる場合があり、運用fallbackとしての信頼性に課題があった。

運用予測モデルでは、すべての派生項目を埋めることよりも、入力ソースの一貫性が重要である。将来気温カーブは一つのソース、体感温度だけ別ソースという形にすると、モデルに混ざった信号を渡す可能性がある。

---

## 変更内容

将来予報の気象入力は、気象庁公式の東京time-series endpointのみを使う。

```text
https://www.jma.go.jp/bosai/jmatile/data/wdist/VPFD/130010.json
```

`fetch_forecast_temps()` はOpen-Meteo JMAを呼び出さない。気象庁公式予報が取得できない場合は、信頼度の低いソースへ静かに切り替えるのではなく、エラーとして表面化させる。

直近の観測気象は、引き続き気象庁AMeDAS東京地点を使う。パーサーは以下を保持する。

- `humidity_pct`
- `discomfort_index`
- 公式観測の気温、湿度、風速から推定した湿度反映の体感温度

気象庁公式予報には時間別湿度がないため、湿度をLightGBMの直接特徴量にはまだ追加しない。その代わり、intraday気象bias補正で、直近観測の湿度により体感温度が予報入力より高い/低い場合、近い将来の `apparent_temp_c` を補正できるようにした。

---

## 期待される効果

気象庁公式の気温カーブにOpen-Meteo JMAの体感温度信号が混ざることを避けられる。

湿度の高い朝には、最新のAMeDAS観測が近い将来の体感温度を引き上げられる。ただし、翌日の湿度を生成するものではなく、当日短期運用の補正に限定する。

---

## 運用メモ

- 古いキャッシュ欠損を埋める過去backfillでは、Open-Meteo archiveが残る場合がある。
- 運用向けの将来予報入力ではOpen-Meteo JMA fallbackを使わない。
- 気象庁公式予報rowの `humidity_pct` と `discomfort_index` は、AMeDAS観測が入るまで `NaN` である。
- この変更は気象ソース信頼性と補正方法の変更であり、TEPCO需要データや予備率リスク基準は変更しない。

---

## テスト

追加/更新したテストは以下を確認する。

- `fetch_forecast_temps()` がOpen-Meteo JMA fallbackを呼び出さないこと。
- 気象庁公式予報の失敗がエラーとして表面化すること。
- AMeDAS湿度と不快指数をパースすること。
- 実気温biasがthreshold未満でも、体感温度biasが大きい場合はintraday補正が適用されること。
