# JSONスキーマ仕様 (Dashboard Contract)

言語: [English](../en/json_schema.md) · [한국어](../ko/json_schema.md)

GitHub Pages（静的ダッシュボード）が直接読み込む**静的JSON出力物の契約**です。
ETL/バッチパイプラインはこのスキーマに従い `web/public/` 以下のファイルを生成します。

> 原則
> - 日付別出力物は **UTCではなくAsia/Tokyo(JST)** 基準の日付（`YYYY-MM-DD`）を使用します。
> - 欠損・未評価状態は値 `null` または明示的な `status` フィールドで表現します。
> - スキーマはMVPで固定し、データ拡張時も**変更しない**ことを目標とします。

---

## ファイル一覧
- `web/public/status.json`
- `web/public/alerts/YYYY-MM-DD.json`
- `web/public/forecast/YYYY-MM-DD.json`
- `web/public/forecast_snapshots/YYYY-MM-DD/index.json`
- `web/public/forecast_snapshots/YYYY-MM-DD/*.json`
- `web/public/actual/YYYY-MM-DD.json`
- `web/public/metrics/forecast_accuracy.json`
- `web/public/metrics/model_backtest.json`
- `web/public/reports/internal/operational-calibration/YYYY-MM-DD.json`

---

## 共通ルール
- 危険度/重要度は全出力物で `severity`（info|warning|critical）に統一します。

## 共通型定義

### Timestamp
- ISO 8601文字列、**バッチ出力物ではtimezone(+09:00)を実質必須として推奨**
  - 例: `2025-12-01T18:00:00+09:00`

### Severity
- `"info" | "warning" | "critical"`

### DataAvailability（ダッシュボード状態表現）
- `"ok"`: 正常処理完了
- `"missing"`: 未収集・未処理（バッチ欠落など）
- `"failed"`: 試行したが失敗（パース/品質ゲート/入力エラーなど）
- `"not_yet_available"`: 提供遅延（正常範囲の可能性あり）

---

# 1) status.json

## 目的
ダッシュボード上部に表示する**現在の状態（Last Updated / 結果サマリー）**および概要KPIを提供。

## パス
`web/public/status.json`

## スキーマ
```json
{
  "project": "tokyo-grid-ems",
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",

  "lastUpdatedAt": "2025-12-02T07:05:12+09:00",
  "coverageTo": "2025-12-01",

  "availability": "ok",
  "missingDays": ["2025-11-23"],
  "failedDays": ["2025-11-24"],

  "latest": {
    "date": "2025-12-01",
    "peakActualMw": 58230.0,
    "peakActualAt": "2025-12-01T18:00:00+09:00",
    "peakUsagePct": 96.2,
    "peakSupplyMw": 61000.0
  },

  "yesterday": "2025-12-01",

  "today": {
    "date": "2025-12-02",
    "peakForecastMw": 57500.0,
    "peakForecastAt": "2025-12-02T18:00:00+09:00",
    "severity": "warning"
  },

  "tomorrow": {
    "date": "2025-12-03",
    "peakForecastMw": 56000.0,
    "peakForecastAt": "2025-12-03T18:00:00+09:00",
    "severity": "info"
  }
}
```

## フィールド説明
- `lastUpdatedAt`: バッチが最後に正常にstatusを更新した時刻
- `coverageTo`: **どの日付まで**異常検知・実績ベースの出力物が生成されたか
- `availability`: ダッシュボード全体の状態
- `missingDays`, `failedDays`: 欠損・失敗日リスト（表示用）
- `latest`: 直近処理された実績サマリー（前日）
- `yesterday`: 常に `today − 1` の日付文字列（ISO形式）。`coverageTo` と異なりCSV処理状況に関わらず暦上の昨日を指す。ダッシュボードの「昨日」タブの基準日として使用
- `today`, `tomorrow`: 今日・明日の予測サマリー

---

# 2) alerts/YYYY-MM-DD.json

## 目的
**昨日（前日）**の異常検知結果を「イベント」単位で提供。

## パス例
- `web/public/alerts/2025-12-01.json`

## スキーマ
```json
{
  "date": "2025-12-01",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "summary": {
    "critical": 1,
    "warning": 2,
    "info": 0
  },

  "events": [
    {
      "id": "2025-12-01T18:00:00+09:00_spike",
      "type": "spike",
      "severity": "critical",
      "startAt": "2025-12-01T18:00:00+09:00",
      "endAt": "2025-12-01T19:00:00+09:00",
      "metric": "actual_mw",
      "actualMw": 61500.0,
      "expectedMw": 58000.0,
      "interval": {
        "p95Lower": 56000.0,
        "p95Upper": 60000.0,
        "p99Lower": 55000.0,
        "p99Upper": 61000.0
      },
      "reason": "Actual exceeded p99 upper bound by 0.8%",
      "tags": ["interval", "peak"]
    },
    {
      "id": "2025-12-01T09:00:00+09:00_drift",
      "type": "drift",
      "severity": "warning",
      "startAt": "2025-12-01T09:00:00+09:00",
      "endAt": "2025-12-01T12:00:00+09:00",
      "metric": "residual_mw",
      "residualAvgMw": 1200.0,
      "method": "ewma",
      "thresholdMw": 1000.0,
      "reason": "EWMA residual above threshold for 3 hours",
      "tags": ["residual"]
    },
    {
      "id": "2025-12-01T17:00:00+09:00_reserve_risk",
      "type": "reserve_risk",
      "severity": "warning",
      "startAt": "2025-12-01T17:00:00+09:00",
      "endAt": "2025-12-01T19:00:00+09:00",
      "metric": "usage_pct",
      "usagePct": 95.4,
      "thresholdPct": 92.0,
      "supplyMw": 61000.0,
      "reason": "Usage rate exceeded threshold",
      "tags": ["kpi"]
    }
  ]
}
```

