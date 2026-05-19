# 2026-05-19 予測スナップショットとshape診断

> intraday予測の問題を後から運用観点で分析できるようにするための追加改善記録。

言語: [English](../../en/model-improvements/model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-19-operational-snapshots-and-shape-diagnostics.md)

---

## なぜ追加したか

2026-05-19の問題は、単にMAEが悪いという話だけではなかった。重要だったのは次の問いだった。

> モデルは各更新時点で何を見ていて、なぜ公開予測線のshapeが変わったのか。

最新の `forecast/YYYY-MM-DD.json` だけを保持すると、現在のダッシュボード状態は分かるが、lead-timeごとの予測文脈は失われる。運用予測モデルとしては、更新時点ごとの予測履歴が必要になる。

---

## 変更内容

### 1. Lead-time予測スナップショット

ETLとintraday実行時に、制限付きの予測スナップショットを次の場所へ保存する。

```text
web/public/forecast_snapshots/YYYY-MM-DD/
```

各スナップショットには次を含める。

- target date
- 生成時刻
- 実行タイプ（`etl`、`intraday`、手動refresh系）
- モデル名/バージョン
- peakサマリー
- 時間別予測series全体
- 生成時点で利用できた実績時間数とTEPCO fallback時間数

保持範囲は意図的に制限している。

- `retention_days: 21`
- `max_per_day: 16`

直近の運用挙動を調べるには十分だが、data branchを無制限のデータベースにはしない。

### 2. Shape診断

daily operation reportに `shape` セクションを追加した。

次のhour-to-hour変化量を比較する。

- 実績需要
- 自モデル予測
- TEPCO予測

これにより、点ごとのMAEだけでは見えにくい問題、たとえば実績需要がほぼ変わっていないのにモデル予測線だけが数千MW急落するケースを検出できる。

### 3. Weather-delta診断

内部daily diagnosticsに次の要約を追加した。

- `coolingDelta24hByBand`
- `weatherDeltaRiskByBand`

24時間前比の気象変化特徴量が、朝/日中/夕方の各帯で役立っているのか、またはモデルを誤った方向へ引っ張っているのかを確認するための情報である。

### 4. Negative residual damping

intraday residual correctionは、正午以降の負のresidual補正を弱めるようにした。

一時的な正のモデル誤差を見て、近い将来の需要を過度に下げる動きを抑えるためである。直近未来の時間帯では、既存の双方向ramp guardも引き続き機能する。

---

## 安全メモ

- スナップショットはdata branch上の公開静的JSONだが、UIからは直接リンクしない。
- スナップショットは診断成果物であり、学習actualとして使わない。
- TEPCO forecast fallbackは、intraday実績がまだない時間帯に限って使用する。
- より強い特徴量を追加する前に、まず運用上の問題を再現・解釈できる土台を作る変更である。

---

## テスト

次を検証するテストを追加した。

- スナップショット保持数とindex生成
- スナップショットの実績/fallback時間数記録
- daily operation reportでの不自然なshape下落検出
- weather-delta内部診断サマリー
- 午後の負のresidual damping
