# 2026-09-03 v14-r2 運用モデルレビュー

言語: [English](../../en/model-reviews/model-review-2026-09-03.md) / [한국어](../../ko/model-reviews/model-review-2026-09-03.md)

レビュー日: 2026-09-03 JST

根拠範囲: v14-r2が全面的に配信された2026-08-22〜09-02の確定実績288時間、2026-09-03 00〜20時の実績21時間、同一実行時点のforecast snapshot、運用calibration snapshot、診断feature、予測区間

再現基準: `origin/data` commit `cb4e9c6d5`、forecast contract `v14-r2-source-robust-day-ahead`、artifact SHA `c2914b699dc306c61c6eb8f777d99fdebf1f7336dbf83bd01d851156e8b0cdd3`

状態: 完了 - v14-r2を暫定維持し、状態を`review_required`と判定。P0の評価・calibration整合性修正とv15 Challenger実験が必要。今回のレビューでは配信動作を変更しない

## 結論

- v14-r2を根拠なくrollbackしない。同一契約で検証済みの代替モデルがなく、Intraday補正は集計上の誤差を改善している。
- 現在のChampionをhealthyとは判定できない。確定期間の配信MAEは693.6MWだが、同一vintage比較では全lead bucketでTEPCOより26〜51%大きい誤差となった。
- 9月3日00〜20時はMAE 925.8MW、bias +821.9MWである。16時と17時はそれぞれ+3.11GW、+3.48GWの過大予測だった。
- 最大の問題はIntradayやFreezeではなくraw q50である。0〜2時間leadではraw MAE 1,201.7MWが後処理とIntraday後に1,004.9MWまで減少した。
- 現在の予測区間は適切というより過度に広い。P95 coverageは100%だが平均半幅は約3.70GWで、観測行の88%が設定上限に達した。
- 予測値を調整する前に、same-regime snapshot schema、固定origin保存、model contract別health集計をP0として修正する。
- 次にv15 Challengerでlag/同一営業種別anchor依存と気象転換featureを検証する。replay根拠なしに特定時刻capやguardを追加しない。

## 評価契約

| 区分 | 用途 | 注意点 |
|---|---|---|
| 最終配信予測 | 利用者が実際に見た品質 | Published Forecast Freezeを含む |
| 同一vintage比較 | 同じ`capturedAt`のモデルとTEPCOを比較 | 外部比較の主指標 |
| 最新TEPCO値 | dashboard上の最新値との比較 | TEPCOは過去予測も更新するため参考値のみ |

TEPCO予測はモデル入力にもcalibration targetにも使用しない。

## データ整合性

| 確認項目 | 結果 | 根拠 |
|---|---|---|
| v14-r2対象範囲 | 合格 | 8月21日は移行日として除外し、8月22日以降は同一artifact SHA |
| 確定実績 | 合格 | 9月2日まで12日、288時間 |
| 当日実績 | 合格 | 9月3日20時まで21時間 |
| 主要診断feature | 合格 | 確定期間の需要、気温、湿度、lag、営業種別anchorに欠損なし |
| stage復元 | 合格 | 215 calibration snapshots、2,851 future rowsを最大17秒差で対応付け |
| 気象vintage lineage | 不十分 | 予報発表時刻と完全なsource lineageを一貫して保存していない |
| 固定origin | 不合格 | 日次snapshot上限により真の初回予測が削除され得る |

## 確定日別性能

| 日付 | 区分 | MAE MW | WAPE | RMSE MW | Bias MW | 最大誤差 MW |
|---|---|---:|---:|---:|---:|---:|
| 2026-08-22 | 土曜 | 682.6 | 2.08% | 903.2 | -98.0 | 1,966.2 |
| 2026-08-23 | 日曜 | 503.0 | 1.64% | 721.1 | +95.5 | 2,510.0 |
| 2026-08-24 | 営業日 | 687.7 | 1.79% | 866.1 | -129.7 | 1,973.9 |
| 2026-08-25 | 営業日 | 446.3 | 1.09% | 601.1 | +19.0 | 1,810.0 |
| 2026-08-26 | 営業日 | 698.4 | 1.68% | 877.5 | +114.8 | 2,170.7 |
| 2026-08-27 | 営業日 | 1,140.3 | 3.18% | 1,473.4 | +1,037.7 | 3,634.7 |
| 2026-08-28 | 営業日 | 972.1 | 2.66% | 1,113.2 | -218.4 | 2,150.9 |
| 2026-08-29 | 土曜 | 1,173.3 | 4.15% | 1,355.5 | +763.6 | 2,490.0 |
| 2026-08-30 | 日曜 | 473.1 | 1.79% | 651.9 | +9.4 | 1,507.3 |
| 2026-08-31 | 営業日 | 815.7 | 2.60% | 1,007.8 | +341.8 | 2,129.3 |
| 2026-09-01 | 営業日 | 334.7 | 1.02% | 491.6 | +43.5 | 1,635.1 |
| 2026-09-02 | 営業日 | 395.6 | 1.11% | 557.4 | -159.7 | 1,650.0 |

