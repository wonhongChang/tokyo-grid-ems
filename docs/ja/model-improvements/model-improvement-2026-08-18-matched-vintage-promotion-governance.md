# 2026-08-18 同一vintage TEPCO評価とモデル昇格ガバナンス

言語: [English](../../en/model-improvements/model-improvement-2026-08-18-matched-vintage-promotion-governance.md) / [한국어](../../ko/model-improvements/model-improvement-2026-08-18-matched-vintage-promotion-governance.md)

## 問題

TEPCOは当日予測を繰り返し更新し、経過時間の値も修正する場合がある。既存の`forecast_accuracy.json`は確定実績とファイルに最後に残ったTEPCO値を比較するため、自モデルの当時の公開値とTEPCOの後日修正値が混在し得た。また従来の昇格gateはseasonal baselineと絶対上限を中心に評価しており、性能低下Championを安全に置換する復旧経路が明確でなかった。

## 変更

- ETL/Intraday実行ごとに、未来時間の自モデル予測とTEPCO予測を同一実行で保存する。
- `reports/internal/forecast-vintages/YYYY-MM-DD.json`へappend-onlyで記録し、後のTEPCO修正で過去captureを上書きしない。
- TEPCOが個別の`issuedAt`を提供しないため、プロジェクトの`capturedAt`を観測可能なforecast vintageとして使用する。
- `0-2h`、`2-4h`、`4-8h`、`8-24h`のlead bucketと運用時間帯に分けて評価する。
- `metrics/forecast_vintage_accuracy.json`にMAE、WAPE、RMSE、最大誤差、モデル/TEPCO比率、日付block bootstrap信頼区間を記録する。
- 正式資格判定では、全lead bucket・時間帯でpaired-hour coverage 80%以上を要求する。RMSE比率、最大誤差比率、paired bootstrap MAE比率の信頼区間上限もgateに含め、有利な点推定だけでは通過できないようにする。
- 過去のforecast/calibration snapshotは、対象日が一致し生成時刻差が120秒以内の場合に限り初期台帳へ移行する。
- ChampionとChallengerを同一train cutoff・holdoutで再現し、通常昇格と性能低下Championの復旧昇格を分離する。
- 復旧候補は28日でMAE/WAPEを10%以上改善し、riskと重要segmentの退行を5%以内に抑え、56/84日でも改善方向が一致する必要がある。
- 大きなprediction driftまたは未承認候補はshadow artifactとして保持する。昇格時には旧Championをrollback artifactとして保存する。
- 復旧昇格は`metrics/model_shadow_evaluation.json`が最低72 shadow forecast-hourと2確定日を確認するまでfail-closedで停止する。その後も明示的な承認flagを必須とする。
- 非評価日のETLが直近の詳細判断を消さないよう`lastEvaluation`を維持する。

## 再現結果

同一train cutoffでv13契約とv11契約を比較した。

| 期間 | v13 MAE | v11契約 MAE | v13改善率 | 判断 |
|---|---:|---:|---:|---|
| 28日 | 1,275.8MW | 1,351.7MW | 5.62% | 復旧基準10%未満 |
| 56日 | 983.8MW | 1,016.0MW | 3.17% | 改善方向だがmargin不足 |
| 84日 | 891.6MW | 916.8MW | 2.75% | 改善方向だがmargin不足 |

直近365日学習と保守的なLightGBM複雑度も検証した。最良の28日候補はMAE 1,207.9MWだったが、同一データで学習したv11契約比の改善は3.58%、WAPEは3.456%だった。v13および実験候補は強制昇格せず、v11を暫定Championとして維持する。

## 初期matched-vintage状態

同一実行を厳密に対応付け、204件の過去capture、14日、911比較行を復元した。lead bucket別の初期モデル/TEPCO MAE比率は約1.84〜2.20である。28日と84日の両windowが揃うまでは`collecting`であり、正式なparity判定には使用しない。

## 影響

今回の変更は配信中のq50や予測bandを変更しない。不公平な時点比較と危険な昇格を防ぎ、将来モデルがTEPCO同等へ到達したかを再現可能な基準で判断できるようにする。
