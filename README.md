# Tokyo Grid EMS

TEPCOの公開電力データを活用した**電力需要予測 / 異常検知 / モニタリングダッシュボード**

> [한국어](README_ko.md) · [English](README_en.md)

---

## プロジェクト概要

東京電力パワーグリッド（TEPCO）が公開する時系列電力データをもとに、以下の3機能を提供する**バッチ処理指向のEMS（エネルギー管理）プロトタイプ**です。

- 電力需要の**予測**（時間別、ピーク時刻・値を含む）
- 予測に対する**異常パターン検知**（急騰・急落、残差ドリフト、供給予備率リスク）
- GitHub Pagesで公開可能な**静的ダッシュボード**

> 前提：「リアルタイム」ではなく、**前日までデータが更新される環境**を想定しています。
> そのため「昨日の異常検知レポート」＋「今日・明日の予測レポート」を中心に構成しています。

---

## 技術スタック

| 役割 | 技術 |
|------|------|
| ETL / パース | Python (pandas) |
| 予測 / 異常検知 | Python (統計ベースライン → LightGBM 予定) |
| ダッシュボード | React + Vite |
| 配布 | GitHub Pages (静的 JSON) |
| 自動更新 | GitHub Actions (毎日 + 2時間ごと) |

---

## アーキテクチャ

```
TEPCO CSV
    │
    ▼
Python ETL / Quality Gate
    │  パース → 品質チェック → 予測 → 異常検知
    ▼
Static JSON Artifacts
(web/public/status.json, alerts/, forecast/)
    │
    ▼
GitHub Pages Dashboard (React/Vite)
```

- **ETL**: TEPCO月次ZIPを毎日ダウンロード → パース → JSON生成 → GitHub Pages へデプロイ
- **Intraday**: 2時間ごとに当日のリアルタイムデータを取得・更新

---

## ダッシュボード画面構成

**ステータスバー（常時表示）**
- 最終更新時刻 / データ取得状況

**タブ 3種**

1. **昨日** — 前日の実績 + 異常イベント
   - Spike / Drop: 予測区間（95/99%）超過
   - Drift: 残差の継続的な偏り（EWMA）
   - Reserve Risk: 使用率・予備率の閾値超過

2. **今日** — 時間別予測 + 予測区間 + ピーク予測（時刻・値）

3. **明日** — 時間別予測 + 予測区間 + ピーク予測（時刻・値）

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
│   ├── lgbm-design.md          # LightGBM モデル設計
│   └── weather-integration.md  # 気温データ連携設計
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

[DEPLOY.md](DEPLOY.md) を参照してください。

---

## 静的JSON出力物

ETLが `web/public/` 以下に生成するファイルです。

| ファイル | 内容 |
|------|------|
| `status.json` | 全体ステータス（最終更新・今日/明日の予測サマリー） |
| `alerts/YYYY-MM-DD.json` | 異常検知イベント一覧 |
| `forecast/YYYY-MM-DD.json` | 時間別予測値 + 予測区間（95/99%） |
| `actual/YYYY-MM-DD.json` | 時間別実績値（当日リアルタイム含む） |

> タイムスタンプはすべて `Asia/Tokyo (+09:00)` 基準のISO 8601形式で出力します。

---

## ロードマップ

| フェーズ | 内容 | 状態 |
|---------|------|------|
| Phase 1–3 | ETL / 予測 / 異常検知 / ダッシュボード | ✅ 完了 |
| Phase 4 | GitHub Pages 自動デプロイ | ✅ 完了 |
| Phase 5-A | LightGBM 予測モデル（気温なし） | 設計済み |
| Phase 5-B | 気温データ連携（Open-Meteo） | 設計済み |

---

## 作者

- Chang Wonhong
- LinkedIn: https://www.linkedin.com/in/wonhong-chang-6660a0177/
