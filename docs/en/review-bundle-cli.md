# Model Review Evidence Bundle and Read-only CLI

[한국어](../ko/review-bundle-cli.md) | [日本語](../ja/review-bundle-cli.md) | [Validation](review-bundle-validation.md)

Review Bundle is this project's local review evidence package, not an industry standard or a decision engine. It prepares deterministic facts and indexes from explicitly frozen inputs. It does not run forecasting, replay, promotion, ETL, Jev, or a model API. Publication does not connect it to normal review automation.

## Motivation and Architecture

Previously, a reviewer or reasoning model repeatedly located actuals, published forecasts, issue-time snapshots, calibration stages, intervals, and governance records, then reconstructed their populations and timing. Advisory prioritization with a small model was explored, but evidence reconstruction remained a separate bottleneck. This tool moves that preparation into Python rather than adding another judgment model.

```text
Frozen local copies + hash manifest
  -> deterministic Python calculations and scope/date/run indexes
  -> initial packet + sealed sections/details/indexes
  -> batch/read-only CLI
  -> human reviewer or reasoning model
  -> selective detail/source drill-down when a question requires it
```

Large raw artifacts are not the default review context. The compact packet supplies navigation and notices, not permission to ignore unhighlighted areas. The reasoning model still interprets evidence; existing replay and promotion rules still govern changes.

The [package](../../python/eval/review_bundle) contains:

| File | Responsibility |
|---|---|
| `core.py` | Frozen calculation, selection, indexing and chunk rules |
| `access.py` | Explicit roots, content addressing, hashes and command-body access guard |
| `cli.py` | Build, selective queries, structured errors and I/O telemetry |
| `batch.py` | Review-oriented views with shared registries |
| `review-bundle.schema.json` | Draft 2020-12 stored-artifact contract |
| `review-view.schema.json` | Draft 2020-12 batch-view contract |

Stored contract: `review-bundle/0.2.0-design`. Presentation contract: `review-bundle-batch/1.1.0`. Historical contract strings remain for compatibility. The runtime uses only the standard library and imports no private workspace, generated experiment artifact, or environment-key loader.

## Populations Must Stay Separate

| Basis | Meaning |
|---|---|
| published | Forecast retained at the scope revision, not necessarily its first publication |
| advance | Minimum positive lead within 120 minutes in the same capture; equal TEPCO issuance is unknown |
| stages | Same-run raw/pre/post, not interchangeable with a later recalculation |
| retrospective | Nonpositive-lead retained evidence, not prospective confirmation |
| interval | Independently selected retained interval snapshots |
| followup | Separate revision with additions/corrections; does not overwrite the original as-of |
| candidate | Every recorded issue/target pair, including changed and degraded pairs; not promotion approval |

Missing model/policy identity, weather provenance, training/holdout/gates remain null. Shared source references do not imply compatible populations. A selected interval history is not necessarily the published file's interval profile.

## Input and Build

Use Python 3.12+ from the repository root, including junction detection on Windows. No API key or `.env` is needed.

```text
local-workspace/
  review-inputs/
    manifest.json
    sources/<sha256>.json
    sources/<sha256>.md
  review-bundles/
    <bundle-name>/
```

The root basenames are enforced. Create the parent directory first; roots must not overlap or point into production directories. This tool does not fetch, discover the latest files, or traverse Git history. Prepare dedicated copies and record their actual hashes, lengths, revision, capture time and finalization state.

Manifest outline (replace placeholders with verified values):

```json
{
  "schemaVersion": "review-bundle-input/0.2.0",
  "scopes": [{
    "id": "primary", "role": "primary", "captureKey": "20",
    "revision": "captured-source-revision",
    "asOf": "2026-09-20T21:37:00+09:00",
    "capturedAt": "2026-09-20T22:09:33+09:00",
    "finalizedThrough": "2026-09-19"
  }],
  "inputs": {
    "20:actual/2026-09-20.json": {
      "path": "sources/<sha256>.json", "sha256": "<sha256>", "bytes": 1234
    }
  }
}
```

Also register forecast, required snapshots/calibration, scope metadata and governance evidence. Logical input keys map to content-addressed copies. Supported roles are `primary`, `followup` (with `parentScope`), and `candidate_validation` (optional recorded `expectedIdentity`). Candidate input uses `candidate:lift_replay.json`; governance uses `extra:metrics/model_promotion.json` and `extra:metrics/operational_replay.json`. These are read identifiers, not executable production paths. Missing input is never replaced by a later file.

PowerShell example:

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

The module also runs on other Python platforms with the same CLI arguments. Only `build` writes, to a new named bundle. It refuses overwrites. A failed partial directory without a successful seal is incomplete. `--input-sha` fixes the manifest bytes; `--bundle-sha` fixes `access.json`. Do not replace hashes to bypass a mismatch; create a separately identified capture/bundle.

## Review Workflow and Commands

Start with initial/notices/scopes, then recent metrics, direction/shape, stages/intervals, and suspicious hours. Inspect completeness/finalization, cancellation in bias, ramps, guard counterexamples, interval history, vintages, artifact/policy identity, missing provenance and governance even if the overview does not highlight them. Record the concrete question before raw drill-down.

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

