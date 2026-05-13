# 異常検知基準

言語: [English](../en/anomaly-criteria.md) · [한국어](../ko/anomaly-criteria.md)

Tokyo Grid EMSでは、アラート理由をダッシュボードで説明できるように、異常検知を3種類のイベントに分けています。

| イベント | 目的 | 入力 |
|---|---|---|
| Reserve Risk | 供給余力が低い時間帯を検知 | 使用率、供給力 |
| Spike / Drop | 予測区間を外れた需要を検知 | 実績需要、予測区間 |
| Drift | 複数時間にわたるモデル偏りを検知 | 実績-予測残差 |

閾値は `config.yaml` の `anomaly` ブロックで管理します。

---

## Reserve Risk

使用率が基準に達した場合にイベントを生成します。

| Severity | 条件 |
|---|---|
| warning | `usage_pct >= 90.0` |
| critical | `usage_pct >= 95.0` |

ダッシュボードでは本文を短くし、使用率・基準・供給力はメトリックチップで表示します。

---

## Spike / Drop

実績需要が予測区間を外れたか確認します。

| イベント | warning | critical |
|---|---|---|
| Spike | 実績 > `p95Upper` | 実績 > `p99Upper` かつ超過幅がMWまたは%基準以上 |
| Drop | 実績 < `p95Lower` | 実績 < `p99Lower` かつ超過幅がMWまたは%基準以上 |

criticalの既定基準:

```yaml
spike_drop:
  critical_breach_mw: 500
  critical_breach_pct: 2.0
```

---

## Drift

Driftは単発の誤差ではなく、複数時間にわたる継続的な偏りを検知します。

手順:

1. `residual = actual_mw - forecast_mw` を計算します。
2. `ewma_alpha = 0.3` でEWMAを適用します。
3. EWMAが `threshold_mw = 800` を `sustained_hours = 3` 時間以上超えた場合にイベントを生成します。

正のdriftは実績がモデル予測より継続的に高い状態、負のdriftは継続的に低い状態を意味します。

---

## 設計原則

- アラート本文は短く保つ。
- 数値はメトリックチップに分離する。
- モデル誤差と供給リスクを別イベントとして扱う。
- `tepco_forecast_fallback` 行は運用予測入力には使うが、実績ベースの異常判定からは除外する。
- 閾値は検知ロジックではなくconfigで管理する。
