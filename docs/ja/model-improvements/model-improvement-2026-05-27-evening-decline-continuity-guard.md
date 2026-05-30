# 2026-05-27 夕方下落継続ガード
> 当日の需要がすでに下落している局面で、近い将来の予測線が不自然に反発することを抑える intraday 補正ガードです。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md)

---

## 背景

2026-05-27 のライブ予測で、夕方時間帯の shape risk が確認されました。

17時時点で実績需要は前時間から大きく低下していました。当日の実績傾き、`lag_24h_hourly_delta`、直近の同一営業日タイプの変化量も、維持または低下方向を示していました。しかし、18時のモデル予測は大きく反発しました。

この時点の intraday residual carry-over は小さく、主因は residual の暴走ではありません。raw モデル線と daytime warm-day guard が、実際の夕方下落が確認された後も近い将来の反発を許容していたことが主なリスクでした。

## 変更内容

intraday 補正レイヤーに `evening_decline_continuity_guard` を追加しました。

このガードは TEPCO 予測を追従せず、18時だけをハードコードして抑えるものでもありません。当日の実績が明確な夕方下落を示し、内部の shape シグナルも反発を支持しない場合に限り、近い将来の過剰な反発幅を制限します。

評価条件は次の通りです。

- 最新の実績時刻が設定された夕方基準時刻以降であること
- 最新の当日実績 slope と直近平均 slope が明確にマイナスであること
- 対象時刻が近い将来の forecast bucket であること
- `lag_24h_hourly_delta` と `recent_same_business_type_delta_mean` が上昇を支持していないこと
- 直前の最終予測値からの forecast rebound が設定しきい値を超えること
- 天候 allowance を含めても上限 buffer を超える反発であること

2026-05-29 にはもう一つの夕方失敗パターンも確認されました。予測線は直前値から反発していないものの、当日の実績需要がすでに低下しているのに近い将来の予測レベル自体が高く残っていました。そのため `level_overhang` 経路を追加しました。この経路は最新実績需要と同一営業日タイプの anchor を基準レベルとして使い、許容 buffer を超える部分だけを次の1-2個の forecast bucket で保守的に削ります。

## 運用パラメータ

デフォルト設定:

- `target_hours`: 16-20
- `min_reference_hour`: 15
- `max_lead_hours`: 2
- `latest_slope_max_mw`: -500
- `mean_slope_max_mw`: -300
- `max_supporting_delta_mw`: 200
- `min_forecast_rebound_mw`: 800
- `max_rebound_mw`: 600
- `actual_reference_slack_mw`: 300
- `weather_allowance_mw_per_c`: 120
- `hot_temp_c`: 30.0
- `max_weather_allowance_mw`: 400
- `max_reduction_mw`: 900
- `min_reduction_mw`: 100
- `level_overhang_enabled`: true
- `min_level_overhang_mw`: 500
- `level_overhang_shrinkage`: 0.75

このガードは保守的に動作します。予測線全体を強制的に下げるのではなく、許容可能な反発幅またはレベル過熱の超過分だけを削ります。暑い夕方の実需要増加を過度に抑えないよう、天候 allowance も残しています。

## 診断メタデータ

補正 metadata に次のフィールドを追加しました。

- `eveningDeclineContinuityGuardApplied`
- `eveningDeclineContinuityMaxReductionMw`
- `evening_decline_continuity_guard` (`appliedRegimeReason`)
- `residualCarryoverByHour` の時刻別 cap、mode、rebound、weather allowance、reduction 情報

運用 calibration snapshot summary にもガード状態を記録し、日次レポートで夕方予測線がなぜ制限されたかを追跡できるようにしました。

## テスト

次の回帰テストを追加しました。

- 2026-05-27 型の夕方下落ケースで、18時の異常な反発を制限するケース
- 2026-05-29 型の level-overhang ケースで、ローカルな反発がなくても近い将来の高い夕方レベルを制限するケース
- lag と同一営業日タイプの shape が実際の反発を支持している場合は、ガードが介入しないケース
