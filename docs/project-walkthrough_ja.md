# 学生向けプロジェクト全体ガイド

言語: [English](project-walkthrough.md) · [한국어](project-walkthrough_ko.md)

この文書は、プログラミングやデータパイプラインを学ぶ学生がTokyo Grid EMSの全体像を理解できるように説明するものです。

---

## このプロジェクトは何をするのか

Tokyo Grid EMSは、TEPCOが公開する電力需要CSVを取得し、Webダッシュボードとして表示するプロジェクトです。

ダッシュボードは次の質問に答えます。

1. 昨日の電力使用量はどうだったか。
2. 異常イベントはあったか。
3. 今日と明日の電力需要はどう予測されるか。
4. 自分のモデルはTEPCO公式予測と比べてどの程度合っているか。

---

## 全体の流れ

```text
TEPCO CSV
  -> Python ETL
  -> 整理済み時間別データ
  -> 予測モデル
  -> 異常検知
  -> JSONファイル
  -> GitHub Pages上のReactダッシュボード
```

常時稼働するバックエンドサーバーはありません。GitHub Actionsが決まった時刻にPython処理を実行し、結果JSONを保存して、GitHub Pagesが静的ダッシュボードを配信します。

---

## TEPCOデータは2種類ある

| データ | 更新タイミング | プロジェクトでの使い方 |
|---|---|---|
| 月次ZIP | 朝JSTごろ、確定履歴データを含む | メインETLソース |
| Intraday CSV | 当日中に更新 | 月次ZIPが追いつく前の当日実績を補完 |

そのためworkflowも2つあります。

- `ETL + Deploy`: 確定データ処理とモデル学習
- `Intraday Update`: 当日データ、予測、statusの更新

---

## 主なフォルダ

```text
python/
  etl/                 データ取得、パース、cache、JSON生成
  forecast/            baseline、LightGBM、特徴量生成、intraday補正
  anomaly/             異常検知ルール
  eval/                バックテストとTEPCO比較

web/
  src/                 Reactダッシュボード
  public/              workflow実行中に生成されるJSON

docs/                  プロジェクト文書
tests/                 自動テスト
```

読む順番は次がおすすめです。

1. `python/etl/fetch_tepco.py`
2. `python/tepc_parser.py`
3. `python/etl/run_batch.py`
4. `python/forecast/feature_builder.py`
5. `python/forecast/lgbm_model.py`
6. `python/anomaly/detector.py`
7. `web/src/App.tsx`
8. `web/src/components/ForecastChart.tsx`
9. `web/src/components/ValidationPanel.tsx`

---

## このプロジェクトでのETL

ETLは次の3段階です。

- Extract: TEPCO CSVやZIPをダウンロードする。
- Transform: 日本語CSVテーブルを解析し、単位変換、タイムゾーン付与、気温データ結合を行う。
- Load: ダッシュボードがそのまま読めるJSONを作る。

代表的な出力:

```text
status.json
actual/YYYY-MM-DD.json
forecast/YYYY-MM-DD.json
alerts/YYYY-MM-DD.json
metrics/forecast_accuracy.json
metrics/model_backtest.json
```

Reactアプリは予測を直接計算しません。生成済みJSONを読み込み、表示します。

---

## cacheが必要な理由

予測には過去データが必要です。毎回すべてのCSVを読み直すと遅いため、ETLは時間別cacheを保持します。

```text
web/public/.hourly_cache.parquet
```

このcacheには時間別実績、TEPCO予測、供給力、使用率、気温が入ります。生成データは`main`にはコミットせず、GitHub Actionsが`data`ブランチに保存します。

---

## 予測モデルを簡単に言うと

モデルは次を予測します。

> "明日の各時間の電力需要はいくらになりそうか。"

使うヒント:

- 昨日の同じ時間
- 先週の同じ時間
- 曜日と祝日
- 直近4週の平均
- 気温
- ラグ値が連休によって低くなっていないか

LightGBMはこれらのヒントからパターンを学習します。問題が起きた場合はbaselineモデルに戻れます。

---

## Intraday補正

当日の実績が増えると、モデルは自分の予測と実績を比較できます。実績が予測より継続的に高ければ残り時間の予測を上げ、低ければ下げます。

23:40 JST時点でも23:00実績がない場合、TEPCO予測値を一時的に使い、次のように印を付けます。

```json
{
  "actualSource": "tepco_forecast_fallback"
}
```

この値は次の予測入力には使えますが、モデルスコア計算や異常検知の実績判定には使いません。

---

## 異常検知

| イベント | 意味 |
|---|---|
| Reserve Risk | 使用率が高く、供給余力が小さい |
| Spike / Drop | 実績需要が予測バンドから外れた |
| Drift | モデルが数時間連続で同じ方向に外れている |

"モデルが外れた"ことと"電力需給が危険"なことを分けて扱うのが重要です。

---

## 検証

| レポート | 目的 |
|---|---|
| Model backtest | 過去データでLightGBMがbaselineより良いか確認 |
| Forecast accuracy | 運用中に自社モデルとTEPCO予測のどちらが実績に近いか比較 |

TEPCO予測は強い公式基準線です。このプロジェクトの目的は常にTEPCOに勝つことではなく、公開データだけで作ったモデルの性能を透明に示すことです。

---

## このプロジェクトから学べること

- スケジュール実行されるデータパイプライン
- 実データの更新遅延とタイムゾーン問題
- ソースコードと生成データの分離
- バックエンドなしの静的ダッシュボード運用
- モデルを公平に評価する方法
- モデルの限界を文書化する方法
