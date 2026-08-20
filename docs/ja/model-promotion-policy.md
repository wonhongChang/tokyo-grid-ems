# モデル昇格および性能低下Championポリシー

言語: [English](../en/model-promotion-policy.md) / [한국어](../ko/model-promotion-policy.md)

状態: v14復旧候補を隔離stagingへ昇格済み。remote配備と72時間安定化監視はoperator公開後に開始

基準日: 2026-08-21 JST

## 目的

本ポリシーは健全なChampionを保護しつつ、既存モデルの性能が長期間低下した場合に、より良いChallengerが一つの絶対基準だけで無期限に拒否される問題を防ぐ。

現行実装はChallengerをseasonal baselineと固定の絶対上限で評価し、Championとは今日・明日のprediction driftだけを比較する。そのため、ChallengerがChampionより実質的に正確でも絶対上限またはdriftを超えると、弱いChampionが継続する可能性がある。

## バージョン原則

- モデルversionは再学習回数ではなく、feature、target、ensemble、inference contractが変わる場合に更新する。
- 同じcontractを新しいデータで再学習してもversionは維持する。
- v12はv13に継承された過去系譜として保存し、active candidate poolからは除外する。
- v13は、v14が劣化v11だけを上回ったのではないことを証明するための旧Challenger基準とする。
- v14はstagingで承認された次期Champion契約とする。同じcontractを新しいデータで再学習する場合はv14 buildであり、feature・target・ensemble・inference契約が変わる場合だけ次versionへ進める。

## 基本原則

1. 通常昇格の絶対品質基準を安易に緩和しない。
2. ChampionとChallengerは同一の学習cutoff、holdout、入力contractで直接比較する。
3. TEPCO予測は外部benchmarkと診断信号に限定し、学習・補正・昇格targetには使用しない。
4. 大きなprediction driftは直ちに性能低下を意味しない。自動昇格を止めてshadow検証を要求する信号として扱う。
5. 通常昇格と性能低下Championの復旧昇格を分離する。
6. 復旧昇格には再現可能なreplay、不変の正確なartifact、明示的operator承認、rollback保護が必要である。昇格前shadowを基本とし、下記の強化条件を満たす緊急復旧だけが必須の昇格後監視へ切り替えられる。

## 検証観点

| 観点 | 目的 | 入力条件 |
|---|---|---|
| Temporal model replay | 原型モデルの汎化性能比較 | 同一train cutoffと28/56/84日holdout |
| Frozen-origin replay | 配信時の気象・lag誤差を再現 | 予測時点のweather/lag snapshot |
| As-served replay | Championと後処理全体の運用状態 | 公開forecastと確定actual |
| Interval validation | q50変更後の不確実性確認 | 全体およびregime/time-band別p95 coverage |

最終観測気象のみを使うreplayはmodel mapping診断には有効だが、運用入力を完全には再現しないため単独の昇格根拠にしない。

## 通常昇格経路

原型temporal replayの安全上限と実運用品質の合格基準を分離する。既存値はfail-closed temporal安全上限としてのみ維持し、通常昇格にはより厳しいfrozen-originまたはshadow運用品質gateを追加する。

| Temporal replay安全基準 | 現在値 |
|---|---:|
| 全体MAE | 1,000MW以下 |
| 全体WAPE | 3.0%以下 |
| Shape delta MAE | 750MW以下 |
| 最大誤差 | 6,500MW以下 |
| segment MAE | 1,500MW以下 |
| segment Shape delta MAE | 1,100MW以下 |
| Seasonal baseline比MAE改善 | 20%以上 |

| 中間運用品質基準 | 提案値 |
|---|---:|
| Frozen-origin/shadow全体MAE | 750MW以下 |
| Frozen-origin/shadow全体WAPE | 2.2%以下 |
| 同期間TEPCO MAE比 | 2.0以下 |
| Shape delta MAE | 700MW以下 |
| 最大時間誤差 | 4,500MW以下 |

TEPCO基準の根拠は次の通りである。

