# データ保持とアーカイブ戦略

> GitHub Pagesベースの公開ダッシュボードを維持しつつ、repositoryが無制限に肥大化しないようにするための運用方針です。

言語: [English](../en/data-retention-strategy.md) · [한국어](../ko/data-retention-strategy.md)

---

## 背景

TokyoGridEMSはGitHub Pagesで静的JSONファイルを公開します。GitHub ActionsがTEPCO/Open-Meteoデータを収集し、JSON/parquet/model成果物を作成し、GitHub Pagesがバックエンドなしでそれらを配信します。

この単純な構成は公開ポートフォリオとして扱いやすい一方、Gitは長期データベースではありません。すべての日次JSON、モデルpickle、cache snapshotを永久にコミットすると、cloneサイズやActions checkout時間が徐々に増えます。

## 運用原則

repositoryは恒久的なデータウェアハウスではなく、公開配信レイヤーとして使います。

- GitHub Pagesには最新のダッシュボード状態と制限された直近履歴を置きます。
- 過去の電力実績のsource of truthはTEPCO CSV/ZIPです。
- モデルforecast JSONは運用成果物であり検証資料でもありますが、無限に増える日次ファイル置き場にはしません。
- 長期公開履歴は、GitHub Pagesから静的にfetchできる月次archiveまたはmetricsファイルへ圧縮します。

## 推奨保持ポリシー

| データ種別 | 日次JSON保持期間 | 長期形式 | 備考 |
|---|---:|---|---|
| `status.json` | 現在のみ | なし | 最新ダッシュボード要約 |
| `actual/YYYY-MM-DD.json` | 直近180-365日 | 月次archive JSON | 過去実績はTEPCO CSV/ZIPから再構成可能 |
| `forecast/YYYY-MM-DD.json` | 直近180-365日 | 月次archiveまたは日次metrics | 過去予測は主に評価用途 |
| `alerts/YYYY-MM-DD.json` | 直近180-365日 | 月次archiveまたは要約metrics | UI応答性を維持 |
| `metrics/*.json` | 保持 | rolling/monthly metrics | 小さくポートフォリオ価値が高い |
| `.hourly_cache.parquet` | 現在snapshotのみ | 元データから再生成可能 | Actionsには便利だがGit history肥大化リスク |
| `.lgbm_model.pkl` | 現在モデルのみ | 再学習可能artifact | バイナリhistoryが早く大きくなる可能性 |

## 推奨公開ファイル構成

```text
web/public/
  status.json
  actual/YYYY-MM-DD.json
  forecast/YYYY-MM-DD.json
  alerts/YYYY-MM-DD.json

  archive/
    actual/2026-05.json
    forecast/2026-05.json
    alerts/2026-05.json

  metrics/
    forecast_accuracy.json
    model_backtest.json
    daily_mae.json
```

ダッシュボードは通常、直近の日次ファイルだけを読み込みます。将来UIで古いデータを見る必要が出た場合は、該当月のarchiveファイルだけを必要時にfetchします。

## まだ外部DBを使わない理由

S3、R2、Supabase、managed databaseなどの外部ストアを使えばrepository成長は抑えられます。ただし、CORS、公開権限、credential、コスト、追加の障害点が発生します。

このプロジェクトでは、次の折衷案がより適しています。

- GitHub Pagesを唯一の公開ホスティングレイヤーとして維持
- 古い公開データは静的な月次ファイルへ圧縮
- 初期画面の読み込みを軽く維持
- private API keyや別バックエンドを避ける

## Forecastデータの境界

過去のモデルforecast JSONは学習用actualとして使いません。学習とlag featureはTEPCO実績を基準に作成し、最新intradayでまだ実績が公開されていない時間帯に限ってTEPCO forecast fallbackを一時的に使用します。

この境界により、モデルが自分自身の予測値を将来の学習データとして再入力する循環を防ぎます。

## 今後の実装タスク

1. `config.yaml` に `retention_days` 設定を追加します。
2. ETLの最後に古い日次JSONを `archive/{actual,forecast,alerts}/YYYY-MM.json` へ圧縮するcleanupを追加します。
3. archive作成後、直近日次JSONだけを残します。
4. UIで過去月を探索する必要が出た場合、archive month indexファイルを追加します。
5. repositoryサイズが問題になった場合、`.hourly_cache.parquet` と `.lgbm_model.pkl` を再生成可能にする、または長期Git historyの外に分離する案を検討します。

