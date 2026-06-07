# 運用レポートタブ

運用レポートタブは、前日の電力需要予測結果を日次の運用レビューとして説明する画面です。検証タブがMAE/WAPE/RMSEなどの定量指標を中心に表示するのに対し、運用レポートタブは **なぜ誤差が発生したのか**、**どの補正レイヤーが関係した可能性があるのか**、**次に何を確認すべきか** を説明します。

---

## 目的

このタブは、予測結果を運用目線で振り返るためのものです。

- 前日のモデルとTEPCO予測の性能差を要約
- 大きく外れた時間帯とtime bandを表示
- lag、天気、営業日/非営業日遷移、intraday補正に関する原因仮説を提示
- 次に確認すべき特徴量・補正候補を自動適用ではなくレビュー候補として記録

運用レポートは予測モデルを直接変更しません。

---

## データ生成フロー

運用レポートはETL実行時に生成されます。

```text
TEPCO CSV / forecast JSON / actual JSON
  -> reports/daily/YYYY-MM-DD.json
  -> reports/internal/daily-diagnostics/YYYY-MM-DD.json
  -> reports/internal/operational-calibration/YYYY-MM-DD.json
  -> reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json
  -> Dashboard Ops Report tab
```

既定では、最新の確定済み日次レポート日付、通常は昨日だけがOpenAI生成の対象です。同じ日付/言語のレポートが既にある場合、ETLはそれを保持してAPIコストの重複を避けます。

Intraday/status-only実行は当日データと予測を更新しますが、運用レポート本文は書き換えません。

---

## 生成方式

| 方式 | 条件 | 説明 |
|------|------|------|
| deterministic fallback | OpenAIキーがない、またはOpenAIを使わない場合 | Pythonルールで指標と主要な外れを要約 |
| OpenAI解説 | `TOKYO_GRID_EMS_OPENAI_API_KEY`がある場合 | 圧縮されたfact packetをもとに自然言語の解説を生成 |

OpenAIを使う場合でも、性能指標、入力参照、データ品質、カバレッジ分離、stage attribution、controller diagnosis、band qualityはPythonコードが固定します。OpenAIは指標を再計算しません。

---

## 誤差方向のルール

レポート生成器は、OpenAIが本文を書く前にfact packetへ符号方向を明示します。

- `modelErrorMw = modelForecastMw - actualMw`
- `modelBiasMw = mean(modelForecastMw - actualMw)`
- 正の値は過大予測、つまり予測値が実績を上回る状態です。
- 負の値は過小予測、つまり予測値が実績を下回る状態です。

OpenAIがこの符号ルールと矛盾する原因仮説を返した場合、その仮説は破棄され、deterministic文言へfallbackします。

---

## 多言語処理

OpenAIレポートは2段階で処理します。

1. 英語マスター分析を生成
2. 英語マスターを韓国語/日本語へローカライズ

既定モデル:

```text
OPENAI_DAILY_REPORT_MODEL=gpt-4o-mini
OPENAI_DAILY_REPORT_LOCALIZATION_MODEL=gpt-4o-mini
```

翻訳が失敗またはtimeoutした場合、その言語パスは英語マスター本文を表示します。

```json
{
  "contentLanguage": "en",
  "generator": {
    "localizationStatus": "fallback_en",
    "localizationFallback": "en"
  }
}
```

UIはこの状態を検出し、英語原文表示のバッジを出します。

---

## UI構成

### ヘッダー

選択日、生成方式、severity、モデル判定を表示します。

- `provider: "fallback"`: システム自動診断
- `provider: "openai"`: AI運用解説
- `contentLanguage !== language`: 英語fallback本文を表示中

### 指標カード

モデルとTEPCOの主な性能指標を比較します。

- MAE
- WAPE
- RMSE
- 最大誤差
- TEPCOに対するモデル優位時間数

電力単位はUI localeに従います。日本語UIではTEPCOの慣例に合わせて `万kW` を使います。

### 運用診断

`diagnosticContext` があるレポートでは、運用診断の要約も表示します。

- 確定実績のカバレッジ
- 補正コントローラーの基準補正量
- 予測バンド品質
- 公開予測線のfreeze影響

この領域は、長い内部ログをそのまま主表示にするのではなく、運用者が予測曲線の見え方を素早く確認できるように圧縮したカードとして表示します。Stage attributionとfreezeの詳細値は折りたたみ可能な詳細領域に置きます。

### 原因仮説

`rootCauseHypotheses[]`をカードとして表示します。各仮説は以下を含みます。

- タイトルと説明
- メカニズム: 入力feature、補正レイヤー、serving policyが誤差を生む経路
- 次の確認: コード変更前に確認するreplay、診断フィールド、snapshot
- 関連時間帯
- 関連featureまたは補正レイヤー
- `evidenceStatus`
- counterEvidence

`evidenceStatus`は根拠の強さを示します。

| 値 | 意味 |
|----|------|
| `confirmed` | 入力JSONに直接的な補正フラグや制御値がある |
| `partial` | 指標/特徴量から強い状況証拠がある |
| `not_observed` | 中間履歴を確認できない |

`not_observed`はconfidenceを低くして、未確認の内容を断定しないようにします。

### 改善候補

`featureRecommendations[]`はモデルや補正のレビュー候補です。

```json
{
  "autoApply": false
}
```

レポートは改善案を提示できますが、自動適用はしません。

UIでは、各候補を実験チケットに近い形式で表示します。

- 実験候補
- 期待効果
- 注意点
- 検証方法

そのため、文面は本番設定をすぐ変更する指示ではなく、backtest/replay候補として表現します。

### 日付セレクター

タブは `reports/ai/daily/{locale}/index.json` を読み、日付一覧を表示します。

```text
2026-05-22
2026-05-23
2026-05-24
```

UIはフォルダ全体を走査せず、indexのみを読みます。既定のindex範囲は最近の日付なので、セレクターが無制限に伸びることはありません。

---

## コスト制御

- 既定では最新の確定済み日付だけがOpenAI対象
- ETL 1回あたりOpenAI呼び出しは最大2回。英語マスター1回と韓国語/日本語ローカライズ1回に制限する
- 既存レポートは保持して再生成しない
- OpenAIには全時間帯raw rowではなく圧縮fact packetだけを渡す
- fact packetには `controllerDiagnosis`, `stageAttribution`, `bandQuality`, `freezeImpact`, `coverageContext`, `rollingPatternContext` などの計算済みフィールドを含める
- fallback自然文、全hourly diagnostics、SHA fingerprint、file pathはプロンプトから除外

既定値:

```text
OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN=2
OPENAI_DAILY_REPORT_LATEST_ONLY=true
OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90
OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180
```

GitHub Actionsのrepository secret名は `OPENAI_API_KEY` のままでも構いませんが、workflow内ではプロジェクト専用の実行時変数 `TOKYO_GRID_EMS_OPENAI_API_KEY` にマッピングします。その他は必要に応じてrepository variablesで調整します。

---

## JSONパス

```text
web/public/reports/ai/daily/index.json
web/public/reports/ai/daily/ko/index.json
web/public/reports/ai/daily/en/index.json
web/public/reports/ai/daily/ja/index.json
web/public/reports/ai/daily/{locale}/YYYY-MM-DD.json
```

ルートの `reports/ai/daily/YYYY-MM-DD.json` は後方互換用の韓国語レポートです。
