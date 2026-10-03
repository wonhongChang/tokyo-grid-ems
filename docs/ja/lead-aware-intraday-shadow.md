# Lead-Aware Intraday Shadow研究

[English](../en/lead-aware-intraday-shadow.md) | [한국어](../ko/lead-aware-intraday-shadow.md)

## 判断

2026年10月3日の追加研究は **PROMOTE L5 TO SHADOW**。本番昇格ではない。凍結L2は比較challengerとして保持する。Champion、公開予測、serving policy、ETL、scheduler、本番昇格基準は変更していない。Jev・モデルAPI呼び出しもない。

[元L1/L2/L3結果](learned-intraday-challenger.md)は不変。固定L2は全MAEを9.01%改善したがclosestは4.88%悪化、日別優位/劣位3/7、issue revisionも増加した。元入力・分割・モデル・replay・source-exact反例を保存した。

## 構造

| 候補 | 予測 | Leakage防止 |
|---|---|---|
| L2 reference | Post + 学習残差 | Outer foldごとに過去だけで再学習 |
| L4 | Post + `sqrt(1+lead/60)` × 正規化学習誤差 | 元46特徴 + 連続lead/context特徴10個 |
| L5 | Post + 学習weight × L2 correction | Gateには時系列OOF correctionのみ |

L4はlog/sqrt lead、観測量・経過時間、lead正規化残差/path相互作用を追加する。Targetは`(actual-post)/sqrt(1+lead/60)`。L5の学習labelは`clip((actual-post)/OOF_correction,0,1)`、correction=0ならweight=0。Gateは56個のissue-time特徴と予測correction/絶対値/正規化値の59入力。最終実測は推論に使わず、特定時刻/120分の手書き切替はない。

L2/L4は元LightGBM設定。L5 gateはsquared-error regression、100 trees、learning rate 0.035、6 leaves、min child 60、regularization 20。日/時刻capture数の逆数で重み付けする。Inner OOFは最初8日で学習後、3日ブロックを過去だけで予測。Random splitや結果後の調整はない。

## 固定評価

Freeze `2026-10-03T18:00:50.748933+09:00`、data revision `ea57d03155b4c5b3f86c97b1b8fb5cbcc3afd275`。Dataset SHA-256 `99aad1b55f6e5c1ada5f1aeae76faa906bde7ce85dff5e7a20231777f9409610`、事前登録SHA-256 `5ffbac417837274c441a3e265da2971e8b602e031c9018724410d12d462687d4`。

| Fold | 学習 | 評価 | Pair |
|---|---|---|---:|
| 1 | 8/28–9/10 | 9/11–17 | 760 |
| 2 | 8/28–9/17 | 9/18–24 | 1,357 |
| 3 | 8/28–9/24 | 9/25–10/1 | 1,588 |

全日付は閲覧済み。時系列retrospective研究であり **新しい独立確認ではない**。当時の確定label到着は未証明。10/2・3 provisionalおよび新live shadow結果は学習/選択に使わない。

Baselineはsame-run recorded post。Published、retrospective/latestとは異なる。Closestは日/時刻ごとの`(0,120]`最小positive lead一件で全near-lead issueとは別。過去champion artifact/policy identityと候補native intervalはunavailable。

事前固定の研究基準: 全MAE/WAPE >=3%改善、closest MAE悪化なし、全/closest RMSE増加 <=2%、closest日別優位 >=劣位、各fold closest MAE増加 <=10%。悪化量p95/maxとissue revision平均/p95は同一標本の再学習L2以下。Band/regime許容幅は最初のfold学習champion絶対誤差中央値×0.25。本番thresholdは変更しない。

## 同一標本結果

確定3,705 pair、closest417 target、21日。誤差はMW。

| モデル | 全MAE | RMSE | WAPE | Bias | Closest MAE | RMSE | WAPE | Bias |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Champion | 838.3 | 1,158.7 | 2.792% | +156.8 | 558.6 | 730.7 | 1.906% | +72.5 |
| 再学習L2 | 809.5 | 1,178.9 | 2.696% | -138.0 | 594.2 | 789.4 | 2.028% | -66.4 |
| L4 | 856.2 | 1,237.3 | 2.851% | -191.9 | 573.4 | 753.9 | 1.957% | -73.5 |
| L5 | 791.3 | 1,138.8 | 2.635% | -16.6 | 557.6 | 732.8 | 1.903% | -7.6 |

L5の全改善5.61%、closest改善0.18%は実質的優越性の証明ではない。日別優位/劣位12/9。Fold closest593.2/461.2/621.7、champion581.6/489.0/606.8で最終foldは2.46%悪化。L4は全/near・tail・revision基準に失敗。事後緩和はない。

最終foldの固定L2全/closest991.7/624.3に対しL5は996.3/621.7。学習cutoffは9/21と9/24で異なり、一様な優越性はない。

