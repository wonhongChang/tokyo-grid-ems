# 異常検知基準

Languages: [English](../en/anomaly-criteria.md) / [한국어](../ko/anomaly-criteria.md)

Tokyo Grid EMS は、ダッシュボードで「なぜアラートが出たのか」を説明できるように、異常検知を三つのイベントに分けます。

| イベント | 目的 | 入力 |
|---|---|---|
| Reserve Risk | 供給余力が低下する時間帯を検知 | 使用率、供給力 |
| Spike / Drop | 予測外側の区間を外れた需要を検知 | 実績需要、予測区間 |
| Drift | 複数時間にわたるモデルバイアスを検知 | 実績-予測残差 |

しきい値は `config.yaml` の `anomaly` ブロックで管理します。

---

## 1. Reserve Risk

TEPCO の使用率がしきい値に達するとイベントを生成します。

| Severity | 条件 |
|---|---|
| 安定 | `usage_pct < 92.0` |
| warning | `92.0 <= usage_pct < 97.0` |
| 危険 (`critical`) | `usage_pct >= 97.0` |

このイベントは予測モデルの精度とは別に、電力需給KPI自体が危険域に入ったかを示します。

---

## 2. Spike / Drop

実績需要が予測区間の外側、つまり p99 範囲を外れたかを確認します。

| イベント | warning | critical |
|---|---|---|
| Spike | 実績が `p99Upper` を超過 | 実績が `p99Upper` を超え、超過幅が MW または % 基準以上 |
| Drop | 実績が `p99Lower` を下回る | 実績が `p99Lower` を下回り、超過幅が MW または % 基準以上 |

p95 だけを少し外れた場合は spike/drop イベントにしません。これは運用上の急騰/急落というより通常のモデルバンド誤差に近く、同じ方向に複数時間続く場合は drift 検知が別途拾います。

デフォルトの critical 基準:

```yaml
spike_drop:
  critical_breach_mw: 500
  critical_breach_pct: 2.0
```

ダッシュボード表示:

- Spike: `実績需要が予測範囲の上側を大きく外れました。`
- Drop: `実績需要が予測範囲の下側を大きく外れました。`
- 指標チップ: 実績、モデル予測、予測上限/下限

---

## 3. Drift

単一時間の急な誤差ではなく、複数時間にわたって同じ方向に蓄積する偏りを検知します。

計算手順:

1. 時間別の残差を計算します。
   - `residual = actual_mw - forecast_mw`
2. 残差に EWMA を適用します。
   - デフォルト `ewma_alpha = 0.3`
3. EWMA が基準値を連続時間以上超えると drift イベントを生成します。
   - デフォルト `threshold_mw = 800`
   - デフォルト `sustained_hours = 3`

| 方向 | 意味 |
|---|---|
| positive drift | 実績需要がモデル予測より継続的に高い |
| negative drift | 実績需要がモデル予測より継続的に低い |

Drift はモデルの継続的な補正必要性を示すシグナルであり、intraday residual correction とも関係します。

---

## 設計原則

- アラート文は短く保ちます。
- 数値は指標チップとして分離します。
- モデル誤差と需給リスクは別イベントとして扱います。
- `tepco_forecast_fallback` 行は実績ベースの異常判定から除外します。
- 運用基準はコードだけでなく config と文書で追跡します。
