# モデルレビューの根拠パッケージと読み取り専用 CLI

[English](../en/review-bundle-cli.md) | [한국어](../ko/review-bundle-cli.md) | [検証結果](review-bundle-validation.md)

Review Bundle は、このプロジェクトのローカルなレビュー根拠パッケージであり、標準規格や意思決定エンジンではない。固定した入力から数値と索引を決定的に生成する。予測、replay、昇格、ETL、Jev、モデル API は実行せず、通常のレビュー自動化にも接続しない。

## 背景と構造

従来は、レビュー担当者や reasoning model が actual/forecast、発行時点の snapshot、補正段階、区間履歴、governance を繰り返し探索し、母集団と時点を再構成していた。小型モデルによる調査優先度の助言も試したが、根拠の再構成は別の負担として残った。そのため判断モデルを追加するのではなく、Python に事前計算と索引化を担当させる。

```text
固定したローカルコピー + hash manifest
  -> Python: 数値計算、scope/date/run 索引、null と notice の保持
  -> Bundle: 初期 packet + sealed sections/details/indexes
  -> batch/read-only CLI
  -> 人または reasoning model によるレビュー
  -> 質問に必要な detail/source だけを追加確認
```

大きな raw artifact 全体を既定の入力にしない。ただし概要は判断の権限を持たず、強調されていない領域もレビュー対象となる。変更の判断には既存の replay・昇格方針を適用する。

[実装](../../python/eval/review_bundle)は `core.py`（計算・選択・chunk）、`access.py`（root/hash/アクセス制限）、`cli.py`（構築・照会・計測）、`batch.py`（質問別表示）からなる。`review-bundle.schema.json` と `review-view.schema.json` は Draft 2020-12 の保存形式・表示形式を定義する。

保存契約は `review-bundle/0.2.0-design`、表示契約は `review-bundle-batch/1.1.0`。互換性のため過去の契約文字列を維持する。標準ライブラリのみを使用し、private workspace、生成済み実験データ、環境キーの loader を import しない。

## 母集団の区別

| Basis | 解釈 |
|---|---|
| published | scope revision に残る公開予測。初回発表値とは限らない |
| advance | 同一 capture の最小正 lead、120分以内。TEPCO と同じ発表時点かは unknown |
| stages | 同一 run の raw/pre/post。別 run の事後再計算に置換しない |
| retrospective | lead が0以下の記録。先行予測の検証には数えない |
| interval | 独立に選択した retained interval snapshot の母集団 |
| followup | 別 revision の追加・訂正。元の as-of を上書きしない |
| candidate | 記録された全 issue/target pair。悪化を保持し、昇格を承認しない |

model/policy identity、気象 provenance、training/holdout/gates の欠落は null のままにする。共有された source 参照は母集団の互換性を意味しない。公開ファイルの interval profile と選択済み過去 snapshot の履歴も区別する。

## 入力と構築

Python 3.12 以上を使い、リポジトリ直下から実行する。Windows junction 検査も含む。API キーや `.env` は不要。

```text
local-workspace/
  review-inputs/manifest.json
  review-inputs/sources/<sha256>.json または .md
  review-bundles/<bundle-name>/
```

root の末尾名は固定で、親ディレクトリを事前に用意する。入力・出力を重ねず、production ディレクトリやユーザーホームを指定しない。ダウンロード、最新ファイル探索、Git history の探索は行わない。

