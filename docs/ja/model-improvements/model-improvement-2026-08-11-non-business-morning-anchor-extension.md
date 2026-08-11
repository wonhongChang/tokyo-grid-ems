# 非営業日朝の実績Anchor拡張

言語: [English](../../en/model-improvements/model-improvement-2026-08-11-non-business-morning-anchor-extension.md) / [한국어](../../ko/model-improvements/model-improvement-2026-08-11-non-business-morning-anchor-extension.md)

## 現象

2026-08-11の山の日ではcalendarが非営業日経路を正しく選択したが、朝のraw q50が高かった。09時のpre-calibration需要は約33.0GW、実績は28.56GWだった。Intraday residual補正は全体の-1.2GW上限に達したが、近距離の将来予測に大きなoverhangが残った。

既存の`morning_observed_anchor_cap`は営業日専用だった。そのため週末・祝日では当日実績が過大予測を確認した後も、同等の最終近距離capを利用できなかった。

## 変更

既存anchor-cap controllerへ独立した`non_business_extension`設定を追加した。固定の週末shapeは作らず、raw LightGBM出力も変更しない。次の条件をすべて満たす場合だけ、残っている近距離運用補正を制限する。

- 対象日が週末または日本の祝日;
- 最新の有効実績が08時または09時;
- 最新model residualが少なくとも400MWの過大予測を確認;
- 対象が最大4時間lead以内;
- lag-24または直近同営業区分deltaが有効なshape経路を提供;
- 予測が最新実績と累積shape supportの合計より依然として高い。

超過分は0.75 shrinkageで減らし、最大減額を1,000MWに制限する。最新実績が09時を過ぎると拡張を終了し、後続の当日controllerへ引き継ぐ。

## 強いRampのVeto

週末・祝日にも実際の遅いrampが起こり得る。次の3条件をすべて満たす場合はcapを回避する。

- 最新実績slopeが4,000MW以上;
- 直近2実績slopeの平均が2,500MW以上;
- 累積lag/recent shape supportが2,500MW以上。

Replayでは実際のrampが強かった2026-08-08朝をこのvetoが保護した。

## Replay

2026-07-18〜2026-08-09の非営業日朝9日について、過去calibration snapshotから比較可能なforecast-hour 68件を復元した。

| 指標 | 既存 | 候補 |
|---|---:|---:|
| 朝snapshot MAE | 1,456.2 MW | 1,282.9 MW |
| MAE変化 | - | -173.3 MW (-11.9%) |
| 変更record | 0 | 13 |
| 最大減額 | 0 MW | 1,000 MW |

影響を受けた7月18日の1 recordはわずかに悪化した。全体誤差改善、少ない介入、減額上限、強いramp veto、早いhandoffを根拠に変更を採用した。すべての非営業日時間で改善するとは主張しない。

## 却下した代替案

- v13 Challengerは直近28日MAE 1,208.1MW、WAPE 3.256%で固定基準を超えたため昇格させなかった。
- 730日、548日、365日に短縮した学習期間は直近replayを悪化させた。
- q50 blendと営業日residual weightの変更は安定した改善を作れなかった。
- 全体intraday residual上限の拡大はraw予測回復後に大きなregressionを作った。
- 日付別条件、固定祝日offset、TEPCO予測calibrationは導入していない。

## 検証と範囲

- 別のband変更まで含むintraday/batch/interval集中test `155件`通過。
- メインworkspaceの全test `500 passed`。
- 公開artifact validatorと運用同等status生成を通過。
- v11 Champion、raw quantile model、平日昼休みロジック、昇格thresholdは変更していない。別のinterval floor変更は同日のband文書に記録した。
- 次回定期レビューは次の週末確定値が入る2026-08-17とする。
