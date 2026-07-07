# 2026-07-08 営業日の昼・夕方 Shape 制御の補強

## 背景

2026-07-07 の運用日は、営業日の需要カーブ全体に shape リスクが出たケースでした。日次レポートは 22:00 と 23:00 がまだ TEPCO forecast fallback 行だったため、比較可能な観測 22 時間を基準に集計されています。

観測スコア:

| 指標 | モデル | TEPCO |
| --- | ---: | ---: |
| MAE | 427.1 MW | 215.0 MW |
| WAPE | 1.43% | 0.72% |
| RMSE | 479.7 MW | 289.5 MW |
| 優位時間 | 5 / 22 | 17 / 22 |

主な誤差:

| 時間 | 実績 | モデル | 誤差 | 診断 |
| --- | ---: | ---: | ---: | --- |
| 12:00 | 33,630 MW | 34,420.9 MW | +790.9 MW | lag/recent の営業日 shape は下向きだったが、昼 dip の減衰が不足。 |
| 16:00 | 34,420 MW | 33,670.2 MW | -749.8 MW | 古い負の residual が最初の午後近未来枠を過度に押し下げた。 |
| 21:00 | 29,510 MW | 30,549.0 MW | +1,039.0 MW | 強い夕方下落局面で raw level が recent same-business anchor より高く残った。 |

## 変更内容

- 営業日 `midday_transition_guard` の `shrinkage` を `0.5` から `0.75` に強化。
  - 負の lag/recent shape 根拠がある場合だけ作動するため、固定的な昼 dip を作る制御ではありません。
- `negative_residual_near_term_floor.actual_reference_slack_mw` を `500` から `150` に縮小。
  - 古い負の residual が、最初の近未来時間帯を最新実績レベルより過度に低く押し下げることを防ぎます。
  - 実績がすでに強く下落し、lag/recent shape も下落を支持する場合は、既存の decline-support damping が復元量を制限します。
- `evening_decline_continuity_guard` の対象に 21 時を追加。
- 夕方 guard 内に `strong_decline_level_anchor` を追加。
  - `lag_24h_hourly_delta` と `recent_same_business_type_delta_mean` がともに強い夕方下落を示す場合、level-overhang cap が最新実績レベルではなく recent same-business anchor をより重視できます。
  - weather allowance は維持し、本当に暑い夕方需要を機械的に抑えないようにしています。

## 期待効果

2026-07-07 のスナップショットを使った近似 replay では:

- 16:00 の近未来過剰下方補正は約 `-750 MW` から約 `-390 MW` まで緩和。
- 21:00 の強い下落局面 overhang は約 `+1,039 MW` から約 `+560 MW` まで縮小。
- 12:00 は intraday 後ではなく事前 shape 段階で処理されるため、次回 forecast rebuild から強化された midday guard 設定が反映されます。

## 検証

- `python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py::test_midday_transition_guard_dampens_unsupported_noon_jump tests/test_adjustment.py::test_midday_transition_guard_uses_lower_recent_quantile_when_same_day_softens tests/test_adjustment.py::test_midday_transition_guard_does_not_use_quantile_without_same_day_softening -q`
- 結果: `79 passed`

## メモ

この変更では TEPCO 予測値をモデル入力として使用しません。TEPCO は比較ベンチマークとしてのみ扱います。制御根拠は当日実績 residual、recent same-business anchor、lag/recent shape delta、weather allowance です。
