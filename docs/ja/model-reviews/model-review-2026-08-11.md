# 2026-08-11 モデル運用レビュー

言語: [English](../../en/model-reviews/model-review-2026-08-11.md) / [한국어](../../ko/model-reviews/model-review-2026-08-11.md)

作成日: 2026-08-10 JST  
レビュー予定: 2026-08-11 朝のETL完了後  
状態: レビュー前

## 1. 目的

複数日の結果をまとめて確認した後の変更によって、実運用予測がさらに悪化した事例が2回続いた。このため、今回は証拠、合格ゲート、中断条件を事前に固定する。

- 日数が増えたことだけを理由にモデルを変更しない。
- 全体平均の改善で日別・時間帯別のshape回帰を隠さない。
- 実際に公開されたserved forecastを評価する。
- raw model、後処理、Intraday、Freezeの影響を分離する。
- TEPCO予測は外部比較値としてのみ使用し、入力や補正目標にしない。
- 結果を見た後に合格基準を緩和しない。
- 原因と回帰安全性を確認できない場合はChampionを維持する。

## 2. 事前に固定する事実

- 現在の運用Champion: v11 lag24 residual ensemble。
- 現在のChallenger契約: v13 transition cooling blend。
- 2026-08-04の評価でv13は84日ゲートを通過したが、28日MAEが`1,036.6 MW`で上限`1,000 MW`を超えたため昇格していない。
- 2026-08-11は火曜日だが、日本の祝日「山の日」である。
- `is_holiday=1`、`is_non_business_day=1`でなければならない。
- チャートの12時bucketは12:00から13:00の需要を表す。
- 営業日の昼休みdipは固定offsetではなく、過去の同一営業タイプshapeが支持する場合だけ適用する。
- 非営業日では`MiddayTransitionGuard`を必ずスキップする。

## 3. 評価対象

| レジーム | 日付 | 目的 |
|---|---|---|
| 営業日 | 2026-08-05から2026-08-07 | 基本shape、朝ramp、昼休みdip、午後・夕方 |
| 週末 | 2026-08-08から2026-08-09 | 非営業日q50と週末shape |
| 営業復帰 | 2026-08-10 | 週末lag汚染と復帰ramp |
| 祝日予測 | 2026-08-11 | 祝日カレンダー、非営業日経路、昼guardのスキップ |

2026-08-11の最終精度は2026-08-12 ETL後に確定する。

- 直近28確定日: 正確に`672`時間。
- 直近84確定日: 正確に`2,016`時間。
- 営業日、非営業日、営業タイプ遷移日を別々に集計する。
- 最近と長期で逆方向の誤差がある場合、全体平均で相殺しない。

## 4. データ完全性ゲート

必須入力に問題があればモデル比較を中断し、データ問題を先に修正する。

- [ ] Local ETLが成功し、実行時刻が記録されている。
- [ ] `data`ブランチに最新ETLコミットがある。
- [ ] `actual/2026-08-10.json`に24個の非null実績がある。
- [ ] `tepco_forecast_fallback`を検証actualとして扱っていない。
- [ ] 2026-08-10の日次・内部診断レポートがある。
- [ ] 2026-08-11のforecastとsnapshotがある。
- [ ] model artifact、学習終了日、metadata、interval versionが一致する。
- [ ] 気象データに説明できないsource遷移、NaN、長時間forward-fillがない。
- [ ] Actions/Pages障害によるsnapshot欠損を明示する。
- [ ] final actual coverageとstage snapshot coverageを混同しない。

| 項目 | 結果 | 根拠 | 判定 |
|---|---|---|---|
| ETL |  |  |  |
| 24時間actual |  |  |  |
| Weather source |  |  |  |
| Forecast snapshots |  |  |  |
| Model metadata |  |  |  |
| Actions/Pages |  |  |  |

## 5. 日別の運用性能

各日で実際に使用されたmodel/configとsnapshotを基準にする。

