# 2026-07-18 平日Lag-24残差アンサンブル

言語: [English](../../en/model-improvements/model-improvement-2026-07-18-weekday-lag24-residual-ensemble.md) / [한국어](../../ko/model-improvements/model-improvement-2026-07-18-weekday-lag24-residual-ensemble.md)

## 問題

7月の運用予測はモデルとガードが複数回変更されているため、同一モデルの単純なバックテストとして集計できません。現行コードでraw LightGBM、決定的後処理、intraday補正、published forecast保存を分離して再生した結果、平日の反復誤差は特定時間のガード一つでは説明できませんでした。

絶対需要q50はlagとanchor水準への依存が強く、需要が前日や最近の同一営業日anchorを上回る日には十分に上昇せず、逆に涼しくなった日でもlag-24が高いと過大予測を維持しました。時間別delta特徴量、平日専用単一モデル、昼休みルールの強化は、最近区間と過去holdoutを同時に安定改善できませんでした。

## 変更

4つ目のLightGBM中央値モデルは次のtargetを学習します。

```text
target = actual_mw - lag_24h
```

営業日のみ中心予測を次のように合成します。

```text
q50_final = 0.5 * q50_absolute + 0.5 * (lag_24h + q50_residual)
```

非営業日は従来の絶対需要q50を維持します。q025/q975のhalf-widthは従来どおり補正して合成q50の周囲へ移すため、この変更自体はバンド幅を変更しません。

## 検証

2026-07-06から2026-07-17までの営業日10日を、現行コードと決定的後処理を含めてrolling replayしました。

| 指標 | 既存 | アンサンブル |
|---|---:|---:|
| 最終MAE | 718.3 MW | 660.9 MW |
| 00-05 MAE | 327.7 MW | 292.0 MW |
| 06-10 MAE | 824.3 MW | 754.1 MW |
| 11-13 MAE | 1,009.0 MW | 938.3 MW |
| 14-18 MAE | 1,046.3 MW | 952.1 MW |
| 19-23 MAE | 578.7 MW | 553.0 MW |

候補モデルは10日中8日を改善しました。悪化した2日の差は小さく、不安定性が大きかった日の改善幅はより大きい結果でした。

2026年1-5月のfrozen-origin holdoutでも、すべての月と時間帯が改善しました。

| 指標 | 既存 | アンサンブル |
|---|---:|---:|
| 全体MAE | 819.0 MW | 775.7 MW |
| Shape-delta MAE | 409.8 MW | 371.0 MW |
| 日次最大MAE | 2,442.4 MW | 2,086.1 MW |

この再生はtarget日の確定気象を使用しているため、ライブ気象予報誤差を含む運用性能の主張ではなく、モデル比較の上限評価です。

## 安全性

- TEPCO予測はモデル入力や補正targetに使用しません。
- 特定時間向けの補正ルールを追加していません。
- 特徴量集合と既存後処理順序は維持します。
- 週末と祝日の中心予測は変更しません。
- interval versionを更新し、古いpickleを配信前に再学習させます。
- `config.yaml`でアンサンブルの無効化やweight調整が可能です。

## 検証

- `pytest tests/test_lgbm_model.py -q`
- 全回帰テスト
- 現行後処理を含むversion-aware rolling replay
- 2026年1-5月frozen-origin holdout
