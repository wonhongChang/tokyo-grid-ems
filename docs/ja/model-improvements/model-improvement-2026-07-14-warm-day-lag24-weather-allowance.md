# 2026-07-14 warm-day lag24 cap の気象許容幅補強

言語: [English](../../en/model-improvements/model-improvement-2026-07-14-warm-day-lag24-weather-allowance.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-14-warm-day-lag24-weather-allowance.md)

## 背景

2026-07-14 のライブ予測線では、朝から日中にかけて人工的な shape 断絶が発生していました。

- 09:00 は約 46.1GW と高いまま
- 10:00 は約 42.8GW まで強制的に下落
- 11:00-12:00 も低く抑えられる
- 13:00 は再び約 50.3GW へジャンプ

原因は intraday residual carryover ではありません。09:32 JST の calibration snapshot では residual 補正は約 -194MW にすぎませんでした。shape の断絶はその前段階の `PostHolidayTimeBandGuard` で発生していました。

根本原因は固定型の warm-day `lag24_warm_day_cap` です。

```text
max forecast = lag_24h + 2500 MW
```

この cap はモデルが暖かい日に過反応する場合には有効ですが、当日が前日より数度以上暑い場合には硬すぎます。2026-07-14 の朝は前日比の冷房 delta が約 +3.8C から +5.2C であり、08:00 実績もモデルより低くありませんでした。それにもかかわらず、固定 cap は涼しかった前日の需要を上限 anchor のように扱い、10-12時を不自然に押し下げました。

## 変更内容

warm-day lag24 cap に気象ベースの許容幅を追加しました。

```text
max forecast =
  lag_24h
  + lag24_warm_day_max_increase_mw
  + min(weather_delta_c * allowance_per_c, max_weather_allowance)
```

運用設定:

| Config key | 値 |
| --- | ---: |
| `lag24_warm_day_max_increase_mw` | `2500` |
| `lag24_warm_day_weather_allowance_mw_per_c` | `1200` |
| `lag24_warm_day_max_weather_allowance_mw` | `5000` |

気象 delta は、次の冷房関連シグナルの中で最も強い値を使います。

- `temp_delta_24h`
- `cooling_delta_24h`
- `apparent_cooling_delta_24h`

## 期待効果

前日よりかなり暑い営業日では、cap が 10-12時に偽の谷を作らなくなります。cap 自体は残るため極端な予測は制限できますが、上限は実際の冷房需要レジーム変化に合わせて広がります。

つまり既存の安全装置は維持しつつ、前日が当日の公平な上限 anchor ではない日に固定 lag 上限が予測線を壊さないようにします。

## 検証

- `python -m pytest tests/test_adjustment.py`

結果:

- `53 passed`

追加した回帰テストは 2026-07-14 のパターンを反映します。許容幅がない場合、10:00 予測は約 42.8GW 付近に抑えられますが、許容幅により raw/analog レベルを維持し、人工的な dip を作らないことを確認しました。
