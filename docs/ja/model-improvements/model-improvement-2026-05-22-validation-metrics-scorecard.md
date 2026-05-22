# 検証指標スコアカード

Languages: [English](../../../en/model-improvements/model-improvement-2026-05-22-validation-metrics-scorecard.md) / [한국어](../../../ko/model-improvements/model-improvement-2026-05-22-validation-metrics-scorecard.md)

## 背景

従来の検証タブは `MAE` と時間別の勝敗数を中心に表示していました。初期ダッシュボードとしては有効でしたが、運用予測ではスポーツの勝敗のように「何時間勝ったか」だけでは判断できません。電力需要予測では、平均誤差、総需要に対する誤差率、大きな単発誤差リスク、時間別の優位区間を合わせて見る必要があります。

## 変更内容

- `MAE` はMW単位で直感的な代表指標として維持しました。
- 総実績需要に対する誤差率を見るため `WAPE` を追加しました。
- 大きな誤差リスクを見るため `RMSE` と最大誤差フィールドを追加しました。
- UI表現を勝敗ではなく、運用判断と優位時間に変更しました。
- 平均誤差と大きな誤差リスクが異なる方向を示す日は `mixed` と判定します。
- 下位互換のため既存の `modelWins`, `tepcoWins`, `modelWinRate` は維持しました。

## 運用上の解釈

ダッシュボードでは、時間別の優位時間を補助情報として扱います。より多くの時間で近かったとしても、1〜2時間の大きな誤差があれば運用上は危険になり得ます。その場合は `WAPE`、`RMSE`、`mixed` 判定でリスクを見える化します。

## 影響する出力

- `web/public/metrics/forecast_accuracy.json`
- `web/public/reports/daily/*.json`
- ダッシュボード検証タブ

## 検証

- `py -m pytest -q`
- `npm.cmd run build`