12日合計はMAE 693.6MW、WAPE 2.02%、RMSE 933.5MW、bias +151.6MWである。最初の5日はMAE 603.6MW、直近7日は757.8MW、直近3日は515.3MWだった。単調な劣化ではなく、特定regimeで大きく失敗する変動性が中心である。

## 9月3日00〜20時の暫定評価

| 指標 | 結果 |
|---|---:|
| 観測時間 | 21時間 |
| MAE | 925.8MW |
| WAPE | 2.62% |
| RMSE | 1,292.8MW |
| Bias | +821.9MW |
| 最大誤差 | +3,480.0MW、17時 |
| Shape delta MAE | 782.1MW |

主な誤差は11時+1.95GW、15時+1.45GW、16時+3.11GW、17時+3.48GWである。16時予測は00:25時点ですでに+4.31GW高く、05:30以降は+6.05GWまで拡大した。17時も朝から+4.73〜+5.40GW高く、直前の一回のIntraday実行だけが原因ではない。

17:37実行では18時raw q50が42,359.6MWから38,768.6MWへ、19時は40,181.9MWから37,709.8MWへ低下した。気象deltaも18時は-0.7°Cから-3.2°C、19時は-0.5°Cから-2.2°Cへ変化した。更新は18時以降を改善したが16〜17時には遅かった。発表時刻lineageが不十分なため、上流APIの誤りとまでは断定しない。

## 時間帯別性能

| 時間帯 | 件数 | MAE MW | Bias MW | RMSE MW | 絶対誤差P95 MW |
|---|---:|---:|---:|---:|---:|
| 00〜05時 | 78 | 474.3 | +24.6 | 610.1 | 1,264.4 |
| 06〜10時 | 65 | 670.3 | -17.7 | 896.5 | 1,907.0 |
| 11〜15時 | 65 | 793.0 | +364.5 | 1,023.7 | 2,170.7 |
| 16〜18時 | 39 | 1,048.7 | +544.0 | 1,335.2 | 3,110.0 |
| 19〜23時 | 62 | 744.9 | +245.9 | 1,040.9 | 2,133.7 |

最も弱いのは16〜18時で、次いで11〜15時、19〜23時である。時刻別MAE上位は18時、19時、17時、14時、09時となった。

## 同一Vintage外部比較

| Lead | 件数 | モデルMAE MW | モデルWAPE | TEPCO MAE MW | 比率 |
|---|---:|---:|---:|---:|---:|
| 0〜2h | 396 | 954.3 | 2.71% | 631.9 | 1.51 |
| 2〜4h | 375 | 1,277.5 | 3.50% | 928.3 | 1.38 |
| 4〜8h | 685 | 1,604.7 | 4.24% | 1,228.8 | 1.31 |
| 8〜24h | 1,221 | 1,634.7 | 4.46% | 1,296.4 | 1.26 |

0〜2h leadの日付block bootstrapでは絶対誤差差の平均が+315.8MW、95%区間が+130.0〜+506.4MWだった。モデルが優位だったのは12日のうち3日である。最新TEPCO値によるMAE 410.2MWは参考値であり昇格gateには使用しない。

## 運用Stage分解

| Lead | Raw q50 MAE | Intraday前MAE | 最終MAE | 最終Bias | Intraday改善/悪化 |
|---|---:|---:|---:|---:|---:|
| 0〜2h | 1,201.7 | 1,231.1 | 1,004.9 | +458.2 | 281 / 144 |
| 2〜4h | 1,538.5 | 1,526.0 | 1,393.2 | +871.0 | 257 / 147 |
| 4〜8h | 1,847.7 | 1,820.2 | 1,754.6 | +1,227.8 | 416 / 319 |
| 8〜24h | 1,818.1 | 1,805.6 | 1,774.9 | +1,047.3 | 731 / 554 |

Intradayは維持する。ただしlead別に34〜43%の行を悪化させるため、上限を一律に増やさない。主対象はraw q50とregime表現である。

0〜2h朝帯はraw MAE 1,074.3MW、Intraday前1,154.0MW、最終1,096.8MWだった。Post-holiday/timeband guardは、削除前にtrigger行限定のshadow disable replayが必要である。

Published Forecast Freezeも維持する。配信予測は日末再計算より194行で良く、113行で悪かった。予測当時のvintageを保存する仕組みであり、9月3日の失敗は対象時刻が閉じる前から存在した。

## 原因診断

### Lagとanchorへの依存

