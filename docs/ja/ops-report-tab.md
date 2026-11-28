# 運用レポートタブ

2026-11-26（JST）を対象日とする新規生成分から、短い運用要約、開いて確認する詳細根拠、必要な日だけの研究ワークシートを表示します。誤差は予測−実績です。公開予測と後の再計算を一つの発行の連続した補正段階とは扱いません。

日付別JSONには従来のフィールドも残ります。互換性のある `operationsBrief` があれば新しい画面だけを、なければ従来の画面だけを表示します。一覧や本文はタブ表示・選択時にキャッシュを再検証し、常時ポーリングは行いません。必須内容はPythonで生成します。利用が許可され根拠がある場合のみ、GPT-6 Luna（none / 4000）による根拠選択1回を各言語で共有します。応答がなくても必須内容は表示します。

GPT-6 Lunaが確認箇所を選んでもv8本文の作成者はPython。新規記録の `generator.provider=python` は本文を指し、`generator.advisory` と `operationsBrief.advisoryStatus` が選択・不採用・未呼出し・失敗を区別する。過去のv8では失敗と根拠不明を区別できない場合がある。通常の決定論的本文はAI障害時の代替ではない。実績の確定状況は作成時に記録し、24行そろっていることから推測しない。日別MAEは事後比較で、同一発行・同一リードの比較ではない。H1は開始前の発行を証明でき、同一確定実績と当時のChampionがそろった対象のみ別集計し、標本がなければ点数を表示しない。

## 日報からモデル検証へ

冒頭で最大需要実績、ChampionとTEPCOの平均絶対誤差（MW）、Championのずれが最大だった時刻と方向を確認できます。需要曲線とゼロを基準にした誤差の棒グラフは、選択した日報に保存済みの時刻別データだけを使用します。時刻を選ぶと根拠の表の該当行を確認できます。欠測はゼロとして描かず、一日分がそろわなければ日別の優劣を示しません。最終公表値の事後比較であり、発表時刻や予測リードをそろえた比較ではありません。再計算値、予測区間、対象開始前に発行したH1の成績は別々に扱います。

モデルID、採用された指摘と根拠へのリンクが記録上で一致するときだけ、**GPT-6 Luna** の分析支援を表示します。呼び出しの有無は作成情報で確認できます。モデルが選ぶのは注目箇所であり、原因の特定や数値の作成、学習用の正解付けではありません。

実績・予測・発行履歴・補正スナップショットは[読み取り専用のReview Bundle](review-bundle-cli.md)や[予測モデルの比較研究](learned-intraday-challenger.md)でも使用します。11月26日の16～18時に繰り返した過小予測を調べる場合は、まずdataリビジョン、実績の締切、日報が記録した出典を固定します。その日を含むバンドルで既存CLIの `hour-review @query --scope primary --date 2026-11-26 --hours 16,17,18 --expand-provenance` を実行します。対象開始前の同じリードで平常日・逆方向の事例と比較し、元予測・補正前・補正後は同じ実行内でのみ対照します。当初の発行記録や当時の入力がなければ、後日の再計算で埋めず、原因は未確認とします。日報の正規化JSONの指紋とバンドルのファイルバイトのSHAは別物です。日報を開いても再現検証は実行されず、保存範囲も変わりません。

## 過去のレポートの読み方

以下は保存された従来の解説形式についての説明です。

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

### 運用メモと技術詳細

通常の運用メモは表示を維持し、補正シグナルカタログは初期状態で折り畳んだ`技術詳細・補正シグナル一覧`に表示します。キーボードで開閉でき、長い識別子はモバイルでも折り返します。既存の韓国語・英語・日本語カタログ表現を認識し、未知のメモは隠しません。元のJSONやAI生成内容は変更しません。

## 有効化とレポート単独復旧

レポートキーだけでは`run_batch.py`のAI呼び出しは有効になりません。Python ETLでは起動前に実行プロセスの環境変数へ有効化フラグを設定します。

```powershell
$env:TOKYO_GRID_EMS_OPENAI_API_KEY='YOUR_REPORT_KEY'
$env:OPENAI_DAILY_REPORT_AUTO_ENABLE='true'
python python/etl/run_batch.py --input data/raw --out web/public
```

Docker ETLではこの2つの変数と値をローカル`.env`に設定すると、Composeがコンテナへ渡します。`.env`や認証情報をコミットしないでください。プロジェクトのレポートキーは汎用の実行時変数`OPENAI_API_KEY`ではなく`TOKYO_GRID_EMS_OPENAI_API_KEY`です。

既存の日次根拠があれば、専用CLIでETLを再実行せずに最新の欠落/fallbackレポートを復旧できます。

```bash
python -m python.eval.ai_daily_report --public-dir web/public --languages ko,en,ja --use-openai --openai-max-calls 2
```

このコマンドはローカルのレポート・indexを作成しますが、公開はしません。明示的な上書き指定がなければ成功済みOpenAIレポートを保持し、最新のfallbackは呼び出し成功時に置き換えられます。ローカルホストの実行制御も前日実測が確定済みならこのレポート単独復旧経路を使います。上記コマンドはAPI費用が発生し得るため、ダッシュボードのプレビュー用ではありません。

## コスト制御

- 既定では最新の確定済み日付だけがOpenAI対象
- 生成実行の既定予算は論理呼び出し2回。英語マスター1回と韓国語/日本語ローカライズ1回で、両モデルとも`gpt-4o-mini`が既定
- 成功済みOpenAIレポートを保持し、欠落/最新fallbackレポートは復旧可能
- OpenAIの一時的なHTTP 500/502/503/504は既定で1回再試行する。最初の朝ETLで前日のレポートがfallbackのままなら、08:30/09:30のローカルスケジュールはhistorical ETL全体を再実行せず、レポートだけを再試行し、成功後にdata branchとPagesへ反映する
- 全時間帯の原始成果物ではなく圧縮fact packetと限定された主要区間の根拠を渡す
- fact packetには `controllerDiagnosis`, `stageAttribution`, `bandQuality`, `freezeImpact`, `coverageContext`, `rollingPatternContext` などの計算済みフィールドを含める
- fallback自然文、全hourly diagnostics、SHA fingerprint、file pathはプロンプトから除外

既定値:

```text
OPENAI_DAILY_REPORT_MAX_CALLS_PER_RUN=2
OPENAI_DAILY_REPORT_LATEST_ONLY=true
OPENAI_DAILY_REPORT_MODEL=gpt-4o-mini
OPENAI_DAILY_REPORT_LOCALIZATION_MODEL=gpt-4o-mini
OPENAI_DAILY_REPORT_HTTP_ATTEMPTS=2
OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90
OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180
```

論理予算とHTTP試行回数は異なります。`OPENAI_DAILY_REPORT_HTTP_ATTEMPTS=2`は論理呼び出し内で再試行可能なHTTP応答に対して1回の再試行を許可します。この通信試行は追加の論理予算を消費しないため、論理予算は実際のリクエスト回数や課金のハード上限ではありません。追加ローカライズ/検証再試行は論理枠を消費し、予算を3に設定するなど残り枠がある場合に限ります。予算の増加は既定動作ではなく運用者の明示的な選択です。

GitHub Actionsのrepository secret名は`OPENAI_API_KEY`のままでも構いませんが、workflow内ではプロジェクト専用の実行時変数`TOKYO_GRID_EMS_OPENAI_API_KEY`にマッピングします。モデル・予算・timeoutはworkflowのrepository variablesで渡せます。ETLの有効化フラグも`run_batch.py`プロセスに届く必要があり、キー注入だけではこの条件を代替できません。

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