| 期間 | TEPCO MAE | 自モデルas-served MAE |
|---|---:|---:|
| 直近28日 | 420.9MW | 949.8MW |
| 直近56日 | 363.8MW | 733.5MW |
| 直近84日 | 352.7MW | 656.7MW |
| 2026-08-01〜17 | 408.2MW | 1,031.1MW |

750MWは直近28日TEPCO MAEの約1.78倍で、56〜84日の自モデル正常範囲にも余裕を持たせる。この値はv11より良いモデルへ安全に置換するための中間SLOであり、TEPCO同等の認定基準ではない。

### TEPCO同等および優位基準

プロジェクトの最終目標はTEPCO同等以上であるため、別のbenchmark資格を使用する。

| 等級 | 基準 |
|---|---|
| Recovery Champion | 現Championより28日MAE/WAPEを8%以上改善し、すべての補助risk gateを通過 |
| Production Acceptable | 中間運用品質gate通過 |
| TEPCO Parity Qualified | 同一発行時点・同一lead timeで28日と84日のMAE ratioおよびWAPE ratioが1.10以下 |
| TEPCO Superior | MAE ratioが1.00未満で、paired日別誤差差分の95%信頼区間上限が0未満 |

`MAE ratio = model MAE / TEPCO MAE`と定義する。直近28日TEPCO MAE 420.9MWに対する10%非劣性marginは約463MWである。これは固定目標ではなく同期間TEPCO性能に応じて変動するbenchmarkである。

10% marginは初期運用許容値である。正式なparity認定の前に、過大・過小予測が予備力と運用費へ与える影響からmarginを換算し、評価前に固定する。妥当な費用根拠が得られない場合は、より厳しいratio 1.00を最終目標とする。

Parity判定では次をすべて要求する。

- TEPCOと自モデルforecastを同一発行時点・同一lead-time bucketで比較
- day-aheadとintradayを分離評価
- 全必須lead bucket・時間帯でpaired-hour coverage 80%以上を確保
- 時間相関を考慮し、日付単位block bootstrapでpaired absolute-error差分の95%信頼区間を計算
- MAE比率の95% bootstrap信頼区間上限を1.10以下とし、有利な点推定だけでは通過させない
- 営業日、非営業日、朝、昼、夕方前半、夜の全重要segmentをTEPCO MAEの1.25倍以内に維持
- RMSE比率は1.15以下、最大誤差比率は1.25以下とする。TEPCOの不変peak vintageが得られるまではpeak時刻誤差を診断指標としてのみ記録する
- 自モデルp95 bandはcoverageとpinball lossで別途検証

同一vintage captureは全ETL/Intraday実行でappend-only保存される。TEPCOは別個の不変`issuedAt`を提供しないため、プロジェクトの`capturedAt`を観測vintageとして使用する。同一実行で見た自モデルとTEPCO値のみを比較し、後のTEPCO修正値で過去captureを置換しない。28日と84日の全lead bucket coverageが揃うまで正式なparity判定は保留する。

### 1,000MW基準の解釈

`max_validation_mae_mw: 1000`は2026-07-26に最初の昇格保護workflowを導入した際に設定された。当時、直前28日の実配信MAEは560.0MW、利用可能なstage snapshotにおけるrawモデルMAEは910.8MWだった。そのため1,000MWは当時の分布に余裕を持たせた運用品質上限とは説明できるが、統計的信頼区間や長期季節分布から算出した不変基準ではない。

候補temporal replayのMAEと実際のas-served MAEは、気象入力と後処理条件が異なるため同一の数値として直接扱わない。例えば2026-08-10のas-served MAEは1,730.2MWだったが、この値だけで候補temporal gateを合否判定しない。これは現Championが通常の運用品質範囲を外れたhealth根拠として用いる。

すべての候補を通すために1,000MWを単純に引き上げない。この値はtemporal replayの安全上限および運用critical基準としてのみ使用し、750MWは中間昇格目標とする。最終成功基準は同一forecast vintageでTEPCOに対する非劣性または優位を証明することである。

次の相対比較を追加する。

