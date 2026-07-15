# 2026-07-16 夕方 ramp drop cap の再調整

## 背景

2026-07-15 の予測は朝から日中ピークまでは概ね許容範囲だったが、夕方区間で後処理の問題が明確に出た。

観測済み時間だけで集計した指標:

| 区間 | モデル MAE | TEPCO MAE | メモ |
| --- | ---: | ---: | --- |
| 全観測区間 | 503.9 MW | 438.6 MW | モデルが小幅に劣後 |
| 05:00-12:00 | 456.3 MW | 555.0 MW | 朝ブロックはモデル優位 |
| 17:00-20:00 | 1,038.6 MW | 500.0 MW | 主な失敗区間 |

最大の誤差は 18:00 JST だった。

| 時刻 | 実績 | モデル | 誤差 | TEPCO |
| --- | ---: | ---: | ---: | ---: |
| 17:00 | 46,980 MW | 48,080 MW | +1,100 MW | 47,390 MW |
| 18:00 | 44,940 MW | 47,080 MW | +2,140 MW | 45,780 MW |

これは raw LightGBM の spike ではなかった。18:04 JST の運用補正スナップショットでは、18:00 の pre-calibration 予測は 45,687.2 MW で、最終実績にかなり近かった。しかし最終段の `ramp_guard` が 16:00 実績を基準に近距離の下限を強く適用し、配信線が 47,080 MW まで押し戻された。

## 変更内容

最終 ramp drop cap の緩和経路を再調整した。

```yaml
ramp_guard:
  observed_drop_relaxation:
    min_recent_drop_mw: 500
    decline_support:
      min_lead_hours: 1
      max_support_delta_mw: -900
      max_decrease_mw_by_lead_hour: [2600, 4800, 6500]
```

保守性は維持している。

- 当日実績需要がすでに意味のある下落を始めていること。
- 対象時間の `lag_24h_hourly_delta` と `recent_same_business_type_delta_mean` がともに下落を支持していること。
- TEPCO 予測値を入力には使わず、最終 drop cap の許容幅だけを広げること。

## 再現結果

2026-07-15 18:04 JST スナップショットを新設定で再現した結果:

| 時刻 | 旧配信線 | 再調整後 | 最終実績 |
| --- | ---: | ---: | ---: |
| 17:00 | 48,080.0 MW | 47,094.7 MW | 46,980 MW |
| 18:00 | 47,080.0 MW | 45,620.2 MW | 44,940 MW |
| 19:00 | 46,080.0 MW | 45,225.6 MW | 43,560 MW |

新設定は、予測線を 16:00 実績付近へ無理に戻さず、確認済みの夕方下落を保持する。

## 検証

- `python -m pytest tests/test_intraday_correction.py -k "ramp_guard_relaxes_drop_cap or supported_evening_decline or ramp_guard_keeps_drop_cap or observed_demand_drop" -q`
- `python -m py_compile python\forecast\intraday_correction.py python\etl\run_batch.py`

結果:

- `4 passed`

## メモ

今回の変更は新しいモデル特徴量ではなく、後処理の安全装置の再調整である。当日実績と対象時間の shape 信号がともに夕方下落を支持する場合に、最後の ramp cap が妥当な下落経路を押し戻す問題を抑える。
