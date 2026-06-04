# 2026-06-04 朝の warm-lag 過反応ガード

> 暖かくなった営業日の朝に、raw モデルが lag/気象上昇シグナルを過大に反映し、当日実績がその水準を裏付けない場合に q50 を保守的に下げる intraday ガードです。

Languages: [English](../../en/model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md)

---

## 事象

2026-06-04 のライブ予測では、営業日の朝 ramp 区間で q50 が実績より高く出ました。これは 2026-06-03 に追加した予測区間 tail guard の問題ではありません。tail guard は p95/p99 のバンド幅を制限するだけで、q50 の中心線は変更しません。

raw LightGBM 予測は前夜からすでに高く、当日実績が入るにつれて intraday residual 補正は強い負方向になりました。ただし、すでに公開された時間帯は forecast freeze により保持されるため、画面上には過大予測が残りました。まだ閉じていない近い朝の予測には、lag/気象上昇シグナルが実績で確認されない場合の追加ブレーキが必要でした。

## 変更内容

intraday 補正レイヤーに `morning_warm_lag_overreaction_guard` を追加しました。

このガードは意図的に狭く動作します。

- 設定された朝の時間帯だけに適用します。
- 営業日コンテキストを要求します。
- 当日実績に基づく負の residual 補正が十分に大きい場合だけ作動します。
- `temp_delta_24h` や `cooling_delta_24h` などの warm-lag シグナルを要求します。
- 近い将来の時間帯だけを制御します。
- すでに観測済み、または freeze された公開予測線は書き換えません。

## 制御方式

対象時刻について、最新実績需要と clipping された当日朝 slope から上限を計算します。

post-calibration 予測線がその上限よりまだ高い場合、超過分の一部だけを cap の範囲で差し引きます。これは TEPCO 追従ではなく、raw モデルの過反応に対する遅いブレーキです。

主要設定:

```yaml
morning_warm_lag_overreaction_guard:
  enabled: true
  target_hours: [8, 9, 10, 11]
  min_base_adjustment_mw: 500
  min_temp_delta_24h_c: 2.0
  min_cooling_delta_24h_c: 0.8
  max_projected_slope_mw: 1800
  shrinkage: 0.75
  max_reduction_mw: 800
```

## 観測性

運用補正 JSON に次の項目を残します。

- `morningWarmLagOverreactionGuardApplied`
- `morningWarmLagOverreactionMaxReductionMw`
- `residualCarryoverByHour` の時間別 cap/reduction 値
- `appliedRegimeReason` の `morning_warm_lag_overreaction_guard`

Ops Report の fact packet にも新しいガードを feature catalog として追加しました。これにより AI レポートは q50 の warm-lag 過反応と予測バンド問題を区別できます。

## 検証

次の回帰テストを追加しました。

- 2026-06-04 に近い暖かくなった営業日の朝で、近い将来の q50 過大予測を下げること
- 負の residual はあるが warm signal が弱い朝では、ガードが作動しないこと