Manifest は `schemaVersion: review-bundle-input/0.2.0`、`scopes`、`inputs` を持つ。Scope は `id/role/captureKey/revision/asOf/capturedAt/finalizedThrough` を記録する。Role は `primary`、`followup`（`parentScope` 必須）、`candidate_validation`（記録済み `expectedIdentity` は任意）。Input は `20:actual/2026-09-20.json` のような logical ID をキーとし、`path: sources/<sha256>.json`、実際の `sha256` と `bytes` を持つ。[完全な manifest 例](../en/review-bundle-cli.md#input-and-build)を参照。

必要な forecast、snapshot、calibration、metadata、governance のコピーも登録する。Candidate の logical key は `candidate:lift_replay.json`、governance は `extra:metrics/model_promotion.json` と `extra:metrics/operational_replay.json`。実行パスではなく読み取り対象の識別子である。不明な revision/cutoff/確定状態は推測しない。

```powershell
$inputRoot = 'C:\local-workspace\review-inputs'
$outputRoot = 'C:\local-workspace\review-bundles'
$inputSha = (Get-FileHash -Algorithm SHA256 "$inputRoot\manifest.json").Hash.ToLowerInvariant()
$common = @('--input-root', $inputRoot, '--input-sha', $inputSha,
            '--output-root', $outputRoot, '--bundle', 'review-2026-09-20')
$built = python -B -X utf8 -m python.eval.review_bundle build @common 2> build-io.json
if ($LASTEXITCODE -ne 0) { throw 'Bundle build failed' }
$seal = ($built | ConvertFrom-Json).value.bundleSealSha256
$query = $common + @('--bundle-sha', $seal)
python -B -X utf8 -m python.eval.review_bundle initial @query
```

他の OS でも同じ CLI 引数を使える。書き込みは `build` の新規 bundle のみで、上書きは禁止する。成功した seal のない部分生成ディレクトリは未完了。Hash 不一致を回避するため既存の hash を差し替えず、新 capture として別 bundle を作る。

## 手動レビューと照会

Initial → notices/scopes → metrics inventory → direction/shape → stages/interval → 問題の時間 → 必要な詳細・原本、の順を基本とする。完全性と確定状態、bias の相殺、ramp、補正反例、区間履歴、vintage、artifact/policy、provenance 欠落、governance を省略しない。Raw 参照前に、概要だけでは回答できない具体的な質問を記録する。

```powershell
python -B -X utf8 -m python.eval.review_bundle notices @query
python -B -X utf8 -m python.eval.review_bundle scopes @query
python -B -X utf8 -m python.eval.review_bundle metrics-inventory @query --scope primary --from 2026-09-07 --to 2026-09-20
python -B -X utf8 -m python.eval.review_bundle direction-screen @query --scope primary --dates 2026-09-18,2026-09-19,2026-09-20
python -B -X utf8 -m python.eval.review_bundle stage-interval-review @query --scope primary --date 2026-09-20
python -B -X utf8 -m python.eval.review_bundle hour-review @query --scope primary --date 2026-09-20 --hours 9,12,18
python -B -X utf8 -m python.eval.review_bundle membership-summary @query --scope primary --date 2026-09-20 --hour 0
python -B -X utf8 -m python.eval.review_bundle paths @query --fact-id primary:2026-09-20:stages
python -B -X utf8 -m python.eval.review_bundle resolve @query --kind detail --fact-id primary:2026-09-20:stages --pointer /stages --hour 9
```

`review-summary` は単一日の全領域を表示する。個別の `facts/fact`、`indexes`、`metadata`、`provenance`、`manifests/chunk` も利用できる。`resolve --kind source` は fact に明示的に接続された source と非空 RFC 6901 pointer のみを許可する。任意ファイルや sidecar 全体を直接返す機能ではない。候補反例では正確な `--date/--hour/--issued-at` を指定し、近い発行本で代用しない。

通常配列は `--offset/--limit`（既定20、最大200）、batch は1ページ最大31日。`nextOffset` が null になるまで参照する。日付範囲は登録済み日付の列挙であり、全暦日の確保を保証しない。明示した未登録日は unavailable として残す。単一日には `--date`、時間には `--hour` または重複のない `--hours` を使用する。

## 応答契約と不足状態

標準出力は UTF-8 JSON の `context/state/value`。Scope/as-of/window、method、population identity、sample count、notice、provenance を数値と一緒に読む。`compatibleBasesAssumed` と `promotionAuthorization` は false。単独の数値を異なる母集団へ流用しない。

Batch は `dates[].sections` と `scopeSections`、複数時間は `dates[].targets[]` を使う。Registry は正確に一致する identity/source/detail/notice を共有するが、`i0` などの ID は応答内だけで有効。不明な identity を published/scope から埋めない。

- 長い source 一覧は件数、一覧 hash、sealed 参照、expansion query に畳む。短い一覧は inline の場合がある。重要度による選別ではなく、source count は標本数でもない。
- `--expand-provenance`、`provenance`、`--expand-details` で展開する。`allAdverseHours` 参照は悪化した全時間を保持する。`absErrorDelta = post絶対誤差 - raw絶対誤差` なので負は改善。
- Parent population と選択した行数/state は別。`rowIdentityCohorts` は記録された identity を分離する。Run context は source/pointer の一致が必要。
- `hour-review` は原本 hash を検証して `/correction/lastObservedHour` を読む。欠落・変更時は unavailable。自動 raw 読み取りも計測するため、明示的 source コマンド数の減少を原本 I/O 減少と同一視しない。
- Membership は `index_membership_not_comparable`、population/sampleCount は null。Interval の保有候補と実際の選択行、保有 index の不在と全 archive の不在を区別する。Candidate は専用 pair index を使う。
- Initial の目標は32,768 bytes。超過時も notice と chunk/section/continuation を残し、単一の巨大 fact も削除しない。通常 batch は byte cap ではなく、複数時間では最大応答が大きくなることがある。

不足 metric は0ではなく null。Exit 0 でも一部 evidence は unavailable/partial になり得る。照会失敗は exit 2 と `SOURCE_HASH_MISMATCH`、`RETENTION_LOSS`、`MISSING_POINTER`、`UNAUTHORIZED_ROOT` などの構造化状態を返す。構文誤りは argparse error。最新値・事後値・推定 identity/gate で補わない。

## アクセス制限と計測

Dedicated root、allowlist、content-addressed name、SHA256 を検証する。Traversal、絶対/drive 注入パス、UNC root、symlink/junction/hardlink、credential/`.env`/Codex history/Jev パスを拒否する。Command body の Python audit hook が許可外 open、mutation、subprocess、socket を拒否する。Query は書き込み禁止、build は指定された新規 bundle 内だけ。

**OS sandbox ではない。** Interpreter/import 初期化は範囲外で、信頼された Python と未改変コード、固定したローカルコピーを前提とする。他プロセスの同時変更、同一 metadata を保つ cache 改変、mapped network drive、kernel bypass まで保証しない。公開の guarded entry point は CLI であり、core は内部計算モジュール。

Stderr の measurement JSON は返却 bytes、open events/固有ファイル、logical read bytes、raw source bytes、command-body 経過時間を記録する。小さな返却でも内部で section 全体を解析する場合がある。物理ディスク I/O、起動時間、モデル token と混同しない。Token telemetry は null で、bytes を token に換算しない。

## テスト

```powershell
python -m pip install pytest "jsonschema>=4.18,<5"
python -B -X utf8 -m pytest tests/test_review_bundle_core.py tests/test_review_bundle_cli.py tests/test_review_bundle_batch.py tests/test_review_bundle_refinement.py -q -p no:cacheprovider
```

公開テストは synthetic なローカル入力を作り、private corpus を要求しない。Schema 検証には開発用 `jsonschema` を要求し、欠落を黙って skip しない。Host が利用できない platform-specific link 検査は明示する。歴史的な16問・33境界検査と手動試行の結果は[検証文書](review-bundle-validation.md)に要約する。日別 bundle、session log、実験生成物は公開しない。Scheduler、ETL、AGENTS、モデル設定の変更は含まない。
