# 2026-08-11 運用モデルレビュー

言語: [English](../../en/model-reviews/model-review-2026-08-11.md) / [한국어](../../ko/model-reviews/model-review-2026-08-11.md)

レビュー日: 2026-08-11 JST

根拠範囲: 2026-08-10までの確定実績と2026-08-11午前のintraday観測

状態: 完了

## 決定

- v11 `lag24_residual_ensemble` Championを維持する。
- 現在のv13 Challengerは昇格させない。補助84日検証は通過したが、直近28日のMAE、WAPE、昼間segment基準に失敗した。
- 独立した運用変更を二つだけ採用する。非営業日朝の実績anchor capを限定的に拡張し、別のband replayを通過したleakage-safeなrolling conformal最小幅を追加する。
- q50 feature、学習期間、raw quantile model、平日昼休みロジック、全体intraday上限は変更しない。最小幅補正は公開band幅だけを変更する。
- TEPCO予測は外部benchmarkとしてのみ使用し、入力、anchor、target、calibration値には使用しない。

## データ整合性

| 確認 | 結果 | 根拠 |
|---|---|---|
| 確定実績coverage | 通過 | `actual/2026-08-10.json`に観測24時間が存在 |
| 実績source | 通過 | `tepco_forecast_fallback`を確定実績として評価していない |
| Calendar path | 通過 | 2026-08-11は山の日で`is_holiday=1`、`is_non_business_day=1` |
| 祝日guard分離 | 通過 | 営業日専用q50と`MiddayTransitionGuard`は非作動 |
| 気象入力 | 通過 | 8月11日朝のmissを説明するNaNや異常なsource遷移なし |
| 公開artifact | 通過 | status、actual、forecast、report、promotionファイルを検証 |

8月11日は進行中のため日次最終性能から除外した。午前snapshotはstage attributionと候補動作の確認にだけ使用した。

## 直近の運用性能

各確定日に実際に公開されたserved forecastを評価した。

| 日付 | 区分 | MAE MW | WAPE | RMSE MW | Bias MW | 最大誤差 MW | TEPCO MAE MW |
|---|---|---:|---:|---:|---:|---:|---:|
| 2026-08-05 | 営業日 | 643.3 | 1.85% | 762.6 | -223.7 | 1,731.4 | 347.5 |
| 2026-08-06 | 営業日 | 960.4 | 2.57% | 1,219.8 | -897.5 | 3,234.7 | 308.8 |
| 2026-08-07 | 営業日 | 1,119.1 | 2.85% | 1,364.1 | -374.6 | 3,829.9 | 272.1 |
| 2026-08-08 | 週末 | 853.4 | 2.44% | 1,125.2 | +654.8 | 2,570.0 | 334.6 |
| 2026-08-09 | 週末 | 1,362.9 | 4.24% | 1,626.7 | +1,344.2 | 3,111.1 | 517.5 |
| 2026-08-10 | 営業復帰 | 1,730.2 | 5.30% | 2,113.3 | +1,721.4 | 4,929.9 | 578.8 |

8月6〜7日の営業日での過小予測が、8月9〜10日の非営業日・営業復帰日では過大予測へ反転した。単一の全体level offsetではなくregime問題である。q50全体の移動やintraday上限拡大は、一方向を改善する代わりに反対方向を悪化させる。

## 28日運用Replay

期間: 2026-07-14〜2026-08-10、実際のserving 672時間。

| Segment | MAE MW | WAPE | RMSE MW | Shape delta MAE MW |
|---|---:|---:|---:|---:|
| 全体 | 890.1 | 2.399% | 1,182.1 | 705.0 |
| 営業日 | 889.4 | 2.328% | 1,199.4 | 729.6 |
| 非営業日 | 891.6 | 2.564% | 1,144.8 | 653.0 |
| 朝 | 970.2 | 2.618% | 1,295.7 | 997.6 |
| 昼間 | 960.4 | 2.111% | 1,231.4 | 725.8 |
| 午後遅め | 1,152.8 | 2.654% | 1,529.7 | 898.3 |

運用後処理を含むserved forecastはraw snapshot経路より良いが、朝と午後遅めのshapeは依然として最もリスクの高い区間である。

## Challenger検証

同じv13契約を各holdout開始前のデータだけで学習した。

| 期間 | MAE MW | WAPE | RMSE MW | 最大誤差 MW | Shape delta MAE MW | 決定 |
|---|---:|---:|---:|---:|---:|---|
| 直近28日 | 1,208.1 | 3.256% | 1,532.8 | 5,050.8 | 628.3 | 却下 |
| 補助84日 | 790.6 | 2.526% | 1,114.5 | 5,432.4 | 481.3 | 補助viewのみ通過 |

