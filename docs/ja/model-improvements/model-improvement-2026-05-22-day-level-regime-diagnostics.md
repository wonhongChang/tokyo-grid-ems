# 2026-05-22 日単位lag/天気regime診断

> 特定時間帯のguardを追加する前に、寒冷化した日の全体曲線で前日高需要lagがどう作用したかを内部診断に残す改善記録。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-22-day-level-regime-diagnostics.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-22-day-level-regime-diagnostics.md)

---

## なぜ必要だったか

最近の予測ミスを07-10時だけの問題として扱うのは危険である。より大きな運用上の問いは、対象日が前日より大きく涼しいとき、モデルが前日の高需要 `lag_24h` の慣性から一日全体の曲線として十分に離れられるか、という点にある。

時間帯別のguardを増やし続けると、予測線がつぎはぎになりやすい。そのため、新しい補正や特徴量をすぐ追加する前に、内部診断JSONへ日単位のregime要約を記録するようにした。

---

## 変更内容

内部の日次診断に `diagnosticSummary.dayLevelRegime` を追加した。

- 一日全体のモデルbiasとMAE
- 平均 `lag_24h_to_same_business_type_gap`
- 直近同営業/非営業タイプ平均に対する `lag_24h` 過熱の平均と時間数
- 平均 `temp_delta_24h`
- 前日比の平均気温低下幅
- 平均 `cooling_delta_24h`
- 平均 `temp_anomaly_7d`
- 72時間の冷房慣性平均
- `cool_lag_overheat_regime` などのflags

これは診断専用であり、予測曲線そのものは変更しない。

---

## 期待される使い方

ETLが一日を確定した後、内部レポートで次をまとめて確認できる。

- 前日lagが直近同タイプ平均より高かったか
- 当日が前日より全体的に涼しかったか
- 冷房負荷が下がる条件だったか
- 72時間の熱慣性が残っていたか
- モデルが過大予測したか、過小予測したか

将来、時間帯をハードコードしない日単位のlag/天気interaction特徴量を入れるか判断する材料にする。

---

## テスト

内部診断テストを更新し、`dayLevelRegime` にlag・天気・flag項目が出力されることを確認する。

全体回帰テスト: `308 passed`
