# 2026-05-20 相対気温と蓄積熱慣性の特徴量

> 固定温度による補正ルールではなく、相対的な気温変化と3日間の蓄積熱慣性をモデル入力として反映した改善メモ。

Languages: [English](../../en/model-improvements/model-improvement-2026-05-20-relative-morning-weather-features.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-20-relative-morning-weather-features.md)

---

## なぜ必要だったか

2026-05-20 の朝予測は、運用上はより高い需要が想定される気象条件だったにもかかわらず、前日実績にかなり近い線にとどまった。

モデルにはすでに CDD/HDD 系の気温特徴量があったが、朝の需要はまだ以下の特徴量に強く引っ張られていた。

- `recent_same_business_type_mean`
- `lag_24h`
- 同時刻の過去パターン

そのため、朝の気温条件が最近の基準から変わっていても、予測が前日同時刻需要を強く追いやすい問題が残っていた。

---

## 変更内容

気象特徴量を再確認し、CDD/HDD 形式の degree 特徴量は維持した。

- `cooling_degree = max(0, temp_c - cooling_base_temp_c)`
- `heating_degree = max(0, heating_base_temp_c - temp_c)`

これらは「何度以上なら補正する」という運用ルールではなく、快適温度帯から外れたときの非線形な需要反応を LightGBM に学習させるための設定可能な入力特徴量である。

暖房側の基準点は 10.0°C から 18.0°C に変更した。従来の 10°C は、東京の冬季暖房需要を捉えるには反応が遅すぎる基準だった。

平日朝のランプ時間帯、現在は 05:00-11:00 向けに LightGBM 特徴量を3つ追加した。

- `business_morning_x_temp_delta_24h`
- `business_morning_x_temp_anomaly_7d`
- `business_morning_x_temp_anomaly_doy`

これらは絶対温度ではなく、相対的な気温シグナルを使う。

- 前日同時刻より暖かいか/寒いか
- 直近7日平均より暖かいか/寒いか
- 同月・同時刻の過去基準より暖かいか/寒いか

したがって「N度以上なら補正する」という固定温度ルールは使わない。

また、3日間の蓄積熱慣性を見るために以下の特徴量を追加した。

- `temp_72h_mean`
- `cooling_degree_72h_mean`
- `heating_degree_72h_mean`

猛暑や寒波が続いたときに、建物や都市が熱を持つ効果をモデルが直接学習できるようにするためである。

---

## 期待される効果

平日朝の需要が `lag_24h` だけに寄りすぎず、直近の気温レジーム変化により反応できるようにする。

特に朝から相対的に気温が高い日に、05:00-11:00 の予測が前日需要に固定されすぎるケースを減らすことが狙いである。

72時間特徴量は、単一時刻の気温に過剰反応せず、持続的な暑さや寒さを反映する助けになる。

---

## メモ

- 既存の degree 系気温特徴量は設定可能なモデル入力として維持する。
- 湿度ベースの heat-index 特徴量は今回は追加しなかった。現在の運用で優先している気象庁公式予報フィードが時間別湿度を提供していないためである。`apparent_temp_c` はデータソースが提供する場合に使用し、ない場合は `temp_c` にフォールバックする。
- 運用 guard から optional absolute warm-day temperature floor を削除した。
- LightGBM interval version を更新し、次回 ETL/intraday 実行時に新しい特徴量セットで再学習されるようにした。
