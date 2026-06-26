# 2026-06-26 営業日 anchor cap の再調整

言語: [English](../../en/model-improvements/model-improvement-2026-06-26-business-day-anchor-cap-retuning.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-26-business-day-anchor-cap-retuning.md)

## 背景

2026-06-26 のライブ予測では、営業日の暖かい朝ランプ帯で上振れが再び確認されました。

- 09:00-11:00 JST は、当日の実績がすでにランプの鈍化を示していたにもかかわらず、モデル線が高止まりしました。
- raw LightGBM 線自体が高く、analogous-day / warm-day レイヤーが 10:00-14:00 周辺の水準を十分に抑えられませんでした。
- その後の intraday 実行では残りの将来時間を下方補正できましたが、すでに公開済みの朝スロットは freeze 方針により書き換えません。

TEPCO 値は誤差診断の外部基準としてのみ使用しました。モデル入力や補正には混ぜていません。

## 変更内容

### 朝の実績 anchor cap 強化

`intraday_correction.morning_observed_anchor_cap` は、最新の朝実績スロットで明確な過大予測が確認された場合、より強く作動します。

- `min_latest_overforecast_mw`: 500 -> 400
- `cap_buffer_mw`: 250 -> 0
- `shrinkage`: 0.75 -> 1.0
- `max_reduction_mw`: 800 -> 1000

当日実績に基づく条件は維持しつつ、過熱した 10:00-13:00 線が余分なバッファで残る問題を抑えます。

### 午後 anchor cap の緩やかな回復許容

`intraday_correction.afternoon_observed_anchor_cap.max_latest_slope_mw` を 500 MW/h から 900 MW/h に緩和しました。

従来値では、昼以降の実績が緩やかに回復しただけで午後 cap が無効になっていました。今後は、過大予測残差が明確であれば緩やかな回復中でも cap を維持し、非常に強い実需要ランプの場合だけ介入を避けます。

## 検証

以下の回帰テストを追加しました。

- 09:00 の観測残差が負である暖かい営業日朝に、10:00-13:00 をより明確に制限できること
- 昼以降の実績 slope は正でも、残差が引き続き過大予測を示す場合に午後 cap が作動すること

対象 intraday correction テスト:

```text
64 passed
```

## 運用メモ

この変更は TEPCO を追従せず、すでに公開された過去スロットも修正しません。当日実績によりモデルが高すぎると確認された後の次回 intraday 実行で、近距離の営業日 cap をより安定して適用するための調整です。