| Interface | Selective result |
|---|---|
| `review-summary` | One date's coverage/metrics/bands/shape/noon/stages/advance/interval/weather |
| `metrics-inventory`, `direction-screen` | Multi-date metrics or directional structure |
| `stage-interval-review` | Raw/post summary, both error extremes, all-adverse references and interval history |
| `hour-review` | Independent published/advance/stages/interval rows, control/run/cutoff for selected hours |
| `membership-summary` | Retained basis/lead membership, not a performance population |
| `paths` | Valid child pointers and structure, not a full dump |
| `facts`, `fact` | Scope/date fact inventory or one context-enveloped fact/pointer |
| `indexes`, `metadata`, `provenance` | Date/run membership, method/population, source/hash references |
| `notices`, `manifests`, `chunk` | Mandatory notices, section/chunk manifests, one initial chunk |
| `resolve --kind detail/source` | Nonempty RFC 6901 pointer into linked evidence |

Use `--help` for all selectors. Ordinary arrays have `--offset/--limit` (default 20, maximum 200); batch dates have a maximum of 31 per page. Follow `nextOffset` until null. Explicit absent dates remain unavailable; a date range lists registered dates, not guaranteed calendar coverage. Use `--date` for single-date views and `--hour` or distinct `--hours`, never both.

Source resolution requires a source/pointer obtained from the selected fact's provenance/index. It cannot open arbitrary sources. Nonpositive lead remains retrospective. Candidate pairs can be filtered with exact `--date/--hour/--issued-at`; never substitute the nearest/latest issue for a specified counterexample.

## Response and Batch Contracts

Stdout is one UTF-8 JSON object with `context/state/value`. Every fact retains scope/as-of/window, method, population identity, sample count, notices and provenance. Never extract a bare number as an interchangeable metric. `compatibleBasesAssumed` and `promotionAuthorization` stay false.

Batch `dates[].sections` and `scopeSections` retain independent states/populations. Multi-hour views use `dates[].targets[]`. Registries share methods, exact recorded identities, provenance, details, notices and sealed files. Short IDs such as `i0` are local to one response. Unknown identity is not filled from the scope or published forecast.

- Long source lists are deferred with counts, a list hash and sealed expansion query; short lists may stay inline. This is a byte-size presentation choice, not evidence selection. Source count is not sample count.
- `--expand-provenance` and `provenance` expose references. `--expand-details` restores the full stage summary. `evidenceQueries.allAdverseHours` keeps every degraded hour reachable. Stage `absErrorDelta` is post absolute error minus raw absolute error; negative means improvement.
- The parent population and selected row count/state are separate. `rowIdentityCohorts` preserves distinct recorded identities. Matching source/pointer is required for run context.
- `hour-review` verifies the raw source hash when reading `/correction/lastObservedHour`. Missing field/source/hash mismatch yields structured unavailable. This automatic read is counted as raw I/O; fewer explicit source commands do not imply less source I/O.
- `membership-summary` has null population/sampleCount and method `index_membership_not_comparable`. Positive lead presence is not a claim about the entire archive or completed actual pairing. Eligible interval index rows and actually selected interval rows are separate. Candidate uses its pair index instead.
- Initial target remains 32,768 bytes. Overflow has explicit notices, section/chunk manifests and continuation; an oversized single fact is retained. General batch responses are not byte-capped. Multi-hour queries can increase the largest response. Initial-only inspection is not a complete review.

Missing metrics stay null, not zero. Query exit 0 can contain partial/unavailable evidence. Failed resolution returns exit 2 and structured codes such as `SOURCE_HASH_MISMATCH`, `RETENTION_LOSS`, `MISSING_POINTER` or `UNAUTHORIZED_ROOT`. Invalid CLI syntax uses argparse errors. No latest-file, retrospective, identity or candidate-gate substitution is performed.

## Read-only Boundary and Measurement

The CLI enforces dedicated roots, an input allowlist, content-addressed names and SHA256 checks. It rejects traversal, absolute/drive-injected source paths, UNC roots, symlinks, junctions and hardlinks. Credential, `.env`, Codex/history and Jev paths are excluded. During command execution a Python audit hook blocks unauthorized file opens, mutations, subprocesses and sockets. Queries cannot write; builds can write only inside their new bundle.

This is **not an OS sandbox** or protection against hostile Python code. Interpreter/import startup precedes the guard. Use trusted Python, unchanged tool code, and frozen local copies. Concurrent external mutation, metadata-preserving cache tampering, mapped network drives and kernel-level bypass are not covered guarantees. The core is an internal calculation module; the supported guarded entry point is the CLI.

Stderr contains command-body measurement JSON: returned bytes, file-open events, unique files, logical content reads, raw source bytes and elapsed time. Selective output may require parsing full internal sections. These are not physical disk I/O, startup timing or model tokens. Model token telemetry is null; no byte-to-token conversion is used.

## Tests and Scope

```powershell
python -m pip install pytest "jsonschema>=4.18,<5"
python -B -X utf8 -m pytest tests/test_review_bundle_core.py tests/test_review_bundle_cli.py tests/test_review_bundle_batch.py tests/test_review_bundle_refinement.py -q -p no:cacheprovider
```

The public tests create synthetic local evidence and need no historical private corpus. Schema checks require the development-only `jsonschema` dependency rather than silently skipping. Platform-specific link tests report unavailable host capabilities explicitly. Additional frozen historical recovery/boundary results and manual measurements are summarized in [Validation](review-bundle-validation.md); generated bundles and session logs are intentionally not distributed. No scheduler, ETL, AGENTS or model configuration integration is included.