| 日付 | Day type | Model/config | MAE | WAPE | RMSE | Bias | Max error | TEPCO MAE | 備考 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-08-05 | 営業日 |  |  |  |  |  |  |  |  |
| 2026-08-06 | 営業日 |  |  |  |  |  |  |  |  |
| 2026-08-07 | 営業日 |  |  |  |  |  |  |  |  |
| 2026-08-08 | 週末 |  |  |  |  |  |  |  |  |
| 2026-08-09 | 週末 |  |  |  |  |  |  |  |  |
| 2026-08-10 | 営業復帰 |  |  |  |  |  |  |  |  |

- [ ] 一日中同じ方向に偏った日を特定した。
- [ ] 誤差符号が繰り返し変わるshape不安定日を特定した。
- [ ] TEPCO dominance hoursは補助参考値としてのみ記録した。
- [ ] 異なるserving versionの日を同条件として比較していない。
- [ ] 各日の最悪区間と原因stageを記録した。

## 6. 時間帯別評価

| 時間帯 | 主な確認事項 | Model MAE/WAPE | Shape delta error | 判定 |
|---|---|---:|---:|---|
| 00-05 | 日付境界carryoverまたはlag24が基底を歪めたか |  |  |  |
| 06-11 | 朝rampが不自然または一方向に偏ったか |  |  |  |
| 12 | 営業日の昼休みdipが根拠に応じて作動したか |  |  |  |
| 13-16 | reboundや局所spike処理が曲線を歪めたか |  |  |  |
| 17-19 | 根拠のない夕方reboundがあったか |  |  |  |
| 20-23 | 夜間低下と23時fallback境界が安定したか |  |  |  |

## 7. 営業日の昼休みdip監査

対象日: 2026-08-05、2026-08-06、2026-08-07、2026-08-10。

- [ ] `is_non_business_day`が0である。
- [ ] `business_midday_x_lag_24h_delta`を記録した。
- [ ] `business_midday_x_recent_delta_mean`を記録した。
- [ ] `business_midday_x_recent_delta_q25`を記録した。
- [ ] `business_midday_x_same_day_recent_delta_mean`を記録した。
- [ ] lagと同一営業タイプshapeが実際に低下を支持している。

| 日付 | Actual 11->12 | Actual 12->13 | Raw 11->12 | Midday delta | Pre-calibration | Served | 判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-08-05 |  |  |  |  |  |  |  |
| 2026-08-06 |  |  |  |  |  |  |  |
| 2026-08-07 |  |  |  |  |  |  |  |
| 2026-08-10 |  |  |  |  |  |  |  |

正常な動作:

- 最近の営業日根拠が弱い場合、固定dipを作らない。
- 支持shapeが負でforecastが明確に高い場合のみ、cap内で下方調整する。
- 12時の単発dipを午後の継続低下として伝播しない。
- Intraday residualが昼のshockを午後全体へ伝播しない。
- servedとmidday stageの差はFreezeまたは過去snapshotとして分離する。

## 8. 2026-08-11 祝日経路

- [ ] `jpholiday`が「山の日」と判定する。
- [ ] `is_holiday=1`、`is_non_business_day=1`である。
- [ ] 営業日専用q50/guardが有効にならない。
- [ ] `MiddayTransitionGuard`をスキップする。
- [ ] business morning/daytime interactionが0または無効である。
- [ ] non-business anchorとlag mismatch contextが正しい。
- [ ] 2026-08-10の営業日lagが祝日需要を過度に持ち上げない。
- [ ] 固定の祝日下方offsetを追加しない。

## 9. Stage別の原因分解

問題時間ごとに値とdeltaを記録する。

1. `raw_lgbm`
2. `analog_adjusted`
3. `post_holiday_guarded`
4. `midday_guarded`
5. `localized_shape_guarded`
6. `pre_calibration`
7. Intraday residual correction
8. `served_forecast`
9. Published Forecast Freeze gap

| 日付/時間 | Raw | Analog delta | Guard delta | Intraday delta | Served | Actual | 主原因stage |
|---|---:|---:|---:|---:|---:|---:|---|
|  |  |  |  |  |  |  |  |

原因タグは`data_quality`、`raw_model_level`、`raw_model_shape`、`weather_regime`、`calendar_regime`、`analog_adjustment`、`shape_guard`、`intraday_carryover`、`freeze_artifact`、`insufficient_evidence`から選ぶ。

