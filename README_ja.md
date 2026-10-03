# Tokyo Grid EMS

TEPCOの公開電力データを活用した**電力需要予測 / 異常検知 / モニタリングダッシュボード**

> [English](README.md) · [한국어](README_ko.md)

- 公開ダッシュボード: [https://wonhongchang.github.io/tokyo-grid-ems/](https://wonhongchang.github.io/tokyo-grid-ems/)

---

## プロジェクト概要

東京電力パワーグリッド（TEPCO）が公開する時系列電力データをもとに、主要機能を提供する**自動更新型の静的EMS（エネルギー管理）プロトタイプ**です。

- 電力需要の**予測**（時間別、ピーク時刻・値を含む）
- 予測に対する**異常パターン検知**（急騰・急落、残差ドリフト、供給予備率リスク）
- GitHub Pagesで公開可能な**静的ダッシュボード**

> 確定履歴はローカルWindows/Docker ETLが更新します。GitHub Actionsは朝・補完実行を含む定期スケジュールで当日データを更新し、静的ダッシュボードをビルド・配信します。
> そのため「昨日の確定済み異常検知レポート」＋「今日・明日の予測レポート」＋「当日の実績/TEPCO予測比較」を中心に構成しています。

---

## 技術スタック

| 役割 | 技術 |
|------|------|
| ETL / パース | Python (pandas) |
| 予測 / 異常検知 | Python (LightGBM + 統計fallback、rule-based anomaly detection) |
| ダッシュボード | React + Vite |
| 配布 | GitHub Pages (静的 JSON) |
| 自動更新 | ローカルWindows/Docker ETL + GitHub Actionsによる定期intraday更新・配信 |
| 運用レポート | Pythonルールベースfallback + 任意のOpenAI解説/翻訳 |

---

## アーキテクチャ

![Tokyo Grid EMS Architecture](docs/assets/tokyo-grid-ems-architecture.png)

- **ETL**: ローカルWindowsの実行制御がDocker ETLを起動し、TEPCOの確定履歴・特徴量を更新して静的成果物をdataブランチへ公開します。
- **Intraday / 配信**: GitHub Actionsの定期実行が当日実測と補正予測を更新し、静的ビルドがJSONとReact/ViteダッシュボードをGitHub Pagesへ配信します。
- **レポート / 検証**: 日次指標と任意のAI解説が運用を支援します。Review Evidence Bundle、replay、隔離されたshadow評価はproduction servingと分離して証拠を分析します。

[アーキテクチャの説明と編集用ソース](docs/architecture/tokyo-grid-ems-architecture.md)

---

## ダッシュボード画面構成

ステータスバーは更新時刻とデータ取得状況を表示します。

| タブ | 内容 |
|---|---|
| 昨日 | 前日実測と急騰・急落、残差ドリフト、予備率リスクのイベント |
| 今日 | 時間別予測、予測区間、実測、ピーク予測 |
| 明日 | 翌日の時間別予測、予測区間、ピーク予測 |
| 検証 | 日次指標、モデル・TEPCO比較、LightGBMバックテスト |
| 運用レポート | 根拠に基づく日次解説。任意のOpenAI英語分析・韓日ローカライズ、またはルールベースfallback |

---

## TEPCOデータフォーマット

| 項目 | 内容 |
|------|------|
| 出典 | TEPCO公開 電力需給データ |
| エンコーディング | **cp932 (Shift-JIS)** |
| 単位 | **万kW (= 10 MW)** |
| フォーマット | 複数テーブルが空行で区切られた**マルチセクションCSV** |

---

## リポジトリ構造

```
.
├── python/
│   ├── tepc_parser.py          # TEPCOマルチセクションCSVパーサー
│   ├── etl/
│   │   ├── run_batch.py        # バッチ実行 (CSV → JSON生成)
│   │   ├── fetch_tepco.py      # TEPCO月次ZIP取得
│   │   ├── fetch_today.py      # 当日リアルタイムデータ取得
│   │   └── quality_gate.py     # 品質チェック
│   ├── forecast/              # 需要モデル、補正、予測区間
│   ├── anomaly/               # 異常検知
│   └── eval/                  # 指標、レポート、replay、Review Bundle、challengerツール
├── scripts/                   # ローカル実行制御、データ復元、公開
├── docker/                    # 分離されたshadowランタイムイメージ
├── docker-compose.yml         # ローカルETLと独立shadowサービス
├── web/                        # React/Vite ダッシュボード
├── docs/
│   ├── en/                     # 英語ドキュメント
│   ├── ko/                     # 韓国語ドキュメント
│   ├── ja/                     # 日本語ドキュメント
│   └── assets/                 # READMEとドキュメント用画像
└── data/
    └── raw/                    # 元CSVデータ（通常はローカル取得、git除外）
        └── YYYY/
            └── YYYYMM_power_usage/
```

---

## クイックスタート

### ダッシュボードのプレビュー

Git、Python 3、Node.jsをインストールし、repository rootから実行します。

```bash
python scripts/restore_public_from_data_branch.py
cd web
npm ci
npm run dev
```

復元コマンドは`web/public/`を公開済みの`origin/data`の内容で置き換えます。未公開のローカル成果物は先に保全してください。このプレビューはETLやOpenAI呼び出しを実行しません。

### 運用ETLの実行と公開

WindowsホストスクリプトにはDocker Desktop、`py` launcherのPython 3.14、Git認証とworkflow dispatch認証が必要です。Repository rootから実行します。

```powershell
# 初回手動実行: 確定履歴ETLが必要な場合はイメージをビルド
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Build -Publish -AllowOffSchedule

# 以降の手動実行
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish -AllowOffSchedule
```

ホストは公開済みデータ・モデル状態を復元し、前日実測が未確定ならDocker ETLを実行した後、成果物の検証・公開と配信/intraday dispatchを行います。前日実測が既に確定していれば履歴ETLを省略し、欠落/fallbackのAIレポートを別途復旧できます。`-AllowOffSchedule`は朝の予約時間外の手動実行を許可します。公開にはコンテナではなくホストのGit認証を使います。

Pythonだけでローカル成果物を再生成する場合は、`requirements.txt`をインストールし、`python python/etl/fetch_tepco.py`、`python python/etl/run_batch.py --input data/raw --out web/public`を順に実行します。モデル・状態の成果物を復元していない新環境では、配備済みChampionの再現は保証されません。

### GitHub Pages デプロイ

[DEPLOY_ja.md](DEPLOY_ja.md) を参照してください。

---

## 静的JSON出力物

`data`から復元する、または該当パイプライン/ツールが生成する`web/public/`の主要成果物です。

| ファイル | 内容 |
|------|------|
| `status.json` | 全体ステータス（最終更新・今日/明日の予測サマリー） |
| `alerts/YYYY-MM-DD.json` | 異常検知イベント一覧 |
| `forecast/YYYY-MM-DD.json` | 時間別予測値 + 予測区間（95/99%） |
| `actual/YYYY-MM-DD.json` | 時間別実績値（当日リアルタイム含む） |
| `metrics/forecast_accuracy.json` | TEPCO最新公開値による運用参考値。正式な同一vintage比較には使用しない |
| `metrics/forecast_vintage_accuracy.json` | 同一capture・lead-timeで揃えたモデル/TEPCO評価 |
| `reports/daily/*.json` | 検証タブに表示する前日運用サマリー |
| `reports/ai/daily/{ko,en,ja}/*.json` | 運用レポートタブの日次解説。OpenAI設定時はAI解説、未設定時はdeterministic fallbackを使用 |
| `forecast_snapshots/`, `reports/internal/` | レビュー用の予測vintage、補正段階、診断根拠。UIからは直接リンクしない |

バックテスト・replay・昇格の成果物は[モデル運用仕様](docs/ja/model-operations-spec.md)を参照してください。特に`model_contract_comparison.json`は明示的な昇格ツールが作成し、毎回のETLでは再生成しません。`internal`という名前はアクセス制御を意味せず、静的配信に含まれる場合があります。

> タイムスタンプはすべて `Asia/Tokyo (+09:00)` 基準のISO 8601形式で出力します。

### AI運用レポートの動作

- Intraday/status-only実行はAI解説を生成しません。通常は最新の確定済み日次レポートが対象で、成功済みのOpenAIレポートを保持し、欠落/fallbackレポートは別途復旧できます。
- 分析とローカライズはどちらも`gpt-4o-mini`が既定です。実行予算の既定は**論理呼び出し2回**であり、HTTP試行回数や費用のハード上限ではありません。通信再試行は別枠です。
- ETLで有効化する場合は、起動前に`TOKYO_GRID_EMS_OPENAI_API_KEY`と`OPENAI_DAILY_REPORT_AUTO_ENABLE=true`を設定します。専用レポートCLIでは代わりに`--use-openai`を指定します。`.env`やキーはコミットせず、プロジェクトのレポートに汎用の実行時変数`OPENAI_API_KEY`を使わないでください。
- 分析が利用できない場合はルールベースfallback、ローカライズ失敗時は`localizationStatus: "fallback_en"`で英語マスターを維持します。AI提案は予測へ自動適用されません。

有効化例、再試行予算、timeout、レポート単独復旧は[運用レポート設定とコスト制御](docs/ja/ops-report-tab.md)を参照してください。

---

## ドキュメント

- [初めて読む人のためのプロジェクトガイド](docs/ja/project-walkthrough.md)
- [LightGBMモデル設計](docs/ja/lgbm-design.md)
- [モデル運用仕様](docs/ja/model-operations-spec.md)
- [モデル昇格および性能低下Championポリシー](docs/ja/model-promotion-policy.md)
- [運用 Runbook](docs/ja/operations-runbook.md)
- [モデルレビュー記録](docs/ja/model-reviews/README.md)
- モデルレビュー用ツール: [根拠パッケージと読み取り専用 CLI](docs/ja/review-bundle-cli.md)、[検証概要](docs/ja/review-bundle-validation.md)
- 実験用 [学習型 intraday challenger と分離された shadow 評価](docs/ja/learned-intraday-challenger.md)
- 独立 [Docker multi-challenger shadow service](docs/ja/docker-intraday-shadow.md)
- [気温データ連携設計](docs/ja/weather-integration.md)
- [データ保持とアーカイブ戦略](docs/ja/data-retention-strategy.md)
- [モデル評価リポート](docs/ja/model-evaluation.md)
- [異常検知基準](docs/ja/anomaly-criteria.md)
- [運用レポートタブ](docs/ja/ops-report-tab.md)
- [AI運用レポートのガードレール](docs/ja/ai-report-guardrails.md)
- [JSONスキーマ契約](docs/ja/json_schema.md)

---

## モデル改善ログ

選定した最近の運用改善:

- [2026-09-21 実測の回復を考慮した週末夕方の残差減衰](docs/ja/model-improvements/model-improvement-2026-09-21-observed-evening-recovery.md)
- [2026-09-13 観測根拠による週末朝shape floor・AI根拠修正](docs/ja/model-improvements/model-improvement-2026-09-13-observed-weekend-shape-support.md)
- [2026-09-11 モデル点検・継続低下時の復元緩和・replay origin修正](docs/ja/model-improvements/model-improvement-2026-09-11-review-and-sustained-decline.md)

全体の時系列ログ: [docs/ja/model-improvements/README.md](docs/ja/model-improvements/README.md)

---

## ロードマップ

| フェーズ | 内容 | 状態 |
|---------|------|------|
| Phase 1–3 | ETL / 予測 / 異常検知 / ダッシュボード | ✅ 完了 |
| Phase 4 | GitHub Pages 自動デプロイ | ✅ 完了 |
| Phase 5-A | LightGBM 予測モデル | ✅ 運用反映 |
| Phase 5-B | JMA実測・予報 + Open-Meteo湿度・履歴補助 | ✅ 運用反映 |
| Phase 6 | 検証タブ / バックテスト / TEPCO比較 | ✅ 完了 |

---

## 作者

- Chang Wonhong
- LinkedIn: https://www.linkedin.com/in/wonhong-chang-6660a0177/

---

## ライセンス

このプロジェクトは [MIT License](LICENSE) の下で公開されています。
