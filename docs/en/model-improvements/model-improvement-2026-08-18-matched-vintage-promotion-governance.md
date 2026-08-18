# 2026-08-18 Matched-vintage TEPCO evaluation and promotion governance

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-08-18-matched-vintage-promotion-governance.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-18-matched-vintage-promotion-governance.md)

## Problem

TEPCO revises its same-day forecast repeatedly and may also revise values for elapsed hours. The existing `forecast_accuracy.json` compares finalized actuals with the last TEPCO value left in each file, so it can mix this project's as-published forecast with a later TEPCO revision. The promotion gate also emphasized the seasonal baseline and absolute ceilings, leaving no explicit recovery path for a degraded Champion.

## Changes

- Every ETL/Intraday run captures future model and TEPCO forecasts together.
- Captures are append-only under `reports/internal/forecast-vintages/YYYY-MM-DD.json`; later TEPCO revisions never rewrite an earlier capture.
- Because TEPCO does not expose a separate `issuedAt`, the project's `capturedAt` is the observable forecast vintage.
- Evaluation is separated into `0-2h`, `2-4h`, `4-8h`, and `8-24h` lead buckets and operational time bands.
- `metrics/forecast_vintage_accuracy.json` records MAE, WAPE, RMSE, maximum error, model/TEPCO ratios, and a date-block bootstrap confidence interval.
- Formal qualification requires at least 80% paired-hour coverage in every lead bucket and time band. It also gates RMSE ratio, maximum-error ratio, and the upper bound of the paired bootstrap MAE-ratio interval; a favorable point estimate alone cannot qualify.
- Legacy forecast and calibration snapshots are imported only when target dates match and generation timestamps differ by no more than 120 seconds.
- Champion and Challenger contracts are replayed at the same training cutoff and holdout. Normal promotion and degraded-Champion recovery are separate paths.
- Recovery requires at least 10% MAE and WAPE improvement at 28 days, no more than 5% risk or critical-segment regression, and a consistent direction at 56/84 days.
- High-drift or not-yet-approved candidates are retained as shadow artifacts. Promotion preserves the previous Champion as a rollback artifact.
- Recovery promotion fails closed until `metrics/model_shadow_evaluation.json` confirms at least 72 shadow forecast-hours and two finalized days. An explicit approval flag is still required afterward.
- Non-evaluation ETL runs retain the last detailed decision in `lastEvaluation`.

## Reproduction result

The v13 and v11 contracts were compared at an identical training cutoff.

| Window | v13 MAE | v11 contract MAE | v13 improvement | Decision |
|---|---:|---:|---:|---|
| 28 days | 1,275.8MW | 1,351.7MW | 5.62% | Below 10% recovery threshold |
| 56 days | 983.8MW | 1,016.0MW | 3.17% | Better direction, insufficient margin |
| 84 days | 891.6MW | 916.8MW | 2.75% | Better direction, insufficient margin |

A 365-day training window and conservative LightGBM complexity settings were also tested. The best 28-day candidate reached 1,207.9MW MAE, but improved only 3.58% over the v11 contract trained on the same data and had 3.456% WAPE. Neither v13 nor the experimental candidates are force-promoted; v11 remains temporary Champion.

## Initial matched-vintage state

Strict same-run matching recovered 204 legacy captures covering 14 dates and 911 comparison rows. Initial model/TEPCO MAE ratios by lead bucket are approximately 1.84-2.20. The status remains `collecting` until both 28-day and 84-day windows are complete, so these values are not a formal parity result.

## Impact

This change does not alter the served q50 or prediction interval. It prevents invalid timing comparisons and unsafe promotion, and establishes a reproducible path for proving whether a future model reaches TEPCO parity.
