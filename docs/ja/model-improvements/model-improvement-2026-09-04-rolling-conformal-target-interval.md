# 2026-09-04 Rolling Conformal Target予測区間

言語: [English](../../en/model-improvements/model-improvement-2026-09-04-rolling-conformal-target-interval.md) / [한국어](../../ko/model-improvements/model-improvement-2026-09-04-rolling-conformal-target-interval.md)

## 問題

従来のrolling conformalは予測区間の**最小幅を引き上げるfloor**に過ぎなかった。native quantileが過大でも縮小できず、v14-r2固定origin 12日ではP95 coverageが100%である一方、平均半幅は3,700.2MWに達し、大半の時間が3,750MW上限に張り付いた。時間帯ごとのリスクを区別できない状態だった。

## 変更

モデルartifact外に配信専用P95 target政策を追加した。

1. target日より前の確定データだけを使用する。
2. 最新28確定日のうち同じ営業レジームについて、時間帯別絶対誤差q95を計算する。
3. 最新10日の全レジーム時間帯別q95をdrift安全網として計算する。
4. 大きい方に1.05の安全係数を掛け、3,750MWで制限する。
5. 全時間帯のtargetが利用できる場合のみ、q50中心の対称P95幅に置き換える。
6. 履歴不足や不完全ファイルの場合は従来のfloor/native bandへfail closedする。

設定は`served_interval_calibration`に分離した。学習済みquantile estimator、LightGBM artifact fingerprint、q50モデル契約は変更しない。

## 検証

すべてtarget日を履歴から除外した因果的walk-forward再現である。

| 期間 | 従来P95 coverage | 新coverage | 従来平均半幅 | 新平均半幅 | 変化 |
|---|---:|---:|---:|---:|---:|
| v14-r2固定origin 12日 | 100.00% | 98.61% | 3,700.2MW | 2,455.5MW | 33.6%縮小 |
| 最新28日 | 97.92% | 97.17% | 3,200.0MW | 2,675.6MW | 16.4%縮小 |
| 最新84日 | 95.19% | 96.08% | 2,373.0MW | 2,139.6MW | 9.8%縮小 |
| 2026-05-20〜09-02の106日 | 94.73% | 96.78% | 2,168.6MW | 2,199.0MW | 1.4%拡大 |

84日では営業日95.83%、非営業日96.63%、時間帯別の最低値は深夜94.44%だった。従来coverage不足だった昼・夕方は広げ、過大だった深夜・夜間は縮小する。一律縮小ではなくP95の意味を回復することが目的である。

## 運用追跡

各forecast JSONの`intervalCalibration.servedTarget`に以下を記録する。

- 同一レジームと直近全レジームの履歴期間
- 時間帯別サンプル数とq95幅
- 安全係数と最終target幅
- target適用可否とfallback状態

## 制限

- P95は長期的な周辺coverage目標であり、すべての日が95%を満たす保証ではない。急激なレジーム転換日には日次coverageが低下し得る。
- P99は従来どおり最終P95半幅をもう一度拡張する。
- q50精度を改善する変更ではない。v15 q50候補は別レビューで昇格を却下した。
