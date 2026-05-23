# 2026-05-23 非営業日遷移補正
> 前日の営業日 lag が土曜/休日の予測線を過度に押し上げる場合の運用補正です。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-23-non-business-transition-calibration.md)

---

## 背景

2026-05-23 の土曜日予測では、週末フラグ自体は正しく入っていました。`is_weekend=1`、`is_non_business_day=1` は正常でしたが、raw LightGBM の予測線は平日型のカーブに近く見えました。

原因は `lag_24h` です。土曜日の24時間前 lag は金曜日の実績であり、最近の同時刻の非営業日平均より数千MW高い状態でした。この regime では、週末フラグがあっても Friday lag の慣性がモデルを上方向に引っ張ることがあります。

既存の intraday residual 補正も予測線を下げていましたが、金曜日 lag の影響を十分に取り除くには弱い状態でした。

## 変更内容

intraday 補正レイヤーに `business_type_transition` 補正を追加しました。

実測ベースの遷移補正は、以下の条件を満たす場合にのみ作動します。

- 対象日が非営業日である。
- 前日 lag と対象日の営業/非営業タイプが異なる。
- 当日の実測 residual がすでにモデルの過大予測を示している。
- `lag_24h` が最近の同じ非営業日平均より十分高い。
- 現在の予測が非営業日 anchor より設定された許容幅以上に高い。

補正は未来時間だけに適用されます。実測済みの時間や公開済みの過去予測線は変更しません。

## 深夜 prior

深夜から早朝の情報不足を補うため、別レイヤーとして `business_type_transition_prior` を追加しました。

このレイヤーは実測ベースの遷移補正よりかなり弱く、当日の有効実測数が通常の intraday 閾値に届かない場合だけ作動できます。また、`lastObservedHour >= 6` になると必ず無効になります。

デフォルト:

- `shrinkage`: 0.25
- `max_abs_bias_mw`: 500
- `lag_overheat_threshold_mw`: 1500
- `base_allowed_excess_mw`: 900

各未来時間の予測値が `recent_same_business_type_mean + base_allowed_excess_mw` を上回る場合だけ、弱く下方補正します。固定的な週末カーブではなく、金曜→土曜の lag 汚染を軽く抑える prior です。

## 運用上の意味

これは固定的な土曜日カーブではなく、TEPCO予測を目標値として使うものでもありません。プロジェクト自身の最近の同一営業タイプ anchor と当日の実測 residual だけを使います。

暖かい非営業日では、気温 anomaly と cooling degree に応じて許容幅を広げるため、実際に暑い週末需要を過度に抑えないようにしています。

## 診断メタデータ

運用補正 JSON には以下を記録します。

- `businessTypeTransitionPriorApplied`
- `businessTypeTransitionPriorBiasMw`
- `businessTypeTransitionApplied`
- `businessTypeTransitionBiasMw`
- `business_type_transition_prior_lag_overheat` (`appliedRegimeReason`)
- `business_type_transition_lag_overheat` (`appliedRegimeReason`)

これにより、週末/休日の予測線が通常の residual 補正で下がったのか、営業日→非営業日の遷移補正で下がったのかを追跡できます。

## テスト

前日の営業日 lag が非営業日 anchor より大きく、当日朝の実測 residual が過大予測を示している土曜日ケースの単体テストを追加しました。
