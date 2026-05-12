# GitHub Pages デプロイガイド

言語: [English](DEPLOY.md) · [한국어](DEPLOY_ko.md)

## 前提条件

- GitHubアカウント
- **Publicリポジトリ** (PrivateはGitHub Pro以上が必要)
- ローカルで全コードが正常動作することを確認済み

---

## Step 1: リポジトリ作成とコードのプッシュ

```bash
# GitHubで新しいリポジトリを作成後
git init
git remote add origin https://github.com/<USERNAME>/<REPO_NAME>.git
git add .
git commit -m "initial commit"
git push -u origin main
```

> `web/public/` 以下の生成データは `main` にコミットしません。
> ワークフローが `data` ブランチへ保存したうえでGitHub Pagesへデプロイします。

---

## Step 2: GitHub Pages の有効化

1. リポジトリ → **Settings** → **Pages**
2. **Source**: `GitHub Actions` を選択して保存

---

## Step 3: Actions 権限の確認

1. リポジトリ → **Settings** → **Actions** → **General**
2. **Workflow permissions**: `Read and write permissions` を選択
3. `Allow GitHub Actions to create and approve pull requests` にチェック

> ワークフローが生成JSON/cache出力を `data` ブランチにコミット・プッシュするため、書き込み権限が必要です。

---

## Step 4: 初回デプロイ（手動実行）

1. リポジトリ → **Actions** → **ETL + Deploy**
2. **Run workflow** → `main` ブランチ → **Run workflow**
3. 約2〜3分後に完了
4. Pages URLを確認: `https://<USERNAME>.github.io/<REPO_NAME>/`

---

## ワークフロー構成

| ワークフロー | 実行時刻 | 役割 |
|---|---|---|
| `ETL + Deploy` | 毎日 07:20, 08:20, 09:20 JST | TEPCO月次ZIPダウンロード → 確定済み履歴データ処理 → metrics → デプロイ。ZIP公開遅延を吸収するための複数回実行で、冪等に動作 |
| `Intraday Update` | 00:10 JST + 01:40〜23:40 JST 2時間ごと | 当日TEPCO intraday CSV更新 → 予測/status → デプロイ |

---

## 確認事項

```
Actionsタブ → ワークフロー実行 → 各Stepのログを確認
```

よくある問題:

| エラー | 原因 | 解決方法 |
|---|---|---|
| `Permission denied` on git push | Workflow permissions 未設定 | Step 3を再確認 |
| ビルド後404 | Pages Sourceが `Actions` になっていない | Step 2を再確認 |
| `ModuleNotFoundError` | requirements.txtにパッケージが不足 | ローカルで `pip install` 後にrequirements.txtを更新 |
| チャートデータなし | dataブランチがまだ作成・更新されていない | `ETL + Deploy` を実行し、当日データが必要なら `Intraday Update` も実行 |

---

## Vite BASE_URL

ワークフロー内で `VITE_BASE_PATH: /${{ github.event.repository.name }}/` として自動設定されます。
リポジトリ名を変更しても自動的に追従するため、個別の修正は不要です。
