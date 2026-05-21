# 2026-05-21 公式JMA気温とハイブリッド湿度補完

> 公式JMAを気温の基準として維持しつつ、湿度欠損によって体感温度の信号が単なる気温に落ちる問題を防ぐ改善。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-21-official-jma-humidity-correction.md)

---

## 背景

最近の intraday 予測では、朝の需要を低く見るケースが続いた。公式JMAの予報は気温カーブを提供するが、現在利用している東京の time-series endpoint には時間別の予報湿度がない。

そのため将来行では次の状態になり得た。

- `temp_c` は公式JMA
- `apparent_temp_c` は `temp_c` と同じ
- `humidity_pct = NaN`
- `discomfort_index = NaN`

電力需要予測ではこの差が重要になる。同じ22度でも、湿度が高い朝は乾いた朝より冷房需要が早く立ち上がる可能性がある。湿度が欠けると、モデルはその違いを見られない。

---

## 変更内容

運用時の気象データ優先順位を次のように整理した。

1. **観測済みの時間**
   - 気温、湿度、不快指数、湿度を反映した体感温度は JMA AMeDAS 観測値を使う。

2. **将来の気温**
   - 公式JMA time-series 予報だけを使う。

3. **近い将来の湿度**
   - 公式JMAに湿度がないため、最新の AMeDAS 観測湿度を1-3時間だけ forward fill する。

4. **それ以降の将来湿度**
   - Open-Meteo JMA は湿度補完だけに使う。
   - 公式JMAの `temp_c` は上書きしない。
   - `apparent_temp_c` と `discomfort_index` は公式JMA気温と補完湿度から再計算する。

5. **最終 fallback**
   - すべてのライブ湿度ソースが失敗した場合のみ、月別の保守的な平均湿度を使う。

キャッシュには `weather_source` も保存する。予測が外れた時に、気象入力の経路を追跡できる。

- `AMEDAS_ACTUAL`
- `JMA_FORECAST+FORWARD_FILL`
- `JMA_FORECAST+OPEN_METEO_JMA`
- `JMA_FORECAST+SEASONAL_MEAN`

---

## 期待される効果

信頼している公式JMAの気温カーブを維持しながら、湿った日の体感温度入力を復元する。

特に、生の気温は普通に見えるが湿度が高く冷房需要が早く立ち上がる朝や夕方に効く。別プロバイダの気温予報が公式JMA気温を上書きするリスクも避けられる。

---

## 運用メモ

- Open-Meteo JMA は将来予測行の湿度補完だけに使う。
- 既存の過去キャッシュは `humidity_pct` だけが欠けている理由では強制 backfill しない。そうしないと ETL が数年分の archive を一度に再取得しようとする可能性がある。
- 既存の過去 `apparent_temp_c` はモデル学習に引き続き利用する。
- `weather_source` は追跡用メタデータであり、LightGBM の入力特徴量には追加していない。

---

## テスト

追加・更新したテストでは次を確認した。

- Open-Meteo JMA の湿度を使っても公式JMA気温は維持される。
- 近い将来では AMeDAS 湿度の forward fill が優先される。
- 季節平均湿度は最終 fallback としてのみ使われる。
- 過去キャッシュで湿度だけが欠けていても、大量の archive 再取得を起こさない。
- 全体回帰テスト: `306 passed`.
