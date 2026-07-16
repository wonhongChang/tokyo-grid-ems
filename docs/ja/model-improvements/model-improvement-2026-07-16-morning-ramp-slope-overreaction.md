# 2026-07-16 朝 ramp slope 過反応ガード

言語: [English](../../en/model-improvements/model-improvement-2026-07-16-morning-ramp-slope-overreaction.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-16-morning-ramp-slope-overreaction.md)

## 背景

2026-07-16 のチャートでは、繰り返し問題になっていた 09:00 JST の跳ね上がりが再発しました。10:00-12:00 は実績に近かった一方で、09:00 だけが過大に上振れしました。

最終診断の主要行は次の通りです。

| 時刻 | 実績 | 補正前予測 | 誤差 | 予測増加幅 | lag24 増加幅 | 直近同営業タイプ増加幅 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 08:00 | 41,540 MW | 42,369.9 MW | +829.9 MW | +7,275.7 MW | +6,120.0 MW | +4,867.5 MW |
| 09:00 | 45,800 MW | 48,196.1 MW | +2,396.1 MW | +5,826.2 MW | +4,760.0 MW | +3,863.8 MW |
| 10:00 | 47,790 MW | 49,695.6 MW | +1,905.6 MW | +1,499.5 MW | +2,060.0 MW | +1,486.2 MW |

これは intraday 残差補正が 09:00 を押し上げた問題ではありません。raw/pre-calibration 段階で 08:00 -> 09:00 の ramp を過大評価していたことが主因です。既存の guard は当日実績が十分に入った後には機能しますが、09:00 のような観測前・観測直前に配信される shape spike には空白が残っていました。

## 変更

既存の `localized_shape_spike_guard.morning_spike` 経路を運用 config で有効化し、独立した `slope_overreaction` モードを追加しました。

新しいモードは、次の条件がすべて満たされる場合だけ作動します。

- 対象時刻が朝 ramp 帯（`08:00-10:00`）であること
- モデルの時間差分の上昇幅が大きいこと
- その上昇幅が lag/recent same-business の shape support を大きく上回ること
- 気温または不快指数の変化が warm-up regime を示すこと
- 一日全体を押し下げず、隣接予測時刻を基準に局所 cap を適用できること

運用 config:

```yaml
localized_shape_spike_guard:
  morning_spike:
    enabled: true
    hours: [8, 9, 10]
    neighbor_buffer_mw: 400
    shrinkage: 0.75
    max_reduction_mw: 1400
    slope_overreaction:
      enabled: true
      min_forecast_delta_mw: 4000
      min_forecast_delta_over_support_mw: 900
      min_weather_delta_c: 1.5
      min_discomfort_delta: 2.0
      max_weather_delta_c: 6.0
```

## 安全性

この guard は TEPCO 予測値を入力として使用しません。モデル自身の予測 slope、内部の lag/recent-business shape 信号、気象/不快指数の変化だけを比較します。

また、2026-07-15 のように 09:00 ramp は大きいものの実績に合っていた cooler morning の回帰テストを追加しました。気象/不快指数が warm-ramp 過反応を示さない場合、guard は作動しません。

## 検証

- `python -m pytest tests/test_adjustment.py tests/test_intraday_correction.py tests/test_run_batch.py -q`
- `python -m py_compile python\forecast\adjustment.py python\etl\run_batch.py`

結果:

- `191 passed`
