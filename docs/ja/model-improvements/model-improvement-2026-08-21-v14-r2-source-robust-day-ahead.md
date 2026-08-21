# 2026-08-21 v14-r2 データソース耐性型D-1予測 Champion

Languages: [English](../../en/model-improvements/model-improvement-2026-08-21-v14-r2-source-robust-day-ahead.md) / [한국어](../../ko/model-improvements/model-improvement-2026-08-21-v14-r2-source-robust-day-ahead.md)

## 判断

`v14-r2-source-robust-day-ahead`が性能劣化したv11 Championを置き換えました。先行するv14-r1 staging候補は配備していません。予測対象日の需要lagがほとんど未確定のとき、v11の欠損分岐を維持するか、安全でない日次共通shiftを適用する構造だったためです。v14-r2はD-1予測時点で実際に利用できる情報だけを使う専用q50経路を学習します。

昇格artifactはTEPCO予測から独立しています。TEPCO値は外部benchmarkと23時の一時的なlag連続性fallbackに限って使用し、学習targetや補正anchorには使用しません。

## モデル契約

- 通常のD0経路は絶対需要、lag-24残差、非営業日q50の構造を維持します。
- 過去湿度の欠損と短期気象fieldへの感度を下げる二つのsource viewを使い、出力差を従来q50から最大500MWに制限します。
- 予測時点で`lag_24h`、直近営業日需要、または直近非営業日需要が利用できない行では、専用source-robust q50モデルが作動します。このモデルは未確定需要lagの6特徴量とD-1で一貫して再構築できない気象fieldを除外します。
- D-1非営業日specialistは8月holdoutを開く前に7月development期間で選択し、weight 1.0を使用します。
- same-regime日次残差calibrationは直近3確定日、shrinkage 0.25、絶対上限1,000MWを使用します。artifact単位で管理され、対象日は学習しません。
- interval sanity calibration後にp95 half-widthを1.25倍します。scale前上限は3,000MW、最終上限は3,750MWで、q50は変更しません。

## 固定時点検証

すべてのreplayは模擬公開時点で利用できなかった観測値を除去します。対象日のactualを空にし、模擬時刻より後にcaptureされたsource commitの未来actualも遮断します。holdoutは現在コードで再学習した近似モデルではなく、実際に配備されたv11 artifact SHAと比較します。

| 評価 | 期間 | v14-r2 MAE改善 | RMSE改善 | 最大誤差改善 | Shape改善 | 優位日数 |
|---|---|---:|---:|---:|---:|---:|
| D0 development | 2026-07-01〜2026-07-31 | 5.13% | 4.63% | 2.03% | 10.16% | 24 / 31 |
| D0 exact-Champion holdout | 2026-08-01〜2026-08-20 | 18.76% | 16.54% | 15.51% | 16.01% | 16 / 20 |
| D-1 development | 2026-07-01〜2026-07-31 | 68.87% | 64.32% | 55.87% | 44.84% | 31 / 31 |
| D-1 exact-Champion holdout | 2026-08-01〜2026-08-20 | 39.82% | 46.96% | 44.39% | 30.22% | 13 / 20 |

D0 holdout MAEは1,725.4MWから1,401.8MWへ、D-1 holdoutは5,018.9MWから3,020.3MWへ低下しました。非退行上限を超えた運用segmentはありません。日付単位paired bootstrapのMAE比95%上限はそれぞれ0.9095と0.8383でした。

別の84日確定気象support replayでは、中心線MAEが902.3MWから883.9MWへ、shape誤差が534.7MWから512.6MWへ低下し、全時間帯が改善しました。単一時間最大誤差は437.1MW増えましたが500MW source-view trust region内であり、D0・D-1固定時点holdoutの最大誤差はともに改善しました。

## 昇格と監視

今日・明日のdriftが大きいのは、v11のD-1曲線が構造的に壊れた欠損lag分岐を使っていたためです。最大補正は+9,654.8MWでした。大規模driftの承認は、D0とD-1のexact-Champion holdoutが両方strict recovery gateを通過し、独立基準のD0 8%およびD-1 20% MAE改善を超えた場合だけ許可しました。

| 項目 | 値 |
|---|---|
| Contract | `v14-r2-source-robust-day-ahead` |
| Interval contract | `q025_q50_q975_p95_v14_source_robust_day_ahead` |
| Training cutoff | `2026-08-01` |
| Champion SHA-256 | `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3` |
| Rollback v11 SHA-256 | `28b75352b8b13713aba04880111dd11b3450864a3580f355081072af4266a640` |
| 昇格状態 | `recovery_promoted` |
| 安定化review | 確定運用3日後 |

D-1 holdout WAPEはなお約9.15%です。今回の昇格はTEPCO同等性の達成ではなく、v11の構造的欠陥からの復旧昇格です。安定化期間中は旧artifactを保持します。データソース整合性の失敗、非有限・不完全予測、または確定根拠でv11 shadowに対する有意な退行が確認された場合は直ちにrollbackを検討します。
