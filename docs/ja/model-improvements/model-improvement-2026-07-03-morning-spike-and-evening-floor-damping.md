# 2026-07-03 朝のスパイクと夜間 floor 減衰

Languages: [English](../../en/model-improvements/model-improvement-2026-07-03-morning-spike-and-evening-floor-damping.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-03-morning-spike-and-evening-floor-damping.md)

## 背景

2026-07-02 の配信予測では、別々の失敗モードが同時に見られた。

- 08:00 JST は営業日の朝 ramp-up を低く見積もった。
- その後、10:00-12:00 JST は朝の実績が入った後の補正が上方向に強く出すぎた。
- 20:00-23:00 JST は、実績と lag/recent shape がすでに下落しているにもかかわらず、`negative_residual_near_term_floor` が下方補正を戻しすぎて高く残った。

翌日の 2026-07-03 の事前観測予測でも、09:00 JST の単発スパイクが見えた。raw/analog 調整後の曲線が lag/recent shape の支持より大きく跳ね、その直後の 10:00 に下がる形だった。

この変更では TEPCO 予測を入力として使わない。TEPCO は外部ベンチマークとしてのみ扱う。

## 変更内容

### 朝の実績 ramp floor の shape 支持 cap

`intraday_correction.morning_observed_ramp_floor` に次の制御を追加した。

- `min_support_delta_mw`
- `support_delta_fraction`

強い朝の実績 ramp は引き続き保護する。ただし、対象時間の lag/recent shape がすでに横ばいまたは下落方向の場合、最新実績の傾きだけで次時間を過度に持ち上げない。2026-07-02 のように 09:00 実績は強いが、10:00-11:00 の shape 支持が十分ではないケースを対象にしている。

### 下落 shape を考慮した negative residual floor 減衰

`intraday_correction.negative_residual_near_term_floor` に `decline_support_damping` を追加した。

次の条件が同時に満たされる場合、floor が下方 residual 補正を戻す強度を下げる。

- 直近の当日実績 slope が明確にマイナス
- 対象時間の lag/recent shape も下落方向

これにより、夜間需要が実際に下がっている場面で、floor が予測線を無理に上へ戻す問題を抑える。2026-07-02 の 20:00-23:00 がこのケースだった。

運用スナップショットには次のフィールドを追加した。

- `negativeResidualNearTermSupportDeltaMw`
- `negativeResidualNearTermDeclineDampingFactor`

AI 運用レポートの compact fact packet にも同じ情報を含める。

### 事前観測の朝単発スパイク guard

`adjustment.localized_shape_spike_guard.morning_spike` を追加した。

この guard は、朝の対象時間が次の条件をすべて満たす場合だけ保守的に下げる。

- 前後の時間より突出した local peak
- forecast の増加幅が lag/recent shape 支持より過大
- 次の時間ですぐ大きく下がる
- 24時間の気象変化が上昇を十分に説明していない

2026-07-03 09:00 のように、当日実績がない状態で約 4.6GW 上昇し、10:00 に約 1.6GW 下がる形を抑えるための仕組みである。

## 検証

次の回帰テストを追加した。

- 朝の実績 ramp floor が対象時間の shape 支持を部分的にだけ反映すること
- 夜間下落 shape で negative residual near-term floor の復元量を減衰すること
- 観測前の営業日朝の単発スパイクを抑えること

対象テスト:

```powershell
python -m pytest tests/test_intraday_correction.py::test_intraday_observed_morning_ramp_floor_uses_fractional_support_and_skips_weak_targets tests/test_intraday_correction.py::test_intraday_near_term_floor_damps_restore_when_evening_shape_points_down tests/test_adjustment.py::test_localized_shape_spike_guard_dampens_business_morning_pre_observation_spike -q
```

結果: `3 passed`.

関連テスト:

```powershell
python -m pytest tests/test_intraday_correction.py tests/test_adjustment.py tests/test_ai_daily_report.py -q
```

結果: `155 passed`.

## 運用メモ

今回の変更は保守的な shape 制御である。TEPCO を追従するものではなく、すでに配信済みの予測値も書き換えない。

次に見るべき点は、朝 floor が本当に強い ramp-up 日を守りつつ、2026-07-02 の 10:00-12:00 の過剰 lift を繰り返さないかである。
