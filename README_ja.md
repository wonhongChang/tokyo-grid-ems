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

> 前提：GitHub Pages上の静的JSONを配信する構成ですが、当日データはTEPCOのintraday CSVを2時間ごとに取得して補完します。
> そのため「昨日の確定済み異常検知レポート」＋「今日・明日の予測レポート」＋「当日の実績/TEPCO予測比較」を中心に構成しています。

---

## 技術スタック

| 役割 | 技術 |
|------|------|
| ETL / パース | Python (pandas) |
| 予測 / 異常検知 | Python (LightGBM + 統計fallback、rule-based anomaly detection) |
| ダッシュボード | React + Vite |
| 配布 | GitHub Pages (静的 JSON) |
| 自動更新 | GitHub Actions (毎日 + 2時間ごと) |
| 運用レポート | Pythonルールベースfallback + 任意のOpenAI解説/翻訳 |

---

## アーキテクチャ

![Tokyo Grid EMS Architecture](docs/assets/tokyo-grid-ems-architecture.png)

- **ETL**: TEPCO月次ZIPを毎日ダウンロード → 確定済み履歴データをパース → JSON生成 → GitHub Pages へデプロイ
- **Intraday**: 2時間ごとに当日のTEPCO intraday CSVを取得・更新
- **検証 / 運用レポート**: 前日運用レポート、TEPCO予測比較、LightGBMバックテスト、UIには表示しない内部診断JSON、任意のAI解説レポートを生成

---

## ダッシュボード画面構成

**ステータスバー（常時表示）**
- 最終更新時刻 / データ取得状況

**タブ 5種**

1. **昨日** — 前日の実績 + 異常イベント
   - Spike / Drop: 予測区間（95/99%）超過
   - Drift: 残差の継続的な偏り（EWMA）
   - Reserve Risk: 使用率・予備率の閾値超過

2. **今日** — 時間別予測 + 予測区間 + ピーク予測（時刻・値）

3. **明日** — 時間別予測 + 予測区間 + ピーク予測（時刻・値）

4. **検証** — 前日運用レポート + 自社モデルとTEPCO予測の比較 + LightGBMバックテスト

5. **運用レポート** — deterministic指標をもとに生成する日次運用解説
   - 前日指標、主要な外れ、データ品質、運用補正メタデータを使用
   - OpenAIキーがない場合はルールベースfallbackレポートを表示
   - `TOKYO_GRID_EMS_OPENAI_API_KEY`がある場合は英語マスター分析を作成し、韓国語/日本語にローカライズ

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
│   ├── forecast/               # 需要予測モデル
│   └── anomaly/                # 異常検知
├── web/                        # React/Vite ダッシュボード
├── docs/
│   ├── en/                     # 英語ドキュメント
│   ├── ko/                     # 韓国語ドキュメント
│   ├── ja/                     # 日本語ドキュメント
│   └── assets/                 # READMEとドキュメント用画像
└── data/
    └── raw/                    # 元CSVデータ（Actionsで自動ダウンロード、git除外）
        └── YYYY/
            └── YYYYMM_power_usage/
```

---

## クイックスタート

### ローカル実行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# TEPCOデータ取得
python python/etl/fetch_tepco.py

# ETL実行 → web/public/ 以下にJSON生成
python python/etl/run_batch.py --input data/raw --out web/public

# 任意: OpenAIベースの日次運用レポートを有効化
# Windows PowerShell:
# $env:TOKYO_GRID_EMS_OPENAI_API_KEY="..."
# $env:OPENAI_DAILY_REPORT_MODEL="gpt-4o-mini"
# $env:OPENAI_DAILY_REPORT_LOCALIZATION_MODEL="gpt-4o-mini"

# ダッシュボード ローカルプレビュー
cd web && npm install && npm run dev
```

### Docker ローカルETL

GitHub-hosted runner が TEPCO 月次ZIPを取得できない場合は、DockerでローカルETLを実行し、生成された静的JSONを自分のPCから `data` ブランチへ publish します。

```powershell
# 初回: イメージビルド + TEPCO ZIP取得 + ETL実行 + OpenAIレポート + dataブランチpublish + Deploy Only呼び出し
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Build -Publish

# 2回目以降: 既存イメージを再利用 + ETL実行 + dataブランチpublish + Deploy Only呼び出し
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish
```

Docker は Python ランタイム、TEPCO fetch、OpenAI レポート生成を担当します。publish と deploy-dispatch は既存の Git 認証情報を再利用できるようホスト側で実行します。

### GitHub Pages デプロイ

[DEPLOY_ja.md](DEPLOY_ja.md) を参照してください。

---

## 静的JSON出力物

ETLが `web/public/` 以下に生成するファイルです。