## フィールド説明
- `events[].type`: `"spike" | "drop" | "drift" | "reserve_risk" | "quality"`
- `events[].interval`: spike/dropで予測区間がある場合のみ含む

### 欠損・失敗例
```json
{
  "date": "2025-12-02",
  "timezone": "Asia/Tokyo",
  "availability": "missing",
  "summary": { "critical": 0, "warning": 0, "info": 0 },
  "events": [],
  "message": "No source data. Ingestion was skipped or data was not available."
}
```

---

# 3) forecast/YYYY-MM-DD.json

## 目的
**特定日の時間別需要予測（今日・明日）**を提供。

## パス例
- `web/public/forecast/2025-12-02.json`

## スキーマ
```json
{
  "date": "2025-12-02",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "model": {
    "name": "baseline_dow_hour_mean",
    "version": "mvp-1",
    "nWeeks": 12
  },

  "peak": {
    "forecastMw": 57500.0,
    "at": "2025-12-02T18:00:00+09:00"
  },

  "series": [
    {
      "ts": "2025-12-02T00:00:00+09:00",
      "forecastMw": 42000.0,
      "p95LowerMw": 40000.0,
      "p95UpperMw": 44000.0,
      "p99LowerMw": 39000.0,
      "p99UpperMw": 45000.0
    }
  ]
}
```

## フィールド説明
- `model.name`: `baseline_dow_hour_mean` — 直近N週の同曜日・同時刻平均
- `model.nWeeks`: 訓練に使用したローリングウィンドウの週数
- `series[]`: 24ポイントの予測値 + 区間（95/99%）
- データ不足時は `availability: "not_yet_available"`, `series: []` で生成

---

# 3.5) forecast_snapshots/YYYY-MM-DD/*.json

## 目的
運用分析のため、lead-time予測スナップショットを制限付きで保持します。Pages出力物と一緒に保存しますが、ダッシュボードUIからは直接リンクしません。

## パス例
- `web/public/forecast_snapshots/2025-12-02/index.json`
- `web/public/forecast_snapshots/2025-12-02/2025-12-01T21-20-00-09-00.json`

## スナップショットスキーマ
```json
{
  "schemaVersion": "1.0.0",
  "timezone": "Asia/Tokyo",
  "targetDate": "2025-12-02",
  "generatedAt": "2025-12-01T21:20:00+09:00",
  "runType": "intraday",
  "preserveObservedForecastHours": true,
  "model": {
    "name": "lgbm_quantile_q50_intraday_residual",
    "version": "mvp-1",
    "nWeeks": 12
  },
  "peak": {
    "forecastMw": 57500.0,
    "at": "2025-12-02T18:00:00+09:00"
  },
  "observationSummary": {
    "actualHoursAtGeneration": 12,
    "observedActualHoursAtGeneration": 12,
    "fallbackActualHoursAtGeneration": 0,
    "lastActualHour": 11,
    "lastObservedActualHour": 11,
    "lastFallbackActualHour": null
  },
  "forecastBuild": {
    "stageSummary": {
      "raw_lgbm": { "hours": 24, "peak": {} },
      "pre_calibration": { "hours": 24, "peak": {} }
    },
    "series": [
      {
        "hour": 9,
        "ts": "2025-12-02T09:00:00+09:00",
        "forecastMwByStage": {
          "raw_lgbm": 31000.0,
          "analog_adjusted": 30950.0,
          "post_holiday_guarded": 30950.0,
          "midday_guarded": 30950.0,
          "pre_calibration": 30950.0
        }
      }
    ]
  },
  "series": []
}
```

`forecastBuild` は運用分析用の任意フィールドです。公開UIには直接表示しませんが、lead-timeスナップショットで raw LightGBM、analog補正、guard、intraday補正直前の値を比較できます。

## 保持方針
- `config.yaml` の `forecast_snapshots.retention_days` と `forecast_snapshots.max_per_day` が制御します。
- 現在の既定値は、直近21個のtarget date、target dateごと最大16件です。

---

# 3.6) reports/internal/operational-calibration/YYYY-MM-DD.json

## 目的
運用補正レイヤーが予測線をどのように動かしたかを追跡する内部分析用JSONです。ダッシュボードUIからは直接リンクしません。

