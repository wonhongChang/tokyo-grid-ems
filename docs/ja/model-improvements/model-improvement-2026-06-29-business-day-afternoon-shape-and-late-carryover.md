# 2026-06-29 営業日の午後 shape と夜間 carryover 補正

言語: [English](../../en/model-improvements/model-improvement-2026-06-29-business-day-afternoon-shape-and-late-carryover.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-29-business-day-afternoon-shape-and-late-carryover.md)

## 背景

2026-06-29 の営業日予測では、複数の後処理段階が連鎖して shape が崩れる問題が確認された。

- 09:00 JST は、08:00 の実績ですでに過大予測が見えていたにもかかわらず十分に抑制されなかった。
- 13:00-16:00 JST は、暖かい営業日の午後にもかかわらず、analog 段階の過度な下方シフトを受けて低く出た。
- 21:00-22:00 JST は、午後の過小予測で増えた正の residual が夜間まで carryover され、高めに残るリスクがあった。

TEPCO 予測は外部ベンチマークとして診断にのみ使う。モデル入力や補正ロジックは TEPCO 予測を利用しない。

## 変更内容

### 09:00 の morning anchor 保護

`intraday_correction.morning_observed_anchor_cap.target_hours` に `9` を追加した。

08:00 実績で過大予測が確認できた場合、10:00 まで待たずに次の 09:00 bucket も保護できる。

### 営業日午後の analog 下方シフトガード

`adjustment.post_holiday_timeband_guard.business_afternoon_analog_downshift_guard` を追加した。

暖かい営業日の午後に、lag/recent shape が明確な低下を支持していないにもかかわらず analog 段階が forecast を大きく下げる場合、その下方シフトを制限する。今回のように raw LGBM の方が後続実績に近いのに、analog 段階が 14:00-15:00 を過度に下げたケースを対象にする。

### 昼間の過小予測 lift が最新 residual に反応

`intraday_correction.daytime_sustained_underforecast_lift` を調整した。

- 対象時間を 15:00-16:00 まで拡張
- 営業日では最新 residual が大きい場合、単発の強い miss でも保守的に反応可能
- post-midday shape gate は 12:00-13:00 に絞り、暑い午後の回復を妨げにくくした

### 夜間の正 residual carryover damping

`intraday_correction.afternoon_positive_residual_carryover_damping` を 20:00-22:00 まで拡張し、参照時間を 19:00 まで見るようにした。

午後の過小予測で発生した正の residual が、lag24/recent shape がともに低下を示す夜間まで機械的に伝播することを抑える。

## 検証

以下の回帰テストを追加した。

- 営業日の warm afternoon analog 下方シフト制限
- 実際に強い下降根拠がある場合は analog 下方シフトを維持
- 09:00 observed anchor cap
- hot business afternoon の最新 residual による daytime lift
- 夜間の正 residual carryover damping

検証コマンド:

```powershell
python -m pytest -q
```

結果: `422 passed`.

## 運用メモ

このパッチは TEPCO を追従するためのものではない。内部の後処理段階が当日実績や lag/recent shape の文脈と衝突した場合にのみ、過度な移動を抑える保守的な防御線である。

次の暑い営業日午後で確認する点:

- 13:00-16:00 が analog downshift で過度に押し下げられないか
- 21:00-22:00 が午後の正 residual を過度に引きずらないか
- 09:00 anchor cap が本物の morning ramp を平坦化しすぎないか
