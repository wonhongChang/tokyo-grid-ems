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

---

## アーキテクチャ

![Tokyo Grid EMS Architecture](docs/assets/tokyo-grid-ems-architecture.png)

- **ETL**: TEPCO月次ZIPを毎日ダウンロード → 確定済み履歴データをパース → JSON生成 → GitHub Pages へデプロイ
- **Intraday**: 2時間ごとに当日のTEPCO intraday CSVを取得・更新
- **検証**: モデルバックテストとTEPCO予測比較を `metrics/` JSONとして生成

---

## ダッシュボード画面構成

**ステータスバー（常時表示）**
- 最終更新時刻 / データ取得状況

**タブ 4種**

1. **昨日** — 前日の実績 + 異常イベント
   - Spike / Drop: 予測区間（95/99%）超過
   - Drift: 残差の継続的な偏り（EWMA）
   - Reserve Risk: 使用率・予備率の閾値超過

2. **今日** — 時間別予測 + 予測区間 + ピーク予測（時刻・値）

3. **明日** — 時間別予測 + 予測区間 + ピーク予測（時刻・値）

4. **検証** — 自社モデルとTEPCO予測の比較 + LightGBMバックテスト

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

# ダッシュボード ローカルプレビュー
cd web && npm install && npm run dev
```

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
| `metrics/forecast_accuracy.json` | TEPCO予測に対する運用精度 |
| `metrics/model_backtest.json` | ベースラインに対するLightGBMバックテスト |

> タイムスタンプはすべて `Asia/Tokyo (+09:00)` 基準のISO 8601形式で出力します。

---

## ドキュメント

- [学生向けプロジェクト概要](docs/ja/project-walkthrough.md)
- [LightGBMモデル設計](docs/ja/lgbm-design.md)
- [2026-05-13 日中高温ガード改善](docs/ja/model-improvements/model-improvement-2026-05-13-daytime-heat-guard.md)
- [2026-05-14 暖かい日中の過少予測補正](docs/ja/model-improvements/model-improvement-2026-05-14-warm-daytime-bias-guard.md)
- [2026-05-14 前週比気温変化特徴量](docs/ja/model-improvements/model-improvement-2026-05-14-lag-temperature-regime-features.md)
- [2026-05-15 前日比気象変化と体感温度特徴量](docs/ja/model-improvements/model-improvement-2026-05-15-24h-weather-apparent-features.md)
- [2026-05-16 営業タイプ遷移lag特徴量](docs/ja/model-improvements/model-improvement-2026-05-16-business-type-lag-features.md)
- [気温データ連携設計](docs/ja/weather-integration.md)
- [データ保持とアーカイブ戦略](docs/ja/data-retention-strategy.md)
- [モデル評価リポート](docs/ja/model-evaluation.md)
- [異常検知基準](docs/ja/anomaly-criteria.md)
- [JSONスキーマ契約](docs/ja/json_schema.md)

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