| ファイル | 内容 |
|------|------|
| `status.json` | 全体ステータス（最終更新・今日/明日の予測サマリー） |
| `alerts/YYYY-MM-DD.json` | 異常検知イベント一覧 |
| `forecast/YYYY-MM-DD.json` | 時間別予測値 + 予測区間（95/99%） |
| `actual/YYYY-MM-DD.json` | 時間別実績値（当日リアルタイム含む） |
| `forecast_snapshots/YYYY-MM-DD/*.json` | 運用分析用のlead-time予測スナップショット（UIからは直接リンクしない） |
| `metrics/forecast_accuracy.json` | TEPCO予測に対する運用精度 |
| `metrics/model_backtest.json` | ベースラインに対するLightGBMバックテスト |
| `reports/daily/*.json` | 検証タブに表示する前日運用サマリー |
| `reports/ai/daily/{ko,en,ja}/*.json` | 運用レポートタブの日次解説。OpenAI設定時はAI解説、未設定時はdeterministic fallbackを使用 |
| `reports/internal/daily-diagnostics/*.json` | 運用出力と一緒に保存する内部向けlag/気温/shape診断（UIからはリンクしない） |
| `reports/internal/operational-calibration/*.json` | 運用デバッグ用の source confidence と補正メタデータ |

> タイムスタンプはすべて `Asia/Tokyo (+09:00)` 基準のISO 8601形式で出力します。

### AI運用レポートの動作

- AIレポートはETL実行時のみ生成し、intraday/status-only実行では本文を書き換えません。
- 同じ日付/言語のレポートJSONが既にある場合、後続のETL再試行でも保持し、APIコストが繰り返し発生しないようにします。
- OpenAI呼び出しは既定で最大3回に制限します。1回目は低コストの英語マスター分析（`OPENAI_DAILY_REPORT_MODEL`, 既定値 `gpt-4o-mini`）、2回目は韓国語/日本語ローカライズ（`OPENAI_DAILY_REPORT_LOCALIZATION_MODEL`, 既定値 `gpt-4o-mini`）、3回目はローカライズ検証に失敗した場合に同じ低コストモデルで一度だけ再試行するためのものです。より強い分析モデルが必要な場合は `OPENAI_DAILY_REPORT_MODEL` を明示的に指定します。
- GitHub Actions向けtimeoutの既定値は `OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90`, `OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180` です。GitHub repository variablesを設定しなくてもPython側の既定値が使われます。
- 翻訳が失敗またはtimeoutした場合、その言語パスは英語マスター本文へfallbackし、`localizationStatus: "fallback_en"` を記録します。

---

## ドキュメント

- [学生向けプロジェクト概要](docs/ja/project-walkthrough.md)
- [LightGBMモデル設計](docs/ja/lgbm-design.md)
- [モデル運用仕様](docs/ja/model-operations-spec.md)
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

- [2026-07-18 平日lag-24残差アンサンブル](docs/ja/model-improvements/model-improvement-2026-07-18-weekday-lag24-residual-ensemble.md)
- [2026-07-18 下落shapeでの類似日上方補正cap](docs/ja/model-improvements/model-improvement-2026-07-18-declining-analog-uplift-cap.md)
- [2026-07-16 朝 ramp slope 過反応ガード](docs/ja/model-improvements/model-improvement-2026-07-16-morning-ramp-slope-overreaction.md)
- [2026-07-16 夕方 ramp drop cap の再調整](docs/ja/model-improvements/model-improvement-2026-07-16-evening-ramp-drop-cap-retuning.md)
- [2026-07-15 intraday anchor cap の精緻化](docs/ja/model-improvements/model-improvement-2026-07-15-intraday-anchor-cap-refinement.md)
- [2026-07-14 warm-day lag24 cap の気象許容幅補強](docs/ja/model-improvements/model-improvement-2026-07-14-warm-day-lag24-weather-allowance.md)

全体の時系列ログ: [docs/ja/model-improvements/README.md](docs/ja/model-improvements/README.md)

---

## ロードマップ

| フェーズ | 内容 | 状態 |
|---------|------|------|
| Phase 1–3 | ETL / 予測 / 異常検知 / ダッシュボード | ✅ 完了 |
| Phase 4 | GitHub Pages 自動デプロイ | ✅ 完了 |
| Phase 5-A | LightGBM 予測モデル | ✅ 運用反映 |
| Phase 5-B | 気温データ連携（Open-Meteo） | ✅ 運用反映 |
| Phase 6 | 検証タブ / バックテスト / TEPCO比較 | ✅ 完了 |

---

## 作者

- Chang Wonhong
- LinkedIn: https://www.linkedin.com/in/wonhong-chang-6660a0177/

---

## ライセンス

このプロジェクトは [MIT License](LICENSE) の下で公開されています。
