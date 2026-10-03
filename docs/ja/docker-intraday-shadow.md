# Docker Multi-Challenger Shadow

[English](../en/docker-intraday-shadow.md) | [한국어](../ko/docker-intraday-shadow.md)

## 役割と隔離

Production championは従来予測を維持する。`intraday-shadow`はpublic GitHub `data` branchを読む独立sidecarで、結果をforecasting/ETL/scheduler/serving policy/promotionへ渡さない。OpenAI/Jev呼び出しとAPI keyは不要。

```text
data branch -> 専用shallow bare Git -> allowlisted source cache
  snapshot -> issue-time特徴を一度生成 -> 最大3 ACTIVEモデル -> immutable prediction
  actual + ETL-state -------------------------------------> immutable evaluation
read-only registry/model mount                 shadow専用writable named volume
```

Imageには評価moduleとpinned dependencyだけをコピーする。`.env`、checkout、production output、ETL code、host HOME、Docker socketはmount/copyしない。Root filesystemと`/shadow-input`はread-only。UID/GID `10001:10001`、capability削除、`no-new-privileges`、ephemeral `/tmp`を使用。Named volumeは`tokyo-grid-ems-intraday-shadow`、workspaceは`/app/data/intraday_challenger/live`。

専用bare repoの`refs/heads/shadow-data`だけをfetchしproduction refsは変更しない。Public HTTPSでhost credential helper/configを使わない。

## SourceとPolling

| Source | 用途 | 欠落時 |
|---|---|---|
| `reports/internal/operational-calibration/snapshots/<date>/*.json` | Issue-time完了観測/cutoff、raw/pre/post、特徴、champion reference | Prediction unavailable |
| `actual/<date>.json` | 後から対応させる実測評価 | Error null/unavailable |
| `.etl_state.json`の`okDates` | 確定日/coverage | Finalizedと推定しない |

Published forecast、一般metrics、latest weatherは読まない。Champion referenceは**same-run recorded post**でpublished/advanceではない。未確認champion artifact/policy identityとnative challenger intervalはnull/unattested。

Pollingは**600秒**。Sourceは主に2時間間隔、朝はhourly、日付切替/late catch-upもある。10分はcadenceより短くproductionと結合しない。一定条件の平均検知遅延約5分は実capture時刻を代替しない。不変revisionはtree/blob/evaluation再処理を省き、新revisionでも同じblobを再利用。Event-driven通知はfuture optionでproduction hookは追加しない。

## Registryと参加条件

契約は`intraday-shadow-registry/1.0.0`、[schema](../../docker/shadow-registry.schema.json)。Name/version、identity SHA、artifact fingerprint/path、feature schema/dataset identity、cutoff、activation、research除外、qualification/legacy referencesを固定。

- Championは別referenceで**ACTIVE challengerは最大3件**。`ACTIVE`、`PAUSED`、`RETIRED`を使う。上限超過は拒否、retirementは人が決定し自動削除しない。
- 更新時はregistry versionを上げ旧bytesを保存。既存identity metadataの変更/削除は禁止、statusのみ変更可能。Artifact変更は同名でも新identity。
- 追加/再開時に実adoption以降のactive epochを記録。過去snapshotを独立標本へ遡及しない。
- 現loaderはfrozen L1/L2/L3とL4/L5契約をサポート。異なるL6/L7 architectureには検証済専用loaderが必要でL5 source hashを変えない。

Baseline分布に基づく基準を研究前にpreregisterしbroad replay、chronological/walk-forward、全体/対象改善、tail、既知反例、deterministic identity、隔離testを検証。Zero regressionは要求しない。Registryはhash-pinned qualification gatesとdataset identityを確認する。これは**shadow参加のみ**でproduction昇格ではない。

L5のidentity/結果/限界は[lead-aware研究](lead-aware-intraday-shadow.md)を参照。旧model bytesとlegacy captureはread-only contextとして保存し新独立件数に加算しない。L5収集中もL6/L7研究/replayをすぐ進められる。

## Captureと独立標本

契約は`intraday-multi-shadow-capture/1.0.0`。Snapshot parsing/issue-time特徴を共有し推論はモデル別。完了観測/cutoffだけを使い後取得actualは入力しない。`recordedAt`は**モデルごとの推論完了時刻**。

Issue/capture時刻、target、両lead、delay、raw/pre/post/reference、challenger、cutoff、source revision/hash/pointer、identity、除外理由を保持。Filenameは完全record SHAで内部identityを固定。Identity+snapshot dedupは再起動後も維持。同一issueの異なるsource revisionはunavailable/rejectionとして旧予測の上書き/二重計数を避ける。

