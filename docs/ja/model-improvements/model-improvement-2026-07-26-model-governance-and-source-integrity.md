# モデル昇格管理とデータソース整合性

作成日: 2026-07-26 (JST)

## 改善の背景

従来はFull ETLのたびにLightGBMを再学習し、既存モデルを直ちに上書きしていました。学習処理の成功だけでは、新しいモデルが営業日、非営業日、時間帯別の品質を維持する保証になりません。また、時間別cacheでは確定実績とTEPCO予測fallbackの区別が十分ではありませんでした。

## 検証根拠

2026-06-28から2026-07-25までの28日、672時間の実配信予測をreplayした結果です。

| 指標 | 結果 |
|---|---:|
| MAE | 560.0 MW |
| WAPE | 1.642% |
| RMSE | 761.7 MW |
| Shape delta MAE | 491.4 MW |
| P95 coverage | 96.1% |
| 平均P95 half-width | 1,867.1 MW |

Stage snapshotがある直近13日では、Analog補正がraw model MAEを910.8MWから957.1MWへ悪化させ、shape errorも増加させました。そのためAnalog補正は本番では無効化し、stage比較はshadow候補として継続します。

## 変更内容

### Champion/Challenger昇格

- 通常日のFull ETLは現在のChampionを維持します。
- Challengerの標準評価日は月曜日で、`TOKYO_GRID_EMS_FORCE_MODEL_TRAIN`により明示的な評価も可能です。
- 評価ごとに直近の確定28日をrolling windowとして使用します。28日ごとに一度だけ入れ替える意味ではありません。
- Challengerはbaseline改善に加え、絶対MAE、WAPE、最大誤差、shape error、営業区分、時間帯別上限をすべて満たす必要があります。
- 近未来の予測曲線が設定済みdrift上限を超えて変化する場合は昇格を拒否します。
- 互換Championがない場合でも失敗したgateを迂回せず、通常のbaseline fallbackを使用します。
- 昇格結果とmetadataは`metrics/model_promotion.json`に記録します。

### 需要・気象ソースの整合性

- 時間別cacheに`actual_source`を保存します。
- `tepco_forecast_fallback`は必要なlag連続性のためだけに利用します。
- fallback需要は学習target、当日実績slope、residual補正、Analog residual、検証actualから除外します。
- 確定CSV実績は常にfallbackより高い優先順位を持ちます。
- 直近時間の予報気象は、公式観測到着後に`AMEDAS_ACTUAL`へ置き換えます。

### 運用replay

`metrics/operational_replay.json`には以下を記録します。

- 実配信MAE、WAPE、RMSE、最大誤差、shape error
- 営業日/非営業日および時間帯別指標
- TEPCOをモデル入力に使わない独立した参考性能
- 日付別の最新snapshotによるstage比較
- band coverageとshadow状態の経験的band幅推奨値

Stage比較は各日付の最新snapshotを使用するため、過去の全Intraday runを完全再現した結果として解釈してはいけません。

### CI

新しいCI workflowは`main`へのpushとpull requestでPython全テストとReact production buildを独立実行します。

## ロールバック

- 明確な緊急迂回時のみ`model_promotion.enabled: false`を使用します。
- `adjustment.analogous_day.enabled`は、営業区分と時間帯別replayで一貫した改善を確認した後に再有効化します。
- Challengerが一つでもgateを通過できない場合、現在のChampionを維持します。