- 同一train cutoffで再学習したChampion contractより全体MAEが最低5%良いこと。
- 重要segmentのMAEまたはshapeがChampionより5%超悪化する場合は自動昇格しない。
- 平均drift 900MW以下、時間最大drift 2,500MW以下なら、他のgate通過時に自動昇格できる。
- drift上限超過は`rejected`ではなく`shadow_required`とする。

## 性能低下Champion判定

次の整合性条件のいずれかを満たす場合、直ちに`champion_degraded_review_required`へ移行する。

- artifactの`trainingCutoff`がない、または検証できない。
- artifactのconfig fingerprintが現在のinference contractと不一致。
- artifact互換性またはsource commitの追跡が不完全。

次の性能条件のうち二つ以上が連続二回の週次評価で再現した場合、`champion_degraded`と判定する。

- 28日as-served MAEが900MWまたはWAPEが2.7%を超過。
- 直近14日MAEがそれ以前の28日基準より15%以上悪化。
- 朝、昼、夕方前半、非営業日のいずれかでMAEが1,500MWを超過。
- 同一temporal replayでChallengerがChampion contractより全体MAEを8%以上改善。
- モデル優位時間率が長期間35%未満。TEPCOはこの信号の診断benchmarkであり昇格targetではない。

性能低下判定は新モデルの自動昇格を意味しない。通常経路だけでは既存モデルを安全に置換できない運用状態を示す。

28日as-served MAEが1,000MWまたはWAPEが3.0%を超えた場合は、連続二回を待たず直ちにcritical degraded reviewを開始する。

## 復旧昇格経路

Championが`champion_degraded`の場合、Challengerは絶対上限を一部超えていても次の条件をすべて満たせば統制された復旧候補になれる。

- 同一temporal replayでChampion比の全体MAEとWAPEをそれぞれ最低8%改善。
- 最大誤差とshape delta MAEをChampion比で5%超悪化させない。
- 営業日、非営業日、朝、昼、夕方前半、夜のどの重要segmentでもMAEを5%超悪化させない。
- Championの既知の弱点を一つ以上10%以上改善。
- 補助56日・84日windowで全体MAEがChampionより悪化しない。
- frozen-origin replayのcoverageが完全で、同方向の改善を確認。
- 最低72 forecast-hourおよび2確定運用日のshadowで重大な退行がない。
- artifact保存・再読込、training cutoff、config fingerprint、rollback artifact検証を通過。

復旧昇格は自動実行しない。`recovery_candidate_ready`を記録し、明示的な運用レビュー後に`recovery_promoted`へ移行する。

基本実装はこの証拠を`metrics/model_shadow_evaluation.json`から読み取る。`artifactSha256`は保持shadow artifact、metadata、以前の昇格reportとすべて一致しなければならない。欠落・古い証拠、72時間未満、または確定2日未満では`shadow_required`で停止し、通常の承認環境変数だけでは迂回できない。承認時は新規再学習候補ではなく、検証済みの同一shadow artifactを昇格する。

### Operator承認による緊急復旧

旧Championを継続すること自体が、別途確認された整合性・性能リスクである場合にのみ緊急復旧を許可する。この経路は自動ではなく、`python/eval/promote_recovery_candidate.py`と明示的復旧承認を使う。

- 旧Championがすでにdegradedで、学習cutoff欠落やconfig fingerprint不一致などのartifact整合性欠陥を持つこと。
- 正確なv14 artifactが28日MAE/WAPEをv11比でそれぞれ8%以上改善し、文書化された弱点segmentを一つ以上10%以上改善すること。
- v13は未配備の参考候補であるため、28日・56日・84日のすべてでv13 MAE/WAPEを悪化させないこと。別途5%の追加改善は要求しない。
- 56日・84日補助windowでv11全体MAE/WAPEを悪化させないこと。
- artifact保存・再読込互換性と今日/翌日48時間の有限値smoke testを通過すること。
- 自動drift上限を超える場合は別途`--allow-large-drift`判断が必要で、数値と理由を昇格reportへ記録すること。
- atomic置換前に旧Champion artifactとmetadataをrollback pathへコピーすること。
- 昇格前shadowを省略する代わりに72時間の安定化監視を必須とし、最低48確定時間で明確な退行があればrollback reviewを開始すること。

