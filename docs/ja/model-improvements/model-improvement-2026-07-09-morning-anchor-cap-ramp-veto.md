# 2026-07-09 朝 anchor cap ramp veto

言語: [English](../../en/model-improvements/model-improvement-2026-07-09-morning-anchor-cap-ramp-veto.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-09-morning-anchor-cap-ramp-veto.md)

## 背景

2026-07-08 の予測失敗は単発の spike ではなく、実績の朝 ramp が強まった後も、モデルが 09時以降の需要レベルを低めに見た問題でした。

確定評価:

| 指標 | モデル | TEPCO |
| --- | ---: | ---: |
| MAE | 376.3 MW | 172.9 MW |
| WAPE | 1.18% | 0.54% |
| RMSE | 441.1 MW | 231.9 MW |
| 優位時間 | 3 / 21 | 18 / 21 |

最大の shape miss は 08:00 -> 09:00 の遷移でした。実績は約 `+3,810 MW` 上昇した一方、モデルは約 `+2,542 MW` しか上昇しませんでした。その後 09:32 JST の intraday snapshot で `morning_observed_anchor_cap` が 09:00-12:00 をさらに押し下げましたが、当日実績 ramp がすでに強く確認されている局面では過剰な制御でした。

## 変更内容

`intraday_correction.morning_observed_anchor_cap` に保守的な `ramp_veto` サブルールを追加しました。

cap をスキップするのは、次の条件をすべて満たす場合だけです。

- 直近の当日実績 slope が非常に強い
- 直近2区間の平均実績 slope も非常に強い
- 対象時刻までの lag/recent shape の累積 support が十分にある
- 直近の over-forecast が小さく、深刻な過大予測が確定した局面ではない

運用デフォルト:

| Config key | 値 |
| --- | ---: |
| `min_latest_slope_mw` | 3000 |
| `min_mean_slope_mw` | 3000 |
| `min_cumulative_support_mw` | 2500 |
| `max_latest_overforecast_mw` | 650 |

## 期待効果

この変更は予測値を直接引き上げません。強い実績 ramp が確認され、lag/recent shape もそれを支持する場合に、morning anchor cap が ramp を誤って押し下げることだけを防ぎます。

2026-07-08 に近い状況では、06:00-08:00 の実績 ramp が高 slope regime を確認した後、09:00 と 10:00 bucket が morning cap によって追加で下げられません。一方、直近 over-forecast がすでに大きい場合は veto が無効になり、既存の cap 保護が維持されます。

## 検証

- `python -m pytest tests/test_intraday_correction.py -k "morning_observed_anchor_cap"`
- `python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py`
- `python -m pytest tests/test_ai_daily_report.py tests/test_daily_operation_report.py tests/test_feature_builder.py tests/test_lgbm_model.py`

結果:

- morning anchor cap targeted test `4 passed`
- intraday correction / adjustment `129 passed`
- report / feature-builder / LGBM `136 passed`

## メモ

この変更は TEPCO 予測値をモデル入力として使用しません。TEPCO は比較基準としてのみ維持します。veto 判断は当日実績需要 slope、lag/recent shape support、直近のモデル residual に基づきます。
