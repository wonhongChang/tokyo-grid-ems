# 学習型 Intraday Challenger

[English](../en/learned-intraday-challenger.md) | [한국어](../ko/learned-intraday-challenger.md)

## 状態と構成

別のL4/L5追加研究は[Lead-Aware Intraday Shadow](lead-aware-intraday-shadow.md)を参照。以下の元結果は凍結している。

2026年10月3日の結論は **RETAIN CHALLENGER: L2**。本番昇格ではない。Champion、ETL、scheduler、公開予測、既存の昇格方針は変更していない。Jevや有料モデルAPIも使用しない。

`python/eval/intraday_challenger/` は発行時点の不変snapshotから当日観測経路・残差を抽出し、誤差モデルを学習する。別領域にshadow予測を保存し、確定実測の到着後に日別・時間帯別・lead別・累計を評価する。

| 候補 | 予測式 | 学習target |
|---|---|---|
| L1 | raw + learned error | actual - raw |
| L2 | recorded post + learned remaining error | actual - post |
| L3 | pre + latest raw residual + learned residual change | actual - pre - latest raw residual |

L3だけ研究上でintraday heuristicを迂回する。LightGBMのL1 loss、240 trees、learning rate 0.035、12 leaves、min-child 45、L2 regularization 10、固定seed、CPU 2 threadsを使用する。日付・時間ごとの収集回数の逆数で重み付けする。Validationで選択し、train+validationで再学習してからholdoutを一度評価する。結果を見て設定や選択を変更しない。

## データと時点管理

固定時刻は `2026-10-03T18:00:50.748933+09:00`。Code revisionは `fe1eaa84a6cc70d061a4c4d8d56782e373d055c4`、data revisionは `ea57d03155b4c5b3f86c97b1b8fb5cbcc3afd275`。以前のretained snapshotsもhash確認して使用した。

517 runsからpositive-leadの5,622行を構築。確定5,235行、暫定294行、未観測93行。未観測は将来55行、区間未終了11行、過去未受信27行である。反復収集行は独立標本ではない。

| 区分 | 期間 | 確定行 | Closest (0,120]分 |
|---|---|---:|---:|
| Train | 8/28~9/13 | 1,863 | 261 |
| Validation | 9/14~9/21 | 1,103 | 140 |
| Holdout | 9/22~10/1 | 2,269 | 229 |

46個のnumeric featuresは予測経路、lead/calendar、終了済み当日実測、残差trend、記録済みlag/anchor deltaからなる。h時の実測は[h,h+1)終了後かつrecorded cutoff以内でのみ使用する。Forecast fallbackは実測扱いしない。Final actualはlabelのみに結合する。TEPCO予測と時点が証明できない再構成気象は除外し、欠測は欠測のまま保持する。

Source hash/pointer、issue/target/lead、cutoff、label hashを行ごとに保存する。比較対象は**同じrunのrecorded post**であり、publishedや最新方針による過去再計算とは混合しない。過去championのartifact/policy identity、final labelの正確なETL到着時刻は未確認。これは時系列順のretrospective実験であり当時の配備実績ではない。Holdoutの一部日付は既存研究で検討済みなので、新しい独立確認は将来shadowで必要になる。Native interval、00時target、翌日予測は未検証。

最初の結果前preregistration hashは `3ede9079a0305e916add1883d580d08f693a8151601452f0159018185ebbc568`。その後の修正はdataset整合性とshadow記録境界であり、候補・期間・選択式・基準は変更していない。

## 結果

同一確定populationで比較。誤差単位はMW。

| モデル | 全positive MAE | RMSE | WAPE | Closest MAE | Closest RMSE |
|---|---:|---:|---:|---:|---:|
| Recorded champion | 1,006.0 | 1,321.1 | 3.354% | 576.7 | 771.9 |
| L1 | 952.2 | 1,308.4 | 3.174% | 649.1 | 838.7 |
| L2 | 915.4 | 1,272.9 | 3.052% | 604.9 | 782.0 |
| L3 | 938.6 | 1,300.0 | 3.129% | 619.4 | 807.5 |