この経路は欠陥Championが無期限に残る政策上の失敗を解消するものであり、運用品質やTEPCO parityを認証するものではない。

## Prediction Driftの扱い

Prediction driftは変化リスク指標であり、精度指標ではない。

- 基準内のdriftは通常自動昇格条件として利用する。
- 基準超過でも過去holdoutの誤差を低減する場合は`shadow_required`へ移行する。
- 大きな時間driftが誤差を修正する方向か、新たなshape歪みを作るかをfrozen-origin replayで確認する。
- driftだけを理由に明らかに悪いChampionを無期限に維持しない。

## 昇格後監視とRollback

- 安定化期間中は以前のChampion artifactとmetadataを保存する。
- 新Champion配信後も3確定運用日は以前のChampion shadow予測を生成する。
- 48時間以上の確定値で新Champion MAEが旧Champion shadowより10%以上悪い、または重要segment MAEが10%以上悪化した場合はrollbackレビューを開始する。
- データsource、artifact互換性、forecast coverageの欠陥は精度に関係なく即時rollback理由となる。
- rollback判断と原因をmodel-promotion履歴に保存する。

## 昇格Report契約

`metrics/model_promotion.json`には最低限、次を保存する。

- Champion version、artifact SHA、training cutoff、config fingerprint
- Challengerの同一項目
- 28/56/84日Champion対Challenger指標
- as-served Champion healthと弱点segment
- absolute gateおよびrecovery gate結果
- prediction driftと処理結果
- `promoted`、`rejected`、`shadow_required`、`champion_degraded`、`recovery_candidate_ready`、`recovery_approval_rejected`、`recovery_promoted`、`rolled_back`状態
- 最後の定期評価結果と次回評価時刻

評価日以外のETLによる`not_scheduled`結果が、最後の定期評価詳細を上書きしてはならない。

## 現在プロジェクトへの適用判断

- v14 `q025_q50_q975_p95_v14_daily_level_calibration`を学習cutoff 2026-08-19で生成し、2026-08-21 JSTに隔離stagingで復旧昇格した。remote data配備は別のoperator作業である。
- 最終artifactはv11の時間別booster 4つをbyte単位で保持し、非営業日q50と日次level補助modelだけを追加する。棄却した全体再学習候補と独立D+1 modelは含まない。
- 同一cutoff v14 MAEは28日1142.5MW、56日972.0MW、84日871.5MWで、v11比8.29%、3.36%、3.27%改善し、未配備v13参考contractも悪化させなかった。
- 最新`origin/data` cache基準の今日・翌日prediction driftは平均104.4MW、最大208.8MWでoverrideは不要だった。今日は前日の確定実績23時間と最後の1時間fallbackを使い、coverage不足の翌日はv11と完全に一致した。
- staging artifact SHA-256は`77a35437305d60de841d2277bc2ed636878f0170a2386d727312397ba1b8a3d3`、v11 rollback SHA-256は`28b75352b8b13713aba04880111dd11b3450864a3580f355081072af4266a640`である。

## 実装状態

- 実装済み: 同一cutoff v11/v13/v14 replay、絶対/recovery gate、degraded health、28/56/84日検査、drift分岐、`lastEvaluation`、shadow/rollback artifact保持、fail-closedな通常shadow承認、明示的緊急復旧承認。
- 実装済み: append-only matched-vintage capture、120秒以内の過去同一実行import、lead bucket指標、日付block bootstrap。
- 収集中: 28/84日matched-vintage履歴。完了前の`forecast_accuracy.json`は最新値ベースの運用参考に限定する。
- operator公開前の残作業: 隔離stagingの正確なartifactとreportをdata branchへ公開する。公開後に72時間安定化、旧Champion shadow比較、最低48確定時間で明確な退行が確認された場合のrollback reviewを開始する。
