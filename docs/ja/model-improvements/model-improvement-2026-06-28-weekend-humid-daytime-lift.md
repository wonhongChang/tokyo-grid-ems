# 2026-06-28 週末の湿度ベース日中リフト

言語: [English](../../en/model-improvements/model-improvement-2026-06-28-weekend-humid-daytime-lift.md) / [한국어](../../ko/model-improvements/model-improvement-2026-06-28-weekend-humid-daytime-lift.md)

## 背景

2026-06-27 土曜日の予測は全体として許容範囲でした。日次 MAE ではモデルが TEPCO を上回り、実績値もすべて p95 バンド内に収まりました。一方、2026-06-28 日曜日の予測では別の週末弱点が見えました。

- 早朝は当日実績が十分に入る前だったため低めに出ました。
- 朝のランプが回復した後も、12:00-15:00 JST の日中ラインが低く残りました。
- 湿度は高かったものの、`cooling_delta_24h` では強い暑さとして扱われず、既存の非営業日の日中リフトが発動しませんでした。

TEPCO 値は診断用の外部ベンチマークとしてのみ使います。モデル入力や補正ロジックには混ぜません。

## 変更内容

### 非営業日の日中リフトの residual 応答を分離

`intraday_correction.daytime_sustained_underforecast_lift` に、非営業日専用の residual 応答パラメータを追加しました。

- `non_business_residual_pressure_shrinkage`
- `non_business_residual_slack_mw`

営業日の制御は変えず、週末の日中だけ、実績 residual が連続して正の場合にやや直接的に反応できるようにしました。

### 週末対象時間と湿度条件の再調整

非営業日の target window を `[14, 15]` から `[12, 13, 14, 15]` に拡張しました。

湿度/不快指数の条件も、極端に蒸し暑い日だけでなく中程度に湿った日を拾えるように下げました。

- `non_business_min_discomfort_index`: `74.0 -> 70.0`
- `non_business_min_humidity_pct`: `90.0 -> 85.0`

ただし、当日実績 residual の根拠が必要なため、週末の日中予測を無条件に押し上げる構造ではありません。

## 検証

2026-06-28 日曜日のパターンを再現する回帰テストを追加しました。

- 非営業日
- 朝ランプ帯で連続する正の residual
- 不快指数 70 前後、湿度 85% 以上
- 強い正の `cooling_delta_24h` はない状況

期待動作は、12:00-14:00 JST の予測が residual-pressure 経路で保守的に引き上げられ、営業日の挙動は変わらないことです。

対象テスト:

```powershell
python -m pytest tests/test_intraday_correction.py -q
```

結果: `65 passed`.

## 運用メモ

このレイヤーは TEPCO 追従ではありません。当日実績で過少予測が繰り返し確認された場合に限り、週末の日中需要が低く残りすぎる問題を補正します。

次に見るべき点:

- 日曜日の日中 WAPE が改善するか
- 涼しい週末で過剰に持ち上げないか
- 06:00-07:00 JST には別の事前週末 ramp prior が必要か
- 週末の日中ランプ周辺の p95 バンドが過度に広すぎたり狭すぎたりしないか