## 主要フィールド
- `source_confidence`: 当日の実測/代替値/欠損状態の要約
- `applied_regime_reason`: 適用された補正理由の一覧
- `applied_day_bias`: 日単位scale補正の平均値
- `forecast_build.stageSummary`: raw modelからpre-calibrationまでの段階別要約
- `correction`: residual補正メタデータ。日付境界carry-over、日単位bias、`businessTypeTransitionPriorApplied`、`businessTypeTransitionPriorBiasMw`、`businessTypeTransitionApplied`、`businessTypeTransitionBiasMw` などの営業/非営業遷移補正フラグに加え、`positiveResidualMitigationApplied`、`positiveResidualMitigationMaxMw`、`negResidualRecoveryDampingApplied`、`negResidualRecoveryDampingFactor` などのhandoff緩和と回復ダンピングフィールドを含む場合があります
- `hourlyDiagnostics[]`: 時間別actual、TEPCO、stage別forecast、pre/post calibration forecast、calibration delta、residual

---

# 4) actual/YYYY-MM-DD.json

## 目的
**特定日の時間別実績値**を提供。当日データはイントラデイワークフローがリアルタイム更新。

## パス例
- `web/public/actual/2025-12-01.json`

## スキーマ
```json
{
  "date": "2025-12-01",
  "timezone": "Asia/Tokyo",
  "availability": "ok",

  "series": [
    {
      "ts": "2025-12-01T00:00:00+09:00",
      "actualMw": 42000.0,
      "actualSource": "observed",
      "tepcoForecastMw": 41500.0,
      "usagePct": 68.5,
      "supplyMw": 61000.0
    }
  ]
}
```

## フィールド説明
- `actualMw`: 実績電力需要 (MW)。未確定時間は `null`
- `actualSource`: `actualMw`の出所。`observed`は実測値、`tepco_forecast_fallback`は23:40 JST更新で23時の実績が未確定の場合にTEPCO予測値で補完した値。この補完値は運用予測の入力には使用し、検証指標と異常検知の実績判定からは除外
- `tepcoForecastMw`: TEPCO公式予測値（CSV収録値）
- `usagePct`: 使用率 (%)
- `supplyMw`: 供給力 (MW)

---

# 5) metrics/*.json

## 目的
ダッシュボードの**検証タブ**でモデル性能を説明するための評価出力です。

## ファイル
- `metrics/forecast_accuracy.json`: 自社モデルとTEPCO予測の運用上の時間別誤差比較
- `metrics/model_backtest.json`: ベースラインに対するLightGBMのオフラインバックテスト

## 共通フィールド
- `schemaVersion`: metricsスキーマバージョン
- `timezone`: `Asia/Tokyo`
- `generatedAt`: 評価生成時刻

## forecast_accuracy 主要フィールド
- `modelScope.summaryModelFamily`: 全体サマリーに含めた直近の運用モデル系列
- `modelScope.excludedDates`: baselineなど別モデル系列のため全体サマリーから除外した日付
- `summary.modelMaeMw`, `summary.tepcoMaeMw`: 比較可能な直近時間のMAE
- `summary.modelWapePct`, `summary.tepcoWapePct`: 総実績需要に対する絶対誤差率
- `summary.modelRmseMw`, `summary.tepcoRmseMw`: 大きな誤差リスクを見るRMSE
- `summary.modelMaxErrorMw`, `summary.tepcoMaxErrorMw`: 比較期間内の単一時間最大誤差
- `summary.modelAdvantageHours`, `summary.tepcoAdvantageHours`: 絶対誤差基準の優位時間。下位互換のため `summary.modelWins`, `summary.tepcoWins` も維持
- `summary.modelAdvantageRate`: `modelAdvantageHours / summary.hours`
- `daily[]`: 日別MAE/WAPE/RMSEと優位時間。`includedInSummary: false` の日付は全体サマリーから除外
- `daily[].maeGapMw`: モデルMAEからTEPCO MAEを引いた値。正ならTEPCOが近く、負ならモデルが近い
- `daily[].wapeGapPct`: モデルWAPEからTEPCO WAPEを引いた値
- `daily[].verdict`: `model_better`, `tepco_better`, `close`, `mixed`, `insufficient` のいずれかの運用判断
- `hourly[]`: 時間帯別MAE/WAPE/RMSEと優位時間

## model_backtest 主要フィールド
- `methodology`: バックテスト方式と分割基準日
- `trainPeriod`, `testPeriod`: 学習/テスト期間
- `baseline`, `lightgbm`: RMSE, MAE, MAPE, sample count
- `improvementPct`: ベースラインに対するLightGBM改善率

---

# ダッシュボード実装のヒント（フロント）
- 欠損は `null` で処理してラインが途切れるように（連続線禁止）
- `availability !== "ok"` の場合はタブ上部にバッジ・メッセージを表示
- `status.json` の `lastUpdatedAt` は常に表示（信頼性）

---

# スキーマ変更ポリシー
- **ファイルパス・スキーマは固定**
- 変更はconfig（学習期間、baselineウィンドウ、閾値）のみで対応
- `model.nWeeks` が変わっても `series/alerts` の構造は同一
