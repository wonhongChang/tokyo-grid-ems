# 2026-07-18 下落shapeでの類似日上方補正cap

Languages: [English](../../en/model-improvements/model-improvement-2026-07-18-declining-analog-uplift-cap.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-18-declining-analog-uplift-cap.md)

## 背景

2026-07-17の最終レポートは実績21時間で集計されました。朝rampは良好でしたが、昼以降は広い区間で正のbiasが残りました。

| 区間 | モデルMAE | TEPCO MAE | 結果 |
| --- | ---: | ---: | --- |
| 00:00-20:00 | 835.0 MW | 510.5 MW | TEPCO優位 |
| 06:00-10:00 | 428.0 MW | 546.0 MW | モデル優位 |
| 11:00-15:00 | 1,087.6 MW | 1,084.0 MW | ほぼ同等 |
| 16:00-18:00 | 1,762.2 MW | 293.3 MW | 主な誤差区間 |

段階別snapshotでは、需要shapeの基準がすでに下落しているにもかかわらず、類似日補正が需要を上方へ追加していました。

| 時刻 | 実績 | Raw LGBM | 類似日補正後 | 類似日shift | 配信誤差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 15:00 | 44,390 | 47,149 | 47,603 | +454 | +680 |
| 16:00 | 44,060 | 47,378 | 48,316 | +939 | +1,652 |
| 17:00 | 42,570 | 44,657 | 45,213 | +556 | +1,443 |
| 18:00 | 41,490 | 43,723 | 44,085 | +363 | +2,191 |
| 19:00 | 40,250 | 42,525 | 43,616 | +1,092 | +1,266 |
| 20:00 | 38,210 | 40,236 | 40,724 | +488 | +685 |

これらの時間では`lag_24h_hourly_delta`と`recent_same_business_type_delta_mean`がともに横ばいまたは下落を支持し、当日も前日より暖かくありませんでした。Intraday補正は後から配信線を下げましたが、その前に不要な正の類似日shiftを相殺する必要がありました。

## 変更

`PostHolidayTimeBandGuard`に`business_declining_analog_uplift_cap`を追加しました。Raw LightGBM予測は下げず、類似日補正の正のshiftだけを制限します。

以下をすべて満たす場合だけ作動します。

- 営業タイプ遷移のない通常の連続営業日
- 対象時刻が13:00-20:00
- 正の類似日shiftが300 MW以上
- lag-24と最近の同営業タイプdeltaがともに+200 MW以下
- 気温・冷房deltaが0°C以下

全条件が成立した場合、類似日上方shiftを+100 MWに制限します。週末、休日遷移、より暖かい日、上昇shape、feature欠損時はbypassします。

また、重複していた`localized_shape_spike_guard.morning_spike`のYAML keyを統合しました。既存の08:00-11:00単独peakルールは維持し、08:00-10:00 slope過反応モードには独立したcap parameterを与え、YAML parseで消えないようにしました。

## Replay検証

保存済みの7月営業日calibration snapshotを使った段階別replayでは、13:00-20:00で条件に一致した行が12件ありました。

| 指標 | 変更前 | 変更後 |
| --- | ---: | ---: |
| 一致行MAE | 1,916.2 MW | 1,437.9 MW |
| 改善行 | - | 12 / 12 |

これは保存された再計算snapshotを使うstage-level replayであり、rolling backtestの代替ではありません。そのため作動条件を意図的に狭くしています。

## 2026-07-19予測確認

日曜日のため、この営業日guardによる24時間の変化はすべて0.0 MWです。現在のpeakは18:00の34,439.9 MWです。最近の暑い日曜日である2026-07-12も18:00-19:00に34,780-34,850 MWへ達しており、水準と夕方peak時刻は妥当な範囲です。

P95半幅は1.74-3.00 GWで、band inversionはありません。07:00-08:00の予測ramp（+3.54 GW）は最近の日曜日より急ですが、06:00-09:00の累積rampは2026-07-12に近い値です。実績根拠が入る前にhard capを追加せず、監視対象とします。

## 検証

- `python -m pytest tests/test_adjustment.py -q`
- リポジトリ全体test
- 統合した朝guardの運用config parse確認
- 最新`origin/data`によるlocal status-only再生成

TEPCO予測は評価基準にのみ使用し、このguardの入力には含めません。
