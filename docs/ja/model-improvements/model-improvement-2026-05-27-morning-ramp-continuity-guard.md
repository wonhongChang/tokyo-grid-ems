# 2026-05-27 朝ランプ継続ガード
> 営業日の朝の需要上昇が実績で確認された後、負の残差キャリーオーバーが近い将来の予測線を不自然に下げることを抑える intraday ガードです。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md)

---

## 背景

2026-05-27 のライブ予測で、朝時間帯の shape risk が確認されました。

営業日の朝 ramp 区間では、当日実績需要が早い時間から強く上昇していました。しかし、過去時間帯の負の intraday residual 補正が近い将来の bucket に漏れ、次の予測時刻が不自然に下がるリスクがありました。

これは TEPCO 予測を追従する問題ではなく、補正制御の連続性の問題です。当日実績が強い上昇 ramp を示している場合、一時的な負の残差で近距離の予測曲線を壊さないようにする必要があります。

## 変更内容

intraday 補正レイヤーに `morning_ramp_continuity_guard` を追加しました。

このガードは raw LightGBM 予測を元の pre-calibration 値より上には引き上げません。直近の当日実績が強い朝 ramp を示す場合に限り、過剰に効いた負の残差の一部を戻し、近い将来の局所的な折れを緩和します。

評価条件は次の通りです。

- 当日が営業日であること
- base residual adjustment が負であること
- 連続した当日実績が3点以上あること
- 直近実績 slope が設定された ramp 基準を超えること
- 対象時刻が設定された朝時間帯に含まれること
- 対象時刻が近距離 lead-time の範囲内であること

## 運用パラメータ

デフォルト設定:

- `target_hours`: 6-11
- `min_reference_hour`: 7
- `max_lead_hours`: 2
- `min_recent_slope_mw`: 1000
- `min_mean_slope_mw`: 1000
- `floor_slope_fraction`: 0.25
- `max_floor_delta_mw`: 900
- `max_restore_mw`: 700
- `min_restore_mw`: 100

このガードは保守的に動作します。新しい需要を恣意的に追加せず、raw モデル線の範囲内で朝 ramp の局所的な連続性だけを保護します。

## 診断メタデータ

補正 metadata に次のフィールドを追加しました。

- `morningRampContinuityGuardApplied`
- `morningRampContinuityMaxRestoreMw`
- `morning_ramp_continuity_guard` (`appliedRegimeReason`)
- 時刻別 forecast delta、lag delta、same-day actual slope、residual adjustment、weather delta

## テスト

次の回帰テストを追加しました。

- 営業日の朝 ramp が強く確認された状況で、負の残差キャリーオーバーによる局所的な折れを緩和するケース
- 非営業日または上昇根拠が不足する状況ではガードが介入しないケース