## 10. 予測バンド監査

- [ ] 日別・時間帯別p95 coverageを計算した。
- [ ] バンド中心がq50と一致する。
- [ ] 最小幅と最大tail capの影響を記録した。
- [ ] q025/q975非対称とrebalanceを確認した。
- [ ] 中心線誤差をバンド拡大だけで隠していない。

| 区間 | Coverage | 平均幅 | 最大幅 | 逸脱方向 | 判定 |
|---|---:|---:|---:|---|---|
| 全体 |  |  |  |  |  |
| 00-05 |  |  |  |  |  |
| 06-11 |  |  |  |  |  |
| 12-16 |  |  |  |  |  |
| 17-23 |  |  |  |  |  |

## 11. Champion/Challengerゲート

新候補を追加する前にChampion v11とChallenger v13を比較する。

| ゲート | 固定基準 | 結果 | 通過 |
|---|---:|---:|---|
| 28日coverage | 672/672時間 |  |  |
| Baseline比MAE改善 | 20%以上 |  |  |
| 28日MAE | 1,000 MW以下 |  |  |
| 28日WAPE | 3.0%以下 |  |  |
| Shape delta MAE | 750 MW以下 |  |  |
| Max error | 6,500 MW以下 |  |  |
| Segment MAE | 1,500 MW以下 |  |  |
| Segment shape delta MAE | 1,100 MW以下 |  |  |
| Segment MAE回帰 | 10%以下 |  |  |
| 48時間平均drift | 900 MW以下 |  |  |
| 時間最大drift | 2,500 MW以下 |  |  |

営業日連続、営業日から週末、週末連続、週末/祝日から営業日、平日中の祝日、急昇温、急低温、高湿度遷移を別々に回帰確認する。

ゲートが1つでも失敗すれば昇格しない。

## 12. 変更ルール

即時修正できるのは、カレンダー誤り、actual source汚染、stage順序バグ、config無視、metadata/snapshot欠陥、再現可能な計算バグに限る。

新feature、guard threshold、cap、shrinkage、lag blend weight、バンド幅の変更は、独立した実験とreplay後にのみ検討する。

禁止事項:

- TEPCO予測を補正入力に使う。
- 観測済み実績で同日の予測を事後適合する。
- 特定日付の条件を追加する。
- 候補を通すために昇格基準を緩和する。
- 直近だけ改善し、28/84日または別レジームを悪化させる変更を採用する。
- モデルと運用後処理を同じ実験で変更する。

## 13. 追加確認項目

新しい証拠により項目を追加できるが、事前ゲートは変更しない。

| 追加項目 | 理由 | 必要な証拠 | 結果 | 後続対応 |
|---|---|---|---|---|
|  |  |  |  |  |

## 14. 実行記録

| 実行 | コマンド/ツール | 開始 | 終了 | 出力 | 状態 |
|---|---|---|---|---|---|
| 公開データ検証 | `python scripts/validate_public_before_publish.py` |  |  |  |  |
| Python tests | `python -m pytest -q` |  |  |  |  |
| 28日operational replay | 内部evaluator |  |  | `metrics/operational_replay.json` |  |
| Challenger validation | promotion evaluator |  |  | `metrics/model_promotion.json` |  |
| Prediction drift | Champion/Challenger 48h |  |  |  |  |

## 15. 最終判断

- [ ] Champion維持、コード変更なし。
- [ ] データまたは運用上の欠陥のみ修正。
- [ ] 後処理候補をshadow評価で維持。
- [ ] モデル候補をChallengerとして維持。
- [ ] 全ゲート通過後にのみ昇格。

記録:

- 主原因:
- 変更が必要または不要な理由:
- 意図的に変更しない領域:
- 回帰検証結果:
- 残存リスク:
- 次回レビュー日:

公開前確認:

- [ ] 最終変更範囲と昇格可否をユーザーが確認した。
- [ ] モデル動作と文書が一致する。
- [ ] 実装変更を採用した場合にのみmodel-improvement文書を追加した。
