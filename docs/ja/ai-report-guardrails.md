# AI運用レポートのガードレール

この文書は、TokyoGridEMSの日次AI運用レポートが、根拠のない説明を避けながら、運用者が信頼できる形で生成される仕組みを説明します。

レポート生成器は自由会話型のチャットボットではありません。Pythonが事実と指標を計算し、OpenAIが説明文を作成し、deterministic merge layerが最終JSONを検証してからダッシュボードに表示する運用レポートパイプラインです。

言語: [English](../en/ai-report-guardrails.md) · [한국어](../ko/ai-report-guardrails.md)

---

## ハードコーディングなのか

いいえ。現在の実装は、特定の日付、予測値、原因、改善結論を固定して埋め込む方式ではありません。

ただし deterministic guardrail は使っています。つまり、指標名、証拠品質、推奨対象、要約の整合性には固定ルールを置きます。実際の数値と判断は、daily report、diagnostics、calibration snapshot、actual、forecast、metrics JSONから計算されます。

整理すると次の通りです。

| 良くないハードコーディング | 現在の設計 |
|---|---|
| 「常にwarm-day biasが原因だと言う」 | 入力証拠がある場合だけ、そのfeature/guardを言及します。 |
| 「常に600MWのfreeze gapを入れる」 | serving lineとrecalculated lineのgapが実測されている場合だけfreezeを説明します。 |
| 「常に自モデルが良く見えるように書く」 | MAE/WAPE/RMSEの事実に基づいてTEPCO比の性能を要約します。 |
| 「OpenAIに指標判断を任せる」 | Pythonが指標を計算し、OpenAIは説明だけを担当します。 |

したがって、deterministicな部分は予測や診断を偽装するハードコーディングではなく、レポート出力契約に近いものです。

---

## パイプライン

```text
日次指標 / 診断 / 補正メタデータ
  -> compact FactPacket
  -> OpenAI English master analysis
  -> 韓国語/日本語ローカライズ
  -> deterministic merge and validation
  -> reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json
  -> 運用レポートタブ
```

OpenAIは自然言語の説明レイヤーを作ります。最終的な事実判断の所有者ではありません。

最終レポートはPythonの検証ステップを通過し、計算された根拠と矛盾する文言は修正または削除されます。

---

## 役割分担

| レイヤー | 役割 |
|---|---|
| Python fact builder | MAE、WAPE、RMSE、最大誤差、カバレッジ、time-band bias、freeze gap、calibration factsを計算します。 |
| OpenAI master analysis | fact packetを読み、運用者が理解しやすい説明を作成します。 |
| Localization step | English masterを韓国語/日本語へ変換し、数値と構造を維持します。 |
| Merge/guardrail layer | 根拠のない主張の除去、用語修正、推奨対象の検証、出力整合性の強制を行います。 |
| React UI | ブラウザからOpenAIを呼ばず、検証済みJSONだけを表示します。 |

---

## deterministicガードレール

| ガードレール | 目的 |
|---|---|
| 指標用語の修正 | このプロジェクトの公式な百分率誤差指標はWAPEであり、MAPEと誤記しないようにします。 |
| TEPCO用語の修正 | TEPCO値は外部forecast/referenceであり、このプロジェクトのモデルとして扱いません。 |
| 符号検証 | positive errorは過大予測、negative errorは過小予測です。矛盾する仮説は削除します。 |
| 証拠フィルタリング | 仮説にはmiss、diagnostics、calibration、freeze metadataのいずれかの具体的根拠が必要です。 |
| カバレッジ分離 | 確定actual coverageとintraday calibration snapshot coverageを混同しないようにします。 |
| freeze-gap検証 | serving-vs-recalculated gapが実際にある場合だけforecast freezeを言及します。 |
| 推奨対象whitelist | 改善候補は実在するfeatureまたは運用guardのみを対象にします。 |
| 推奨と仮説の接続 | 推奨項目は有効なroot-cause hypothesisと接続されている必要があります。 |
| `autoApply: false` | AI推奨は検討/バックテスト候補であり、自動適用対象ではありません。 |

---

## OpenAIが引き続き担当する部分

ガードレールがあっても、OpenAIの価値が消えるわけではありません。OpenAIは引き続き次を担当します。

- 指標やshape riskを読みやすい文章で説明する。
- 主要な誤差をlag、weather、calendar、calibrationの仮説に結び付ける。
- 韓国語/英語/日本語の運用サマリーを書く。
- 数値診断を実験チケット形式の改善候補に変換する。
- evidenceを`confirmed`、`partial`、`not_observed`として人間が理解しやすく表現する。

目的はレポートを機械的にすることではなく、OpenAIが根拠の範囲内でだけ説明するようにすることです。

---

## 品質基準

良い運用レポートは次を満たす必要があります。

- 日次性能の優劣判断がMAE/WAPEの事実と一致する。
- WAPEをMAPEと呼ばない。
- TEPCOを外部forecast/referenceとして表現する。
- 確定actual coverageとcalibration snapshot coverageを分けて説明する。
- 各root-cause hypothesisに具体的根拠がある。
- freeze policyの説明は実際のfreeze gapがある場合だけ出る。
- 改善候補は実在するfeatureまたはpost-processing layerを対象にする。
- 推奨は自動適用ではなくreview/backtest候補として残す。
- 韓国語/日本語レポートがEnglish masterの数値と論理を変えない。

---

## メンテナンスチェックリスト

モデルfeature、post-processing guard、report fieldを追加または改名する場合は、次を確認します。

1. AI report feature catalogに追加する。
2. OpenAIが別名で呼ぶ可能性がある場合はaliasを追加する。
3. 実際にチューニング対象になる場合だけrecommendation whitelistに追加する。
4. hypothesis filteringとrecommendation linkingのテストを更新する。
5. AI report単体テストを実行する。
6. 公開前に最新1日分のレポートをローカル生成して確認する。

推奨テスト:

```powershell
py -3 -m pytest tests\test_ai_daily_report.py -q
py -3 -m pytest -q
```

最新1日分のレポートsmoke test:

```powershell
$env:OPENAI_DAILY_REPORT_MODEL='gpt-4o-mini'
$env:OPENAI_DAILY_REPORT_LOCALIZATION_MODEL='gpt-4o-mini'
py -3 python\eval\ai_daily_report.py --public-dir web\public --out-dir tmp_ai_report_check --max-days 1 --languages ko,en,ja --use-openai --overwrite-existing --openai-max-calls 3
```

生成されたJSONとUIを確認し、`tmp_ai_report_check`を削除します。

---

## 運用上のトレードオフ

現在の設計は意図的に保守的です。そのため、完全に自由な文章より少し定型的に見えることがあります。一方で、根拠のない洗練された説明を公開してしまうリスクを下げます。

電力需要予測ダッシュボードでは、このトレードオフは妥当です。レポートは読みやすくあるべきですが、数値と主張は追跡可能でなければならないためです。
