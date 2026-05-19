# 2026-05-19 午後のthermal inertiaとshape guard

> 14:00-18:00の予測線が実績需要の流れより急に低下した問題への追加改善記録。

言語: [English](../../en/model-improvements/model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md) / [한국어](../../ko/model-improvements/model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md)

---

## 何が起きたか

2026-05-19のintraday refresh後、モデル予測線が午後に急低下した。

方向そのものが完全に不自然だったわけではない。TEPCOも午後から夕方にかけて需要低下を見込んでいた。問題はshapeだった。モデルは14:00-16:00付近で速く下がりすぎ、18:00 lead-timeでも低めに残った。

運用観点では危険な形である。暑い日の電力需要には熱慣性があり、気温がピーク後に下がり始めても、冷房需要がすぐ消えるとは限らない。

---

## 診断

既存モデルには、時間別気温、cooling degree、weather-delta特徴量があった。ただし、これらは主に現在時刻または同時刻の差分を表す。

モデルに直接伝わっていなかった情報は次の通り。

- 直近数時間も暑かったか
- 気温ピーク後も冷房需要が残る可能性があるか
- 予報気温が下がり始めても午後需要が高いまま維持される可能性があるか

intraday ramp guardは、直近未来1時間がハードな下限より下がることは防いだが、午後全体のshapeを滑らかにはできなかった。

---

## 変更内容

### 1. Thermal inertia特徴量

次のrolling weather-load特徴量を追加した。

- `cooling_degree_3h_mean`
- `cooling_degree_6h_mean`
- `heating_degree_3h_mean`
- `heating_degree_6h_mean`

これは夏専用ルールではなく、一般的な需要反応特徴量である。cooling inertiaは暑い日に、heating inertiaは寒い冬の朝/夕方に役立つ可能性がある。

LightGBM feature versionも更新し、次回ETL/intraday実行時にモデルが再学習されるようにした。

### 2. Intraday午後shape guard

`intraday_correction.shape_guard`を追加した。

既定動作は次の通り。

- 12:00以降の当日観測contextがある場合に有効
- target hour `15-19`を監視
- 1時間あたりの予測低下幅を `1000 MW` に制限

TEPCO予測に追従するためのルールではない。当日contextがある状態で、公開予測線が運用上説明しにくい崖のような形になることを防ぐ安全装置である。

---

## 期待効果

暑い平日午後に、モデルが高い日中需要から低い夕方需要へ一、二時間で過度に下げる傾向を抑える。

この変更は、毎日TEPCOに勝つことを保証するものではない。需要がまだ高いのに予測線だけが速く折れる特定の失敗パターンを減らすことが目的である。

---

## 安全メモ

- 新特徴量はcoolingとheatingの両方を含む。
- shape guardは狭い範囲で、当日観測値がある程度入った後だけ作動する。
- guardはdaily peak levelではなく、予測線shapeの極端な動きを制限する。
- 過去評価はpublished forecast snapshotとdaily reportを基準に継続確認する。

---

## テスト

次を検証した。

- training/inferenceでのthermal inertia特徴量生成
- inferenceが同日直近時間帯の気温を反映すること
- LightGBM feature-version再学習トリガー
- 午後予測線急落のshape guard
- 基準時刻前はshape guardが無効のままであること
