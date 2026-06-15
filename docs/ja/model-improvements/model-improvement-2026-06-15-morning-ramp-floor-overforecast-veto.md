# 2026-06-15 朝ramp floor過大予測veto

Languages: [English](../../en/model-improvements/model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md) / [Korean](../../ko/model-improvements/model-improvement-2026-06-15-morning-ramp-floor-overforecast-veto.md)

## 問題

2026-06-15の05:00-12:00配信チャートの朝の問題は、単一のrawモデル誤差ではありませんでした。

- 05:00は主に早い時点の入力と配信線freezeの問題でした。後から入力が更新された再計算線はかなり近くなりましたが、公開チャートの該当時間はすでに固定されていました。
- 08:00-10:00は前日よりかなり涼しい日にもかかわらず高めでした。特に09:32 JST実行では、`morning_observed_ramp_floor`が06:00-08:00の強い実績rampだけを見て10:00を約+1,150MW持ち上げました。
- この10:00 liftが後続の10時過大予測を作り、次のintraday実行で負のresidualが11:00へ伝播して11:00を低くしすぎました。

つまりfloor guardは実績rampの強さを見ていましたが、最新の観測バケットでモデルがすでに十分高く外れているかを確認していませんでした。

## 変更内容

`morning_observed_ramp_floor`に`max_latest_overforecast_mw`を追加しました。

- デフォルト: `500MW`。
- 最新観測時間がこの閾値以上に過大予測されている場合、floor guardは近未来rampを追加で持ち上げません。
- 最新観測バケットが高すぎない通常の強いrampケースでは、既存のlift動作を維持します。

これはrawモデルを新たに抑えるcapではなく、補助liftに対するvetoです。直近実績が「すでにモデルは高い」と示しているときに、追加の上方圧力を入れないための制御です。

## 期待効果

2026-06-15のパターンでは、次の効果を期待します。

- 08:00がすでに約1,000MW過大予測されている状態では、10:00に追加ramp-floor liftを入れません。
- その結果、次のintraday実行でliftされた10:00に起因する人工的な負のresidualが発生しにくくなります。
- 11:00がcontroller-induced downward swingに巻き込まれるリスクを下げます。

05:00のstale input/freeze問題と08:00のrawモデル高止まりは、別の課題として残ります。

## 検証

```text
tests/test_intraday_correction.py::test_intraday_correction_lifts_near_future_when_observed_morning_ramp_is_strong
tests/test_intraday_correction.py::test_intraday_correction_skips_morning_ramp_floor_when_latest_observed_bucket_is_already_high

Full suite: 396 passed
```
