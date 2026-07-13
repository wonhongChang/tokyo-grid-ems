# 2026-07-13 非営業日の遅い朝 ramp floor 補強

言語: [English](../../en/model-improvements/model-improvement-2026-07-13-non-business-late-morning-ramp-floor.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-13-non-business-late-morning-ramp-floor.md)

## 背景

2026-07-10 から 2026-07-13 までを確認した結果、最も明確に対処すべき失敗は 2026-07-11 の土曜日でした。

公開データ基準の要約:

| 日付 | 判断 |
| --- | --- |
| 2026-07-10 | モデル MAE 383.8 MW、TEPCO MAE 375.0 MW。ほぼ同等で、朝の shape と 11時の過大予測が課題でした。 |
| 2026-07-11 | モデル MAE 639.3 MW、TEPCO MAE 316.7 MW。00-10時の過少予測が大きい明確な失敗でした。 |
| 2026-07-12 | モデル MAE 384.4 MW、TEPCO MAE 326.2 MW。12-14時の非営業日昼過大予測が主な課題でした。 |
| 2026-07-13 | 部分実績ではモデルがTEPCOを上回っており、広範囲の即時修正は不要でした。 |

2026-07-11 は土曜日の朝 ramp が遅く始まり、その後急激に立ち上がりました。

- 05:00 -> 06:00: +430 MW
- 06:00 -> 07:00: +2,430 MW
- 07:00 -> 08:00: +3,440 MW
- 08:00 -> 09:00: +3,250 MW

従来の `morning_observed_ramp_floor` は、直近2区間の slope が両方とも同じ閾値を超える必要がありました。週末のように生活・商業 ramp が遅れて立ち上がる日は、この条件が厳しすぎました。最初の slope は弱くても、最新 slope はすでに実需要の転換を示していたためです。

## 変更内容

`morning_observed_ramp_floor` の非営業日パスで、設定により最新実績 slope を floor の基準にできるようにしました。

運用設定は次の通りです。

| Config key | 値 |
| --- | ---: |
| `non_business_min_latest_slope_mw` | `2000` |
| `non_business_min_mean_slope_mw` | `1200` |
| `non_business_floor_basis` | `latest` |
| `non_business_floor_slope_fraction` | `1.0` |
| `non_business_max_lift_mw` | `700` |

ガードは引き続き狭く動作します。

- 当日実績が実際に入った後だけ作動
- `max_lead_hours` 以内の近い未来だけを保護
- 最新実績時間がすでに大きく過大予測されている場合は作動しない
- 対象時間の lag/recent shape support が必要
- 最終 lift は `non_business_max_lift_mw` で制限

## 週末ハードコードではない理由

このルールは土日を無条件に引き上げません。非営業日に当日実績が強い ramp をすでに示した場合だけ、floor 計算の基準を最新 slope に切り替えます。

今回のパッチでは 2026-07-12 の非営業日昼過大予測を広く抑える cap は追加していません。7/12 は 12-14時が高すぎる逆方向の問題であり、7/11 の過少予測と同じ強いルールで同時に解決しようとすると、実際の週末需要を抑えるリスクが高くなります。まず確認済みの遅い ramp 過少予測を補強し、昼の過大予測は別途観測対象として残す方が安全です。

## 観測性

時間別 residual 調整行に次のフィールドを追加しました。

- `morningObservedRampFloorBasis`

これにより、ramp floor が通常の `mean` slope 基準なのか、非営業日用の `latest` slope 基準なのかを追跡できます。

## 検証

- `python -m pytest tests/test_intraday_correction.py -k "weekend_morning_ramp_floor or observed_morning_ramp_floor"`

結果:

- `5 passed`

追加した回帰テストでは次を確認します。

- 2026-07-11型の遅い週末 ramp では近い時間だけ保守的に lift
- 2026-07-12型の弱い初期 ramp では latest-slope floor が作動しない
