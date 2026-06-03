# 2026-06-03 予測区間の上側 tail 安定化

> q50 の需要予測線は変更せず、p95 上側バンドだけが過度に広がる稀なケースを抑える改善です。

Languages: [English](../../en/model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)

---

## なぜ必要だったか

2026-06-03 の intraday 予測では、q50 の予測線自体はおおむね妥当でしたが、ダッシュボード上の予測バンドが視覚的に不自然になりました。

問題は p95 上側に集中していました。

- 12:00 上側 half-width: 約 `+4,831 MW`
- 13:00 上側 half-width: 約 `+5,939 MW`
- 14:00 上側 half-width: 約 `+6,108 MW`
- 15:00 上側 half-width: 約 `+6,187 MW`

下側はかなり狭く、上方向だけが大きく開いた risk cone のように見える状態でした。スナップショットを比較すると、この変化は 11:14 JST の intraday 実行から始まっていました。

直前のスナップショットから異常スナップショットまでの間に、モデルファイルは変更されていません。大きく変わった入力は気象データでした。12:00-14:00 の将来気温が約 `21.0 C` から約 `18.0 C` に変わり、q50 モデルは小さく反応した一方で、独立した q975 モデルはこの気象 regime 変化を大きな上側 tail risk として解釈しました。

---

## 原因

Tokyo Grid EMS は q025、q50、q975 を別々の LightGBM quantile regressor として学習します。各 quantile が異なるリスク形状を学習できる利点がありますが、特定の入力組み合わせでは q975 が q50/q025 に比べて過度に広がることがあります。

既存の interval calibration は、バンドの潰れを防ぎ、片側の不確実性を反対側へそのままコピーしないようにしていました。しかし、気象 regime 変化後に上側 tail 自体が稀に暴走するケースを制限する仕組みは不足していました。

さらに forecast freeze により、この表示が残りやすくなっていました。評価の公平性のため観測済み時間帯の forecast を保存しますが、その際に異常な interval も一緒に保存されていたためです。

---

## 変更内容

共通の interval calibration helper を追加しました。

```text
python/forecast/interval_calibration.py
```

この helper は次を保証します。

- p95 最小 half-width の維持
- p95 最大 half-width の制限
- 上側/下側の非対称比率の制限
- 補正後の p95 幅を基準にした p99 区間の再構成

同じ補正を二つの段階に適用します。

- `LGBMForecaster.predict()`: 新しい q025/q50/q975 出力段階
- `build_forecast_json()`: forecast JSON 保存・スナップショット直前

運用設定は次の通りです。

```yaml
interval_calibration:
  min_p95_half_width_mw: 500
  max_p95_half_width_mw: 4500
  max_p95_asymmetry_ratio: 4.0
  asymmetry_reference_half_width_mw: 1000
  mirror_collapsed_side: false
```

---

## 期待効果

中心予測値(q50)は変更しません。不自然に広がる予測区間 tail のみを制限します。

2026-06-03 の再現ケースでは次のようになります。

| 時刻 | 適用前の上側 half-width | 適用後の上側 half-width |
|---|---:|---:|
| 12:00 | `+4,830.8 MW` | `+4,500.0 MW` |
| 13:00 | `+5,939.2 MW` | `+4,500.0 MW` |
| 14:00 | `+6,107.7 MW` | `+4,380.8 MW` |
| 15:00 | `+6,187.2 MW` | `+4,000.0 MW` |

不確実性は表示し続けながら、ダッシュボードが片側に過度な risk cone を表示することを防ぎます。

---

## テスト

次の回帰テストを追加しました。

- LGBM の raw quantile 出力で上側 interval が過度に広がるケース
- 既に生成済み、または freeze で保存された forecast point が JSON 直前で正規化されるケース

検証結果:

```text
369 passed
```
