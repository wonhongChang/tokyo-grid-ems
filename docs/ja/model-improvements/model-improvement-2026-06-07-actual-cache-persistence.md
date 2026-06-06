# 2026-06-07 actual JSON キャッシュ永続化

Languages: [English](../../en/model-improvements/model-improvement-2026-06-07-actual-cache-persistence.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-07-actual-cache-persistence.md)

---

## 問題

週末予測のレビューで、2つの問題を分けて確認しました。

2026-06-06土曜日の確定レポートでは、実際のshape問題がありました。モデルは朝のrampを高めに見積もった後、10:00-13:00を低く抑え、15:00付近では再び上振れしました。この点は、後処理制御とrawモデルshapeの両面で継続監視するケースです。

2026-06-07日曜日の予測には、別のデータ連続性問題も重なっていました。`actual/2026-06-06.json`には土曜日の実績値が入っていましたが、`.hourly_cache.parquet`では2026-06-06が気象予報用の仮想行として残り、`actual_mw`がすべて欠損していました。そのため、日曜日の推論で`lag_24h`が失われ、モデルが古いlag、直近の同一営業タイプ平均、暖かい気象シグナルに過度に依存する可能性がありました。

## 変更内容

2つの実行経路で、hourly cacheの保存タイミングをactual JSON注入後に移動しました。

- status/intraday refresh
- full ETL

既存パイプラインも、予測直前には直近のactual JSONをメモリ上へ注入していました。問題は、永続化されるキャッシュが注入前の状態で保存されていた点です。これにより、`.hourly_cache.parquet`にも予測実行で使用した観測値または一時fallback actualが残るようになります。

## 運用上の効果

TEPCO月次ZIPがまだ前日CSVを確定していない時間帯でも、システムは`actual/YYYY-MM-DD.json`をlag特徴量の連続性ブリッジとして使えます。次の日の`lag_24h`入力が、ダッシュボードに表示されるactual seriesと一致します。

これはTEPCO-aware calibration layerではありません。TEPCO予測値でモデルをチューニングしたり、TEPCO曲線を追従したりしません。夜遅い時間帯の実測が確定CSVに入るまで、欠損actualを一時的に埋める既存の運用fallbackルールだけを維持します。

## 診断根拠

今回の事象のシグネチャは次の通りです。

- `actual/2026-06-06.json`: 24件のactual値あり
- `.hourly_cache.parquet`: 2026-06-06行は存在するが、`actual_mw` countは0
- 2026-06-07推論: 全時間帯で`lag_24h`が利用不可

回帰テストでは、actual JSONを注入した後にhourly cacheを保存し、再ロードして、需要、TEPCO forecast reference、使用率、供給力、気象フィールドが保持されることを確認します。

## 検証

- `test_injected_actuals_can_be_persisted_to_hourly_cache`を追加しました。
- `_inject_today_actuals(...)`後にキャッシュを保存する実行順序へ修正しました。

