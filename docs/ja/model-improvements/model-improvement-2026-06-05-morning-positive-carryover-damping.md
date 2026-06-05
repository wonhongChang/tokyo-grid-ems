# 2026-06-05 朝の正の残差 carryover 減衰

## 問題

2026-06-05 のライブ予測では、前日の warm-lag 過反応とは別の失敗パターンが確認されました。

- 07:00-08:00 の実績需要がモデル予測より速く上昇した。
- Intraday 補正はこの過少予測を正の残差信号として扱った。
- その正の残差が 10:00-13:00 まで機械的に持ち越され、ランプアップが弱まる時間帯まで予測線を押し上げた。
- 後続実行では過大予測を検知して残差が負方向に転じたが、10:00-11:00 の公開済み予測線は published forecast freeze により画面上に残った。

## 変更

`intraday_correction` に `morning_positive_residual_carryover_damping` レイヤーを追加しました。

このガードは raw LightGBM 予測を直接書き換えません。次の条件が同時に成立する場合のみ、正の intraday carryover を減衰します。

- 営業日の朝コンテキスト、
- 強い当日実績ランプにより正の残差が発生、
- 対象時刻が 10:00-13:00、
- 対象時刻が少なくとも 2 時間先の近距離未来、
- `lag_24h_hourly_delta` と `recent_same_business_type_delta_mean` が強い上昇ランプを支持していない。

## 運用上の効果

朝の早い時間帯の過少予測が、昼前後の plateau/dip 時間帯へ機械的に伝播することを抑えます。一方で、対象スロット自体に強いランプアップ根拠がある場合は介入しません。

## 診断メタデータ

運用補正スナップショットに以下を追加しました。

- `morningPositiveResidualCarryoverDampingFactor`
- `morningPositiveResidualCarryoverDampedMw`
- `morningPositiveResidualCarryoverSupportDeltaMw`

AI 運用レポートの fact packet にもこの信号を含め、raw モデル誤差、residual carryover の過伝播、published freeze の影響を分けて説明できるようにしました。

## 検証

- 2026-06-05 型ケースの回帰テストを追加。
- 強いランプ根拠がある場合は減衰しない bypass テストを追加。
- `tests/test_intraday_correction.py`: 41 passed.