## Lead・安定性

固定L2の元holdoutを事前固定区間で集計した。

| Lead分 | Pair | Champion MAE | 固定L2 MAE |
|---|---:|---:|---:|
| (0,30] | 136 | 628.1 | 654.2 |
| (30,60] | 34 | 500.0 | 495.5 |
| (60,120] | 170 | 781.1 | 768.3 |
| (120,180] | 160 | 977.9 | 947.3 |
| (180,360] | 460 | 1,142.4 | 1,084.1 |
| >360 | 1,309 | 1,043.2 | 909.4 |

120分で明確に切り替わらず、30–60分は少標本。L5の区間平均weightは約0.52–0.55で主にcontext shrinkage。単調lead信頼度則とは呼ばない。

全悪化量p90/p95/maxは再学習L2 905.0/1,243.7/2,552.9からL5 546.2/754.8/1,952.9、closestは758.8/964.9/1,692.1から445.1/543.2/1,038.7へ低下。回帰ゼロではない。

同targetの隣接issue間隔 <=120分の2,838 pairでrevision平均/p95はchampion164.8/661.4、再学習L2 273.6/780.4、L5 209.3/670.0。L2より安定するがchampionより変動する。Same-run shapeとcross-issue revisionは別指標。

保持issueでL5最大追加誤差の反例は9/14 09時 +474.9、9/16 14時 +603.7、9/22 20時 +210.0、9/26 21時 +416.3など。Outer-test外の旧事例はhistorical contextで、独立テストではない。

## Worker・記録

継続収集は[分離Docker multi-challenger service](docker-intraday-shadow.md)を使う。下記terminal workerと1.1契約はhistorical/manualツールとして維持し、独立live inclusionは新serviceの別契約で管理する。

`feed.py`は`data/intraday_challenger/<workspace>`の専用bare Gitに`data`のみ取得する。Allowlistのsnapshot/actual/ETL-stateを読み、bytes/hash/revisionを保存する。`web/public`、production Git refs、ETL、モデルAPIを変更・実行しない。

Prediction `intraday-shadow/1.1.0`はissue/capture時刻、各lead、target、raw/pre/post、cutoff、source pointer/hash、identityを記録。開始済targetはretrospectiveで旧1.0も不変。遅延captureは定刻issueではないため`captureDelayMinutes`、`capture_lead_minutes`を確認する。

Evaluation `intraday-shadow-evaluation/1.1.0`は行ごとのactual state/hash、signed error、absolute-error deltaを含む。実測revisionは別のimmutable評価となり旧評価/予測を上書きしない。Identity、finalized/provisional、prospective/retrospectiveを分離。欠測はunavailable、forecast fallbackは実測ではない。Lead/time-band、日別優劣、tail、revisionを集計。Sample readinessはpromotion readinessではない。

```text
python -m python.eval.intraday_challenger lead-research --dataset <dataset.jsonl> --registration-file <preregistration.json> --registration-sha <sha256> --code-revision <revision> --output-root data/intraday_challenger/<new-research>
python -m python.eval.intraday_challenger.feed --remote https://github.com/wonhongChang/tokyo-grid-ems --model-root <frozen-model> --identity-sha <sha256> --output-root data/intraday_challenger/<identity-shadow> --start-date 2026-10-03 --interval-seconds 300
```

`--cycles 1`は有限確認。省略するとPython内で待機・継続する。ユーザーterminalを開いたまま実行しCtrl+Cで停止。Scheduler/service/自動起動登録はない。正確な過去再現にはGitに含めないlocal frozen dataset/manifestが必要。

## Identity・次の判断

L5は10/1まで確定5,235行で学習。Identity SHA-256 `e39715d5e956d6bb8f110df0b857f4af7baf94fa57fd3122fdce4f9e70a9a149`、combined fingerprint `614486238b55aaec6e705a686905b6264b9284c6ef38ed0cc75f2a4de6b393be`。Artifact/dataset/特徴/設定/OOF期間/実装hashを固定。元L2 model/feature source identityとloaderは不変。

研究段階でL2有限worker cycleとL5初回prospective captureを確認しsession background processは残さなかった。当時の遅延captureはcontextで確定独立evidenceではない。継続収集は別Docker serviceが担当する。このhistorical確認を現在のhealthと解釈せずstatusを照会する。

Identityごとに従来readiness維持: 確定14日、営業日 >=8、非営業日 >=4、確定prospective pair >=300、closest target >=150。実収集が充足した場合だけ10/18 ETL後に確認する。日数だけで承認しない。Native interval/champion identity/通常昇格手続きも必要。

追加14件と元・関連intraday/replay/batch **計258テストが通過**。Leakage/cutoff、identity/hash、immutable revision、path隔離、serialization/決定性、OOF/outer chronology、population一致、lead境界、unchanged-input workerを検証。Generated dataset/model/capture、usage、sessionメモはignored。
