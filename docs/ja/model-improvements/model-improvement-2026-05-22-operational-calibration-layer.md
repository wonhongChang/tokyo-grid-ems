# 2026-05-22 運用補正レイヤー

> 深夜から早朝の予測を安定させるための構造的な post-processing レイヤーです。LightGBM 本体は変更せず、データソースの信頼度と residual 補正を分離します。

言語: [English](../../en/model-improvements/model-improvement-2026-05-22-operational-calibration-layer.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-22-operational-calibration-layer.md)

---

## なぜ必要だったか

以前の対応は、特定時間帯の失敗を抑えるために複数の guard を追加する形でした。日によっては有効でしたが、運用予測としては予測線がなぜ動いたのか説明しづらくなっていました。

2026-05-22 の深夜誤差は、より構造的な問題でした。

- 22:00-23:00 の実績は TEPCO API や Actions の遅延により翌朝まで欠けることがあります。
- その欠損行は lag 特徴量を維持するため、一時的に `tepco_forecast_fallback` で埋めます。
- fallback 値は lag 入力としては有用ですが、実測値ではありません。
- fallback を residual 観測として扱うと、深夜直前にモデルが合っていたように見える錯覚が生まれます。
- 00:00 になると当日の実測が少ないため、intraday 補正がほぼリセットされます。
- その間、モデルが過熱した `lag_24h` を信じすぎる可能性があります。

## 変更内容

intraday post-processing レイヤーの責務を三つに分けました。

1. ソースを認識した residual

`tepco_forecast_fallback` は lag 特徴量には引き続き使いますが、residual 補正からは除外します。リアルタイムの誤差補正は実測 observed actual のみで行います。

2. 日付境界 residual carry-over

新しい日の実測 observed が少ない場合、前日の最後の実測 residual を深夜に持ち越せます。fallback 時間はスキップし、経過時間に応じて急速に減衰させます。

3. 日単位スケール補正

当日の observed が十分に蓄積する前に、`lag_24h` が直近の同じ営業/非営業タイプ平均より過度に高く、かつ当日が前日より涼しいかを確認します。条件がそろう場合だけ、該当する未来時間に制限付きの下方 bias を適用します。これは LightGBM の特徴量追加ではなく、運用補正レイヤーです。

## 無効化した項目

有効設定では、以前の時間帯ベースの intraday guard をオフにしました。

- 昼時間帯 residual deweight
- shape guard
- ramp guard
- midday transition guard
- 午後専用 negative residual damping

コードパスはテスト可能なまま残しつつ、実運用パイプラインでは時間帯別パッチより source confidence と day-level scale calibration を優先します。

## デバッグメタデータ

各 intraday 実行では次のファイルを生成します。

`reports/internal/operational-calibration/YYYY-MM-DD.json`

含まれる内容:

- `source_confidence`
- `applied_regime_reason`
- `applied_day_bias`
- `forecast_build.stageSummary`
- `hourlyDiagnostics`
- residual carry-over メタデータ
- residual 計算から除外した fallback 数

`hourlyDiagnostics` には、時間別の実績、TEPCO予測、raw LightGBM、analog補正、guard後、intraday補正直前/直後の値を残します。これにより「なぜ深夜予測が跳ねたのか」「午前の過大予測がrawモデル由来か補正レイヤー由来か」を、ダッシュボードUIに内部診断を出さずに追跡できます。

lead-timeスナップショット(`forecast_snapshots/YYYY-MM-DD/*.json`)にも任意の `forecastBuild` ブロックを保存します。各実行時点のraw modelとpre-calibration予測線を保持するため、後から表示済み予測がどのように作られたかを確認できます。

## テスト

- fallback 行は residual 計算から除外されます。
- 日付境界 carry-over は fallback をスキップし、最後の実測 observed residual のみを使用します。
- day-level scale calibration は lag 過熱と cooler-day シグナルが同時にある場合だけ適用されます。
- internal calibration JSON は pre/post calibration とstage別forecastを時間別に記録します。