L2は全positive MAEを9.01%改善したがClosest MAEは4.88%悪化。全体の改善/悪化は1,332/937行、日別勝/敗は6/4。Closestは105/124行、3/7日である。悪化行の追加絶対誤差p50/p90/p95/maxは全体299.4/715.6/845.3/1,513.8MW、Closest234.7/583.5/695.1/1,264.3MW。

全体の午後・夜間・非営業日は改善したが、Closestの午後・夜間は悪化した。Closest最大悪化は9/24 12:26発行の13時target。9/22 20時guard成功例でも689.1MW悪化した。F/G/Hのsource-exactな16件を別途保存し、学習期間内の例を独立確認には数えない。

同一run内の隣接target delta MAEは415.2 → 362.4に改善。一方、隣接issue間の同一target平均改訂量は167.7 → 284.4に増加した。曲線内とrun間の安定性は別の問題である。10/3暫定Closest 14件のraw/champion/L2 MAEは629.2/702.6/781.5で、今日の改善とは言えない。

結果前の研究用基準はMAE/WAPE 5%以上改善、RMSE増加2%以内、日別勝数>=敗数、train baseline分位点に基づく時間帯・tail許容値など。L2はvalidationのtail安全性と選択scoreで選ばれたが、holdoutのClosest平均改善・日別勝敗条件に失敗した。結果後の基準緩和はしていない。

## CLIと分離

```text
python -m python.eval.intraday_challenger --help
```

CLIは名前付き `data/intraday_challenger/<workspace>` を `--output-root` として要求する。この領域はGit対象外。

| コマンド | --output-root以外の必須入力 |
|---|---|
| prepare | --input-root, --input-sha, --periods |
| train-replay | --registration-sha |
| shadow-capture | --snapshot, --snapshot-sha, --model-root, --identity-sha |
| shadow-evaluate | --actual-root, --state-file |
| shadow-watch | --snapshots-root, --model-root, --identity-sha, --actual-root, --state-file |

`--periods` はtrain/validation/holdoutの[start,end]を含むJSON。Input manifest `intraday-input/1.0.0` はasOf/runs/actualsと相対JSON path/SHA-256を持つ。Runにはdate/issuedAt、actualにはdate/stateが必要。Hash、vintage、重複issue-target、split不整合は停止する。

Shadowはissue時刻と実保存recordedAtを記録する。保存時点ですでに開始したtargetはretrospectiveに分離しlive確認に数えない。予測は不変・冪等で、actual改訂は別hashのevaluationになる。異なるmodel identityを同じpopulationにまとめない。Native intervalは未確認のままでchampionからコピーしない。

任意のstandalone workerはPython内で標準300秒待機する。Source同期は外部の責任。ETL/schedulerには登録しておらず、開始には別の運用判断が必要である。

## 再現性と次の判断

新規42件を含むintraday/replay/batch関連244 testsが通過。Source identityではWindows GitのLF/CRLF変換のみ正規化し、data/model hashは元のbytesを検証する。6 native model filesと数値レポートも完全再現した。最終preregistration hashは `7fa4c6b5b6d0538c40e7c688f677ce5dfb7727669d2623da58ea764d14b34bf6`、L2 model hashは `0bcd25b4133fa57fe446da5eb6beea537f65947aaa940d2c027718ac9b9a88f5`。

確定14日以上、営業日8日以上/非営業日4日以上、prospective pair 300件以上、Closest target 150件以上で再評価する。収集が揃えば10/18 ETL後が最初の判断時点。これは標本準備条件であり自動昇格条件ではない。既存の平均/tail/時間帯/regime基準に加えrun間改訂安定性、native interval、champion identityの証拠が必要。本番採用にはserving-policy version変更と通常のpromotion手順を要求する。

Dataset、replay、model、日別shadowはローカルGit除外領域に置き、コード・tests・公開設計/結果概要のみversion管理する。
