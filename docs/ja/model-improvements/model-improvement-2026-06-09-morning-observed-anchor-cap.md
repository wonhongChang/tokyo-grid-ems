# 2026-06-09 午前の実績アンカー上限制御

## 問題

2026-06-09 のライブ予測では、午前後半の予測線が大きく上振れしました。

- 10時の実績は 30,690 MW で横ばいでしたが、公開されたモデル予測は約 32,081 MW まで上昇しました。
- 11時と12時も実績パスより高く、予測バンド下限からの逸脱が発生しました。
- 06:10 の intraday スナップショットは 10-12時にかなり近かった一方、07:30 の ETL 再生成後に、同日未来の予測線が十分な当日実績根拠なしに約 900-1,200 MW 上昇しました。

## 採用しなかった案

active-day の予測線が前回スナップショットから急変した場合に制限する drift limiter も検討しました。しかし、直近スナップショットで仮想検証したところ、2026-06-09 には有効でも、実際の午前 ramp が強い別の日では悪化リスクがありました。

そのため、予測線の移動そのものを制限する方式は採用しませんでした。

## 実装したレイヤー

`intraday_correction.morning_observed_anchor_cap` を追加しました。

このレイヤーは TEPCO 予測を追従しません。また、午前予測を一律に抑えるものでもありません。最後の当日実績がすでにモデルより低く、近い未来の予測が lag/recent shape で説明できる上限を超えた場合だけ、保守的に下方調整します。

## 作動条件

次の条件をすべて満たす場合だけ作動します。

- 営業日のみ対象。
- 最後の観測時刻が 08-12時。
- 最後の観測 residual がモデル比で -200 MW 以下。
- 対象時刻は 10-13時、lead time は4時間以内。
- 予測値が `最後の実績 + 累積 shape support + 250 MW` を超過。

`累積 shape support` は各時刻で次の大きい方を使います。

- `lag_24h_hourly_delta`
- `recent_same_business_type_delta_mean`

上限を超えた部分だけを 75% の shrinkage で削り、最大削減量は 800 MW です。

## 診断メタデータ

運用 calibration JSON に次のフィールドを残します。

- `morningObservedAnchorCapApplied`
- `morningObservedAnchorCapMaxReductionMw`
- `morningObservedAnchorCapReductionMw`
- `morningObservedAnchorCapMw`
- `morningObservedAnchorCapCumulativeSupportMw`
- `morningObservedAnchorCapLatestResidualMw`

AI 日次レポートの feature catalog にも `intraday_correction.morning_observed_anchor_cap` を追加しました。

## 検証

- 2026-06-09 午前後半の過大予測パターンを再現する回帰テストを追加しました。
- 最後の実績 residual が十分に負でない場合は作動しない no-op テストを追加しました。
- 対象テスト: `tests/test_intraday_correction.py` 通過。