`targetTiming`は完了時のprospective/retrospective。`captureStatus`は15分超ならdelayed、それ以外はprospective/retrospective。独立live条件はissueがactivation/active epoch以降、target前の完了、delay <=**900秒**、training/research使用日でないこと。900秒は600秒poll +180秒Git timeout +120秒余裕の**収集policy**でforecast thresholdではない。Workspaceに固定し別policyを混ぜない。

Offline backlog、delayed、retrospective、pre-activation、research使用日はcontext-only。当時のlive predictionとは称さない。各新候補は自身のactivation以降から別に集める。

## EvaluationとReadiness

契約は`intraday-multi-shadow-evaluation/1.0.0`。Actual state/hash/revision、両モデルのsigned/absolute error、absolute-error deltaを保存。Forecast fallback/未来/欠測actualは観測ではない。Provisional→finalizedと値のrevisionごとに新immutable評価を作り旧prediction/evaluationを残す。

Identity、independent/context-only、finalized/provisional、all-positive/closest `(0,120]`を分離。MAE/RMSE/WAPE/bias、time/lead band、日別優劣、改善/悪化数、悪化p90/p95/max、same-target issue revision、same-run target transitionを計算。Retired historyも維持。

Sample readinessは確定日>=14、営業日>=8、非営業日>=4、確定prospective pair>=300、closest target>=150。**Promotion readinessは別で常にfalse**。Native interval/champion identity/policy不足は残る。採用にはexplicit serving-policy identity/version更新と通常validation/promotionが必要。10/18は条件付き確認日で自動承認日ではない。

## 準備と起動

Trained artifact、qualification、generated evidenceはGitに含めない。Local frozen modelを以下で準備する。学習/API呼び出しはしない。

```powershell
python scripts/prepare_intraday_shadow.py --model-root data/intraday_challenger/<model> --identity-sha <sha256> --qualification data/intraday_challenger/<research>/RESULTS.json --qualification-sha <sha256> --research-range <first-used-date> <last-used-date> --name L5 --version 1
docker build -f docker/shadow.Dockerfile -t tokyo-grid-ems-intraday-shadow:1.0.0 .
docker compose run --rm --no-deps -T intraday-shadow python -m python.eval.intraday_challenger.service run --cycles 1
docker compose up -d intraday-shadow
```

Research rangeは繰り返し可能。既存deploymentは上書きしない。新候補のartifact/qualificationは別pathに準備し旧entryを維持したregistry versionを上げる。Serviceは各cycleでregistryを確認。[設定例](../../docker/shadow-config.example.json)。

## Monitoringと復旧

```powershell
docker compose ps intraday-shadow
docker compose logs --tail 50 -f intraday-shadow
docker compose exec intraday-shadow python -m python.eval.intraday_challenger.service status
docker compose exec intraday-shadow python -m python.eval.intraday_challenger.service health
docker compose restart intraday-shadow
docker compose stop intraday-shadow
```

Statusはservice start、last loop/sync/revision/snapshot/prospective prediction/actual/evaluation、active identities、件数、error/healthを記録。Logsはstartup/sync/no-change/snapshot/prediction/duplicate/delayed/actual-revision/evaluation/identity-change/recoverable/fatal/shutdownを区別しcredential/remote stderrは出さない。Docker logは10 MiB x3 rotation。

Healthはloop/status age >2100秒、fatal/stopped、workspaceアクセス失敗を検知。**新sourceがないだけではunhealthyではない**。Network failureは次の600秒Python cycleで再試行。Dockerはunhealthyだけで自動restartしないためhangは調査/手動restart。

`unless-stopped`はengine再開時に稼働していたserviceを復旧しmanual stopを維持。Windows boot/scheduler登録は追加しない。Docker Desktop **Settings → General → Start Docker Desktop when you sign in to your computer**を有効にする。[Startup設定](https://docs.docker.com/desktop/settings-and-maintenance/settings/)、[restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/)。PC/engine停止中はlive収集不可。

Volume OS lockは別Compose projectの二重workerも拒否。`docker compose down -v`やvolume削除は使わない。Evidence自動削除はしないためdisk容量を管理する。Source retentionで最新label provenanceが消えればunavailableとし旧immutable評価/cacheを保持。

## 検証と制限

2026-10-03関連suite **291件通過**: registry/Draft 2020-12 schema、identity、ACTIVE上限、retirement/history、shared parsing、leakage/cutoff、完了boundary、遅延/activation/research除外、actual revision、不変/dedup、no-change/network/health、path/secret隔離、ETL Compose不変性。Schema validatorはlocal dev/test専用でproduction dependencyは変えない。

実Linux Dockerでfinite sync/capture/evaluation、read-only書込拒否、API key/ETL不在、frozen L5 Windows/Linux予測一致を確認。Process/restart/health/no-changeは別のdeployment確認。PC稼働率、publication遅延、native interval/historical provenanceの制限は残る。Review Bundleは人間の根拠閲覧用でこの継続収集serviceとは別役割。
