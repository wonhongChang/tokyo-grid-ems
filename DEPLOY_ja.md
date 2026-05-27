# GitHub Pages デプロイガイド

言語: [English](DEPLOY.md) / [한국어](DEPLOY_ko.md)

## 前提条件

- GitHub アカウント
- Public repository、または private Pages を利用できる GitHub プラン
- GitHub Pages Source を **GitHub Actions** に設定
- Actions workflow permissions を **Read and write permissions** に設定
- ローカル historical ETL 用の Docker Desktop

`web/public/` 以下の生成データは `main` にはコミットしません。生成データは `data` ブランチへ publish し、Pages デプロイ workflow がそのブランチを復元してから Vite アプリをビルドします。

## 運用構成

TEPCO 月次 ZIP の取得は GitHub-hosted runner から HTTP 403 になる可能性があるため、ローカル PC の Docker ETL で処理します。当日 intraday 更新は GitHub Actions のまま維持します。

```text
Windows タスク スケジューラ
  -> scripts/local_etl.ps1 -Publish
    -> origin/data を web/public に復元
    -> Docker ETL と OpenAI 日次レポート生成
    -> web/public を origin/data に push
    -> Deploy Only workflow を呼び出し
    -> Intraday Update workflow を呼び出し
```

## Workflows

| Workflow | Trigger | 役割 |
|---|---|---|
| `Manual ETL + Deploy` | 手動のみ | 緊急用 historical ETL。GitHub-hosted runner では TEPCO ZIP fetch がブロックされる可能性があるため schedule は無効化しています。 |
| `Intraday Update` | スケジュール + 手動 | 当日実績、予測、status の更新とデプロイ。ローカル ETL スクリプトが publish/deploy 後に呼び出し、朝のチャートを最新の当日 CSV 基準でもう一度更新します。 |
| `Deploy Only` | 手動 dispatch | ETL を実行せず `origin/data` を復元し、Vite アプリだけをビルド/デプロイ。ローカル ETL スクリプトが data publish 後に呼び出します。 |

## ローカル Docker ETL

初回実行:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish -Build
```

通常実行:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish
```

publish 前にローカルスクリプトが `web/public` を検証します。

- `status.json` が `availability: ok` であること。
- `coverageTo` が昨日以降であること。
- 昨日の `actual/YYYY-MM-DD.json` に 24 時間分の実績値があること。
- 今日と明日の forecast JSON に 24 時間分の予測行があること。

Docker fetch ステップは、TEPCO の遅延修正を吸収するため、直近 3 日分 JST の CSV を `data/raw` 上で上書きします。

推奨ローカルスケジュール、07:30 / 08:30 / 09:30 JST を登録:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_local_etl_task.ps1
```

スケジュール削除:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\unregister_local_etl_task.ps1
```

## モニタリング

- Windows タスク スケジューラ: `LastRunTime`, `LastTaskResult`, `NextRunTime`
- ローカルログ: `logs/local_etl/*.log`
- ローカル状態 JSON: `web/public/ops/local_etl_status.json`
- GitHub: `data` ブランチの最新コミットと `Deploy Only` workflow 結果
- Docker Desktop: ETL はバッチ処理なので、完了後に `Exited` になるのが正常

## トラブルシューティング

| 問題 | 原因 | 対応 |
|---|---|---|
| Actions で TEPCO 月次 ZIP が `403` | GitHub-hosted runner の IP が TEPCO 側でブロック | ローカル Docker ETL を実行: `scripts\local_etl.ps1 -Publish` |
| Deploy Only 呼び出し失敗 | ローカルで GitHub token が見つからない | `GH_TOKEN` または `GITHUB_TOKEN` を設定、GitHub CLI にログイン、または Actions で `Deploy Only` を手動実行 |
| ローカル ETL 後の Intraday 呼び出し失敗 | ローカル GitHub token がない、または GitHub Actions dispatch に失敗 | Actions で `Intraday Update` を手動実行し、`logs/local_etl/*.log` を確認 |
| OpenAI レポートが fallback | API キー不足、認証失敗、timeout | `.env` と `logs/local_etl/*.log` を確認して再実行 |
| チャートが古い | `data` ブランチは更新済みだが Pages が未デプロイ | `Deploy Only` を手動実行 |
| data push 権限エラー | ホスト側 Git 認証がない | Windows の GitHub 認証を再設定 |

## Vite Base Path

workflow は `VITE_BASE_PATH: /${{ github.event.repository.name }}/` を設定します。リポジトリ名を変更すると、base path もリポジトリ名に追従します。
