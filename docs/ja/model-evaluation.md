# モデル評価リポート

言語: [English](../en/model-evaluation.md) · [한국어](../ko/model-evaluation.md)

Tokyo Grid EMSでは、予測性能を2つの観点で評価します。

1. **オフラインバックテスト**: 過去データ上でLightGBMが統計ベースラインを改善しているか確認します。
2. **運用比較**: 実際のダッシュボード運用期間で、自社モデルとTEPCO予測のどちらが実績に近かったか確認します。

両方の結果は `web/public/metrics/` に生成され、ダッシュボードの**検証**タブで表示されます。

---

## オフラインバックテスト

出力:

```text
web/public/metrics/model_backtest.json
```

方式:

- `testStart`（既定: `2026-01-01`）より前のデータのみで学習します。
- 各テスト日の予測では、その日より前のキャッシュだけをラグ・ローリング特徴量に使用します。
- ターゲットは時間別実績需要 (`actual_mw`) です。
- 曜日/時間ベースラインとLightGBMを比較します。

主要指標:

| 指標 | 意味 |
|---|---|
| `MAE` | 平均絶対誤差。ダッシュボードで最も直感的な指標です。 |
| `RMSE` | 大きな誤差を強く評価します。ピーク予測ミスに敏感です。 |
| `MAPE` | 実績値に対する相対誤差です。 |
| `improvementPct` | ベースラインに対するLightGBM改善率です。正の値が改善を示します。 |

再現コマンド:

```bash
python python/eval/compare_models.py \
  --cache web/public/.hourly_cache.parquet \
  --out web/public/metrics/model_backtest.json \
  --test-start 2026-01-01
```

---

## TEPCO予測との運用比較

出力:

```text
web/public/metrics/forecast_accuracy.json
```

方式:

- 実績需要、自社モデル予測、TEPCO予測の3つが揃う直近時間だけを比較します。
- それぞれの絶対誤差を計算します。
- サマリー、日別、時間帯別にMAE、WAPE、RMSE、最大誤差リスク、優位時間を集計します。
- `actualSource` が `tepco_forecast_fallback` の行は除外します。
- 全体サマリー(`summary`)には直近の運用モデル系列のみを含めます。
  - 例: 現在の運用モデルがLightGBMの場合、baseline時代の予測日は全体スコアカードから除外します。

主要指標:

| 指標 | 意味 |
|---|---|
| `modelMaeMw`, `tepcoMaeMw` | 平均絶対誤差(MW)。運用者が最も直感的に読める代表指標です。 |
| `modelWapePct`, `tepcoWapePct` | 総実績需要に対する絶対誤差率。日全体の需要規模に対する安定性を見ます。 |
| `modelRmseMw`, `tepcoRmseMw` | 大きな単発誤差を強く反映するリスク指標です。 |
| `modelMaxErrorMw`, `tepcoMaxErrorMw` | 比較期間内の最大単一時間誤差です。 |
| `modelAdvantageHours`, `tepcoAdvantageHours` | 各予測の絶対誤差が相手より小さかった時間数です。既存の `modelWins`, `tepcoWins` と同じ値ですが、UIでは運用用語として「優位時間」と表示します。 |
| `verdict` | MAE、WAPE、RMSEを合わせて見た運用判断です。`model_better`, `tepco_better`, `close`, `mixed`, `insufficient` のいずれかです。 |

注意点:

TEPCO予測は公式の運用予測であり、このプロジェクトでは使えない情報を反映している可能性があります。この比較は「常にTEPCOに勝つ」主張ではなく、どの条件でどちらの予測が実績に近いかを透明に示すための運用スコアカードです。

厳密な学習/評価分離に基づくモデル性能は `model_backtest.json` を主な指標として確認します。

優位時間は補助情報であり、主順位そのものではありません。ダッシュボードでは単純な勝敗表現よりも、WAPEと大きな誤差リスクを優先します。
