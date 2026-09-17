# モデル評価リポート

言語: [English](../en/model-evaluation.md) · [한국어](../ko/model-evaluation.md)

Tokyo Grid EMSでは、予測性能を3つの観点で評価します。

1. **オフラインバックテスト**: 過去データ上でLightGBMが統計ベースラインを改善しているか確認します。
2. **運用比較**: 実際のダッシュボード運用期間で、自社モデルとTEPCO予測のどちらが実績に近かったか確認します。
3. **同時取得ベンチマーク**: 同一実行で取得した自モデルとTEPCO予測を同じlead区間で比較します。元の発表時刻が同一という意味ではありません。

3つの結果はすべて`web/public/metrics/`に生成されます。**検証**タブは`事前予測比較`を初期表示とし、既存の運用比較は`最新公開値の参考`に分離します。オフラインバックテストは別領域に維持します。標本の表示はモデル昇格やTEPCO同等判定の承認ではありません。

## 画面の読み方

- 事前比較はJSONの観測日窓(現在28/84日)とlead区間(0-2/2-4/4-8/8-24時間)を選択し、実際の期間・比較標本・MAE/WAPEを表示します。詳細表にはRMSEと最大誤差も示します。
- `capturedAt`は収集時刻で、元の発表時刻ではありません。下限超・上限以下の各区間内で、対象時刻ごとに最小の正のleadを選びます。区間間で同一対象時間が重複し得るため、標本数を合算して一意な時間数とは呼びません。
- モデルバージョン・補正方針別の分離集計はありません。選択期間の運用履歴全体であり、現在モデルだけの成績ではありません。
- `qualification.failures`の日数・時間・時間帯の不足を対象窓/区間の`標本範囲不足`として表示します。性能基準未達とは区別し、`比較可能`は昇格・同等性基準合格を意味しません。
- 最新公開値の参考はJSON全体の集計窓、直近14日付のMAE/WAPEグラフ、直近10日付の詳細表をそれぞれ実日付範囲付きで表示します。24時間未満は過去欠損も含め`部分集計`です。
- ツールチップは正確なMW、モデル−TEPCOのMAE差、両WAPE、標本数を示します。WAPEは同一標本のバックエンド算出値を使用し、日別率の単純平均や`100 - WAPE`の精度表示は行いません。
- ファイル欠損・通信エラー・未対応契約は明示し、別比較やオフライン結果へ自動代替しません。
- 検証値は万kWで小数1桁、GWで小数3桁まで、詳細MWは小数1桁まで表示します。他のグラフ・単位方針は維持します。

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

TEPCO予測は公式の運用予測であり、このプロジェクトでは使えない情報を反映している可能性があります。また経過時間の値も修正されるため、`forecast_accuracy.json`は`latest_published_value_reference`運用参考値であり、正式なparity判定には使用しません。

厳密な学習/評価分離に基づくモデル性能は `model_backtest.json` を主な指標として確認します。

優位時間は補助情報であり、主順位そのものではありません。ダッシュボードでは単純な勝敗表現よりも、WAPEと大きな誤差リスクを優先します。

---

## 同一vintage TEPCO Benchmark

出力:

```text
web/public/metrics/forecast_vintage_accuracy.json
```

- 各ETL/Intraday実行で、未来時間のモデル/TEPCO値を同時に`reports/internal/forecast-vintages/`へ保存します。
- 後のTEPCO修正値は過去captureを上書きできません。
- TEPCOが不変の発行時刻を提供しないため、プロジェクトの`capturedAt`を観測可能なvintageとして使います。
- `0-2h`、`2-4h`、`4-8h`、`8-24h` lead bucketと運用時間帯に分けて評価します。
- 正式資格には28日・84日両windowの完成、全体MAE/WAPE ratio 1.10以下、十分な標本がある各時間帯MAE ratio 1.25以下が必要です。
- paired日付block bootstrapでモデルとTEPCOの絶対誤差差の不確実性も記録します。

`collecting`は機能しているが履歴が不足している状態であり、合格または不合格を意味しません。
