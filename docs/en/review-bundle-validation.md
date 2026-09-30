# Review Bundle Validation Summary

[Architecture and usage](review-bundle-cli.md) | [한국어](../ko/review-bundle-validation.md) | [日本語](../ja/review-bundle-validation.md)

This validates evidence preservation and selective retrieval, not forecast improvement, candidate promotion or token savings. Stored contract `review-bundle/0.2.0-design` and view contract `review-bundle-batch/1.1.0` remain independent of production.

## Failures and Corrections

| Stage | Finding | Preserved correction |
|---|---|---|
| v0.1 offline | A smaller initial packet omitted followup/candidate links; 10 of 26 boundary checks failed | Size alone is not evidence preservation |
| Missing/boundary input | Empty/fallback-only actuals, wrong dates, absent advance evidence, missing pointers/sources and overflow were incomplete | Structured unavailable, locators and nulls instead of zero/latest substitution |
| Q13 oracle audit | Nearest issuance selected a different row from the intended candidate degradation | Preserve the original result; preregister the exact issue/target in Q13-v02 |
| v0.2 | Added scopes, date/run indexes, all changed/degraded candidate pairs and notice/chunk/source links | Keep counterexamples beyond top-N and unknown provenance |
| CLI | Initial allowlist omission and Windows CRLF byte-count mismatch | Correct namespaces and UTF-8/LF output, not broader arbitrary access |
| Batch/refinement | Repeated single queries and long provenance; deferring every small list increased size | Shared registries, multi-hour queries and explicit compact/expanded references |

Q13-v02 fixed the 2026-09-06 12:25:35 JST issue/14:00 target, not the nearest 13:30 issue. Q16 preserved all four changed and three degraded pairs; two degraded pairs had negative lead and were not prospective failures. These are historical tooling fixtures, not Candidate A or September 30 model research.

The v0.2 development record also retained a string-valued model-metadata error and errors in test pointer counts/key names. They were corrected and revalidated, not retrospectively described as first-attempt success. Public documentation preserves the lessons without duplicating session logs.

## Current-code Verification: September 30, 2026

| Check | Result |
|---|---:|
| Public synthetic core/CLI/security/batch/refinement suite | **76 passed**, zero skips, 21.67 seconds |
| Frozen historical recovery questions through the real CLI | **16/16** |
| Frozen boundary/loss cases | **33/33** |
| Stored-artifact Draft 2020-12 validation | **46 artifacts, zero errors** |
| Batch schema/registry and compact/expanded, single/multi-hour equivalence | Passed in pytest |
| Identical-input bundle/details/index/access seal regeneration | Identical bytes/hashes |
| Historical input, original v0.2 records and outputs before/after queries | Unchanged |
| Model API calls in this publication work | Zero |

Executed on Windows, Python 3.14.4, pytest 9.0.3 and local development-only jsonschema 4.26.0. Public tests generate synthetic evidence without private data. Two new-test setup errors initially expected chunks from a small fixture and omitted mandatory date selectors. The fixtures/selectors were corrected to exercise real overflow and valid queries; existing assertions, calculation rules and bounds were not weakened.

`jsonschema` is a development dependency, not a production dependency. Schema tests no longer silently skip if it is missing. [Test commands](review-bundle-cli.md#tests-and-scope) cover the public suite. Publication did not change the validated CLI calculation/selection/security implementation or stored schema.

The 16 questions cover completeness/finalization, published versus advance populations, MAE/RMSE/WAPE/bias, opposite-direction/time-band structure, same-run stages, publication vintage, intervals/exclusions, controls, missing issue-time weather, noon deltas, followup corrections, policy changes, exact candidate counterexamples, missing gates/all changed pairs, and governance.

The 33 boundary cases cover empty/fallback inputs, zero denominators, NaN/Inf, duplicate timestamps, timezone/date mismatch, provisional revisions, missing TEPCO, residual order/small shape/gaps/opposing extremes, adverse rows beyond top-N, policy mismatch, absent advance/control evidence, tampered hashes, missing pointers/sources, overflow, minimum sample changes, retained versus passed, secrets, cache identity, alternative runs, failed gates, unavailable populations, fact locators and schema mutants.

A successful missing-provenance test means unavailability was preserved, not that provenance was recovered. Missing gates do not count as candidate approval. Determinism was verified at the same local paths; absolute source locators mean cross-machine byte identity is not promised.

## Read-only Boundary

Public tests exercise root/traversal rejection, source hash/length checks, retention loss, allowlists, no query writes, confined build writes, denied `.env`/subprocess/socket access, full-detail dump rejection, and Windows symlinks/junctions/hardlinks. Hosts without a platform-specific link capability report that limitation explicitly.

This is a trusted-Python command-body guard, not an OS sandbox. Startup/imports, hostile tool code, concurrent external changes and metadata-preserving cache tampering are not proven isolated. Raw detail/followup internals are not all covered by a complete formal subtype schema; recovery and semantic tests supplement schema validation.

## Manual Review Observations

| Metric | First manual review | Second manual review | Refined replay of the second question set |
|---|---:|---:|---:|
| Evidence CLI commands | 83 | 13 | 11 |
| Returned bytes | 328,849 | 255,913 | 218,477 |
| Internal logical read bytes | 22,658,704 | 7,308,680 | 6,473,451 |
| File-open events | 428 | 126 | 112 |
| Raw-source read events | 2 | 3 | 3 |
| Raw-source bytes | 327,041 | 556,803 | 556,803 |
| Command-body seconds | 44.739833 | 7.604760 | 5.921800 |

**83 to 13 compares different manual trials; 13 to 11 is deterministic reproduction of the same 13 questions after refinement.** This is not a controlled benchmark. The first 83 includes one failed pointer query and excludes one help call.

The second review made no explicit raw-source commands, but hour-review automatically read three sources to verify observation cutoffs. Reduced direct exploration is not reduced raw I/O. Refinement reduced total returned bytes and interactions but increased the largest response from 34,161 to 49,125 bytes. Membership summaries may also read more internally than a simple index query.

Ten separate expansion/equivalence/determinism checks returned another 658,787 bytes and read 6,325,261 bytes internally. They were recorded separately, not hidden in the 11-command review path. OS cache was uncontrolled; command-body I/O excludes interpreter startup/imports and reporting.

**Codex input/output/cached/reasoning tokens and model turns are unavailable/null.** Neither bytes nor CLI calls are converted into tokens. These observations support reduced evidence-retrieval interaction and reconstruction work, not a token/cost savings percentage or causal performance guarantee.

## Reproducibility and Publication Scope

Code, schemas and self-contained synthetic tests are public. The retained historical corpus was rerun locally: input manifest hash `e944f9e9f6861d90fe575acedb0ff7c91413ae1c22ed704aff1a2496520c03bf`, bundle seal `f80d7c74b0c3e57ebd84b2b631db924b3cfde01decba2ce063859dedc8e40a27`. The full historical corpus is not distributed, so the complete historical run is not claimed reproducible from the public checkout alone.

Generated date bundles, query dumps, capture/replay intermediates, session seals/handoffs, private notes, Jev detailed experiments, Candidate A and September 30 research are excluded. Public documentation is consolidated into architecture/usage and this validation summary. Recommendation: use as an independent manual-review tool while continuing to inspect missing evidence and counterexamples, not as a forecast or promotion authority.