配備q50のgain importanceでは`recent_same_business_type_mean`が23.59%、`lag_24h`が20.78%である。lag_24hが同一営業種別anchorを5,000MW超上回る行はMAE 970.5MW、bias +667.0MWだった。

### 冷却転換と湿度上昇

前日より2°C以上低い行はMAE 1,091.8MW、bias +930.5MWだった。湿度が10ポイント以上上昇した行はMAE 1,122.9MW、bias +794.8MWだった。気温、冷房、湿度、不快指数deltaの符号付き変換と相互作用を個別にablationする必要がある。

### Same-regime calibrationのstale状態

`python/forecast/same_regime_calibration.py`は`forecastBuild.hourly`を読むが、snapshotは`forecastBuild.series`に保存される。そのため`metrics/same_regime_day_level_calibration.json`は8月21日以降更新されず、営業日+133MW、非営業日-486.5MWの古いadjustmentが残っている。

反実仮想ではaggregate raw MAEの改善は約12.5MWに留まるため、これは主因ではない。ただしstale calibrationが無警告で適用されるP0整合性欠陥である。日次16 snapshot上限も固定originを不安定にする。

### Model contractを混在したhealth

`model_promotion.json`は`healthy`とするが、28日replayはv11とv14-r2を混在している。health、昇格gate、警告はartifact SHAとforecast contract別に集計しなければならない。

### 気象Vintage lineage不足

各実行に`weather_source`、`forecast_issued_at`、`fetched_at`、AMeDAS residual、fallback状態を保存し、遅い予報改訂を再現可能にする。

## 予測区間レビュー

P95とP99 coverageはともに100%だが、P95平均半幅は3,703MWで、309行中272行、88.0%が3,750MW上限に達した。現在のfloor-only conformalは広すぎるnative quantileを狭められない。

次のshadow候補はv14-r2専用とし、leadとtimebandで分割する。適用gateは全体P95 coverage 93〜97%、主要区間すべて90%以上、平均幅15%以上削減とし、少数区間には階層的backoffを使う。

## 修正項目

| 優先度 | 修正 | 理由 | 完了条件 |
|---|---|---|---|
| P0 | same-regime calibrationで`forecastBuild.series`を読む | 8月21日以降stateがstale | 24行をparseし最新確定日まで更新 |
| P0 | rolling保存外にimmutable originを保持 | 最古の保存snapshotは固定vintageではない | prune後もorigin IDと発表時刻を保持 |
| P0 | calibration freshness guardと警告 | stale adjustmentの無警告適用を防ぐ | bypassまたはdegraded化しageを表示 |
| P0 | Champion healthをartifact/contract別にする | v11/v14混在で現行品質が隠れる | 同一SHAかつ配備後の行のみ集計 |
| P1 | v15を学習しablation | raw q50が主な誤差源 | lag・気象候補を分離してv14と比較 |
| P1 | lag/anchor動的regularizationを検証 | lag過熱行で+667MW bias | 大きいgapを改善し通常regimeを悪化させない |
| P1 | 気象deltaと湿度をablation | 冷却・湿度上昇時の過大予測 | clipping、source-robust、no-humidityを比較 |
| P1 | 気象lineageを保存 | 遅い改訂を再現できない | source、issue/fetch時刻、fallback、residual保存 |
| P1 | timeband guardをtrigger限定でshadow無効化 | 朝0〜2hで悪化可能性 | 対象行の改善と回帰を同時に提示 |
| P1 | v14専用interval recalibrationをshadow評価 | 88%が幅上限 | coverage gateを守り平均幅15%以上削減 |
| P2 | D-1固定予測の24〜48h評価を追加 | 翌日予測とIntraday品質を分離 | 固定D-1 originを独立保存・採点 |

## v15実験原則

1. 学習cutoffを2026-09-02まで拡張し、v14-r2と同じdata contractで比較する。
2. baseline、lag regularization、weather-delta clipping、no-humidity、source-robust候補を分離する。
3. 全体に加えて営業/非営業、06〜10、11〜15、16〜18、19〜23時を個別評価する。
4. v14-r2とのdate/hour paired比較とblock bootstrapを使う。最新TEPCO MAEは昇格gateではない。
5. 一日だけを直す候補は却下し、28/56/84日replayと配備後固定originを併用する。
6. Challenger生成はshadowで再開可能だが、自動昇格は無効のままとする。

## 次回レビュー

P0修正とv15 replayが準備でき次第、技術レビューを開始する。測定基盤の修正を日付まで待つ必要はない。

配信契約と設定を変更しない場合、次の運用チェックポイントは確定実績が7日増える2026-09-10朝ETL後が適切である。配信動作を変更した場合は、その時点から新しい観測窓を開始する。

今回変更したのは文書のみであり、model artifact、config、guard、配布データは変更していない。
