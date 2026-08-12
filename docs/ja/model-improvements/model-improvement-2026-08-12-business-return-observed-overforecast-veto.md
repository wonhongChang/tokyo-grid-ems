# 営業日復帰補正の実績過大予測 Veto

言語: [English](../../en/model-improvements/model-improvement-2026-08-12-business-return-observed-overforecast-veto.md) / [한국어](../../ko/model-improvements/model-improvement-2026-08-12-business-return-observed-overforecast-veto.md)

## 事象

2026-08-12 は山の日の次の最初の営業日であり、営業日復帰 anchor は lag-24 が休日パターンであることを正しく認識していました。しかし、当日実績は予測水準がすでに高いという反対の証拠を示していました。

- 07時の shortfall 補正前予測は 27,498.3 MW、実績は 25,380 MWで、2,118.3 MWの過大予測でした。
- それでも anchor-shortfall レイヤーは08時と09時にそれぞれ 1,000 MWを追加しました。
- その結果、post-holiday 段階の08時誤差は 3,899 MWとなり、その後確定した09時実績に対する段階誤差は 3,364.6 MWでした。

休日から営業日へ復帰するという事前情報と、当日実績の証拠が逆方向を示したケースです。朝のランプ実績がない段階では既存 prior は有効ですが、大きな過大予測が確認された後は追加リフトの根拠が弱くなります。

## 変更

推論専用コンテキストに `same_day_latest_actual_hour` とともに `same_day_latest_actual_mw` を追加しました。`business_return_anchor_shortfall` レイヤーはリフト適用前に `observed_overforecast_veto` を評価します。

次の条件をすべて満たす場合だけ veto が作動します。

- 既存の営業日復帰 shortfall 条件を先に満たす
- 最新実績の基準時刻が07時以降である
- 対象時刻が基準実績の1〜3時間先である
- 基準時刻の shortfall 補正前予測が実績を 1,200 MW以上上回る

作動時は、その対象時刻に対する営業日復帰の追加リフトだけを省略します。raw LightGBM 出力、類似日結果、予測バンド、全体 intraday 残差 cap は変更せず、TEPCO予測値も使用しません。

## 設定

```yaml
observed_overforecast_veto:
  enabled: true
  min_reference_hour: 7
  max_lead_hours: 3
  min_overforecast_mw: 1200
```

高い証拠閾値と短い lead 範囲によって介入を局所化しています。小さな誤差では既存の anchor-shortfall 補正を維持します。

## 運用 Replay

保持中の直近21日 forecast snapshot で新条件を満たし、実績も確定していた対象は1時間だけでした。追加リフトだけを除いた post-holiday 段階の反事実結果は次のとおりです。

| 日付 / 時刻 | 既存の段階誤差 | veto 反事実誤差 | 変化 |
|---|---:|---:|---:|
| 2026-08-12 08時 | 3,899 MW | 2,899 MW | -1,000 MW |

09時実績が 29,370 MWで確定した後、同じ段階反事実を適用すると09時誤差も 3,364.6 MWから 2,364.6 MWへ減少します。これは当日コントローラーの限定的な衝突を修正した結果であり、モデル全体の性能向上を証明するものではありません。保持期間内の他の遷移記録は veto 閾値を満たさなかったため過去の介入回帰はありませんでしたが、複数レジームの検証が完了したという意味でもありません。

## 検証と範囲

- feature builder と adjustment の集中テスト: `139 passed`
- リポジトリ全体テスト: `502 passed`
- 大きな過大予測ではリフトを取り消し、小さな誤差では既存補正を維持する両方の経路を検証しました。
- v11 Champion、学習フィーチャー集合、raw quantile モデル、バンド calibration、昼休み補正、公開予測 freeze 方針は変更していません。