直近28日のsegment MAEは営業日1,290.7MW、非営業日1,033.6MW、昼間1,549.4MWだった。昼間は固定1,500MW上限を超え、全体MAEとWAPEも1,000MWと3.0%の基準を超えた。長期平均で直近の失敗を相殺してはならない。

学習期間を730日、548日、365日に縮める実験、q50 blend変更、営業日residual weight変更は安定した直近改善を作れず却下した。

## 平日Lunch Dip監査

Chartの12時bucketは12:00〜13:00需要である。8月5日、6日、7日、10日の実績11→12時変化は+60、+40、-550、-290MWで、raw model変化は-1,014.4、+608.5、-111.5、-1,209.6MWだった。

4日とも`MiddayTransitionGuard`の追加補正は`0 MW`だった。3日はraw modelにすでに下落shapeがあり、2日は実績11→12時の下落自体がなかったため正しい動作である。平日という理由だけで固定lunch dipを作ってはならない。昼休み関連parameterは変更しなかった。

## 2026-08-11 祝日診断

Calendarとguard routingは正常だったが、朝のraw q50 levelが高かった。09時のpre-calibrationは約33.0GW、実績は28.56GWだった。Intraday residual補正は-1.2GW上限に達したが、近距離の将来予測にはoverhangが残った。

既存のobserved morning anchor capは営業日専用だった。そのため週末・祝日では当日過大予測の証拠が明確でも、追加の近距離level capを使えない空白があった。原因は祝日flag欠落や平日昼休みguardの誤作動ではない。

## 採用した運用変更

`morning_observed_anchor_cap.non_business_extension`は次の条件でのみ作動する。

- 週末または祝日の予測;
- 最終実績時刻が08時または09時の場合のみ;
- 最新model residualが少なくとも400MWの過大予測を示す;
- lag-24または直近同営業区分shapeが支える対象時刻のみ;
- 最大lead 4時間、最大減額1,000MW;
- hard clampではなく0.75 shrinkage;
- 最新実績ramp 4,000MW以上、直近2区間平均2,500MW以上、累積shape support 2,500MW以上ならveto;
- 最終実績が09時を過ぎると自動終了。

このlayerはTokyoGridEMSのmodel出力、確定需要履歴、当日のTEPCO実績需要、calendar、内部lag/shape featureだけを使用する。TEPCO予測値は参照しない。

## 候補Replay

2026-07-18〜2026-08-09の非営業日朝9日について、過去calibration snapshotから比較可能なforecast-hour 68件を復元した。

| 指標 | 既存 | 候補 | 結果 |
|---|---:|---:|---|
| 朝snapshot MAE | 1,456.2 MW | 1,282.9 MW | -173.3 MW (-11.9%) |
| 変更record | 0 | 13 | 限定介入 |
| 最大減額 | 0 MW | 1,000 MW | 設定上限を遵守 |
| 2026-08-08の実際の急激なramp | 保持 | 保持 | Ramp veto作動 |

影響を受けた2026-07-18の1 recordはわずかに悪化した。そのため全時間で必ず改善すると表現しない。全体改善、少ない介入数、hard cap、強いramp veto、09時以降のhandoffを根拠に、model昇格ではなく運用guardとしてのみ採用する。

## 予測Band監査

直近28日のp95 coverageは全体93.8%、非営業日90.7%、朝89.3%、昼間91.4%、午後遅め89.3%、夕方99.3%だった。

別の因果的walk-forward実験で、直前の確定28日における絶対誤差の有限標本95%分位点を営業レジームと時間帯で分け、最小半幅としてのみ適用した。全体coverageは95.8%、非営業日は95.8%、朝は94.3%、昼間は95.7%へ改善した。平均半幅は144.6MW増え、既存の3,000MW最大値は維持した。対象日、fallback実績、TEPCO予測は入力から除外する。

午後遅めは上限でも90.5%までしか改善せず、band幅より中心予測とshapeの問題であることを確認した。夕方は99.3%のovercoverageを維持し、安全な最小幅policyは既存bandを狭めない。

## 検証

- intraday、batch、intervalの集中test `155件`通過。
- メインworkspaceの全test `500 passed`。
- 公開artifact validator通過。
- 運用同等の`run_batch.py --status-only`完了。
- v11 Champion artifactと昇格thresholdは変更なし。

## 残存リスクと次回レビュー

- 実績根拠が蓄積する前、またはすでにfreezeされた時刻はこの拡張では修復できない。
- 8月11日の最終評価は8月12日のETL後に実施し、進行中の日を今回の判断へ事後追加しない。
- 午後遅めのp95 coverageは依然として基準未達である。3,000MWより広いbandで隠さず、中心予測とshapeを改善する必要がある。
- 夕方のovercoverageは、運用幅を狭める前に別の両側縮小実験が必要である。
- 次回定期レビューは次の週末実績が確定する2026-08-17 JSTとする。それ以前は決定的なdata、calendar、pipeline不具合だけを即時修正する。
