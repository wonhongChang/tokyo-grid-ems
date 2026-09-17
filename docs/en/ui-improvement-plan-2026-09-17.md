# 2026-09-17 UI Review and Improvement Plan

Status (2026-09-18): **Phase 1 implemented and locally verified; Phase 2 not started**. Not committed or pushed. No forecast model, calibration, interval or data-generation policy changes.

Languages: [한국어](../ko/ui-improvement-plan-2026-09-17.md) / [日本語](../ja/ui-improvement-plan-2026-09-17.md)

## Scope and Priorities

Reviewed Today, Validation and Ops Report on the [deployed dashboard](https://wonhongchang.github.io/tokyo-grid-ems/). Data timestamp: 2026-09-17 17:38:08 JST; today's actuals cover 00:00-16:00, 17 hours. Mobile viewport: 390px.

| Order | Finding | Proposed change |
|---|---|---|
| 1 | Long internal feature names overflow the mobile page | Wrap strings; collapse technical catalogs separately from ordinary notes |
| 2 | Estimated utilization does not clearly identify the demand source | Separate observed, TEPCO-estimated and model-estimated utilization |
| 3 | Latest-published comparison can look like a formal forecast comparison | Separate advance, matched-capture/lead evaluation from latest-value reference |
| 4 | MAE alone hides demand-scale context | Add WAPE, absolute gap, sample count and provisional status in context |

Implement 1-2 first; group 3-4 into a separate Validation change. The comprehensive model review remains planned for September 20 after ETL.

## Mobile Overflow

At a 390px viewport, document `scrollWidth` reached 467px because the operator-note `intraday_correction.*` catalog exceeded its container. This is distinct from intentional horizontal tab scrolling.

Targets: `.ops-bullet-list` in `web/src/index.css` and operator notes in `web/src/components/OpsReportPanel.tsx`. Use wrapping and shrinkable layout, not page-level `overflow-x: hidden` that clips content. Put the technical catalog in a keyboard-accessible, initially collapsed section; retain the underlying data. Prefer structured fields and test multilingual compatibility when classifying legacy text.

Acceptance: no document-wide overflow at 360/390/430px in ko/en/ja; long identifiers, evidence and tables remain readable.

## Utilization Provenance

Before this change, `peakUsageMetric()` in `web/src/App.tsx` used observed utilization when present, otherwise model demand / TEPCO supply. The maximum could switch between sources, while the neighboring demand card showed TEPCO's peak forecast.

At the September 17 deployed-page review, the displayed 17:00 value 89.7% was model 34738.8MW / supply 38710MW. TEPCO's 33820MW at the same hour gives about 87.4%. This is a source difference, not arithmetic error.

Recommended contract:

- **Peak observed utilization:** valid observations only; never classify substitute forecasts as observed.
- **TEPCO estimated peak utilization:** TEPCO demand / same-hour supply, as the primary estimated metric.
- **Model estimated peak utilization:** model demand / same-hour supply, separately labeled as a secondary metric.
- Identify which utilization peak hour the displayed supply belongs to. Never mix demand and supply peaks from different hours.
- Show missing state for absent/zero supply or missing TEPCO forecasts; do not silently switch sources.

Translate provenance in all three languages. Do not change 92%/97% alerts or model calibration. Test source selection, missing values, ties, timestamp matching and rounding boundaries.

## Validation Contract

`metrics/forecast_accuracy.json` declares `latest_published_value_reference`, `tepcoSourceMayRevisePastValues: true`, and `formalParityEligible: false`. Label this as a **published-value error reference**, not an unqualified operational superiority judgment.

Expose the existing `metrics/forecast_vintage_accuracy.json` separately. It compares future targets using forecasts collected at the same `capturedAt`; source `issuedAt` is unavailable, so do not call it identical publication time.

Proposed views: **Advance forecast comparison** / **Latest-published reference**. Show 0-2 / 2-4 / 4-8 / 8-24 h lead buckets, sample counts, period, model/policy scope and insufficient-coverage state. Do not silently combine lead buckets or substitute the reference view as formal evaluation when samples are insufficient.

## What the MAE Gap Means

From the [published-value report](https://wonhongchang.github.io/tokyo-grid-ems/metrics/forecast_accuracy.json); live rows can change later.

| Scope | Model MAE | TEPCO MAE | Absolute gap | Ratio | Model / TEPCO WAPE |
|---|---:|---:|---:|---:|---:|
| Aug 19-Sep 17, 713 h | 605.9MW | 342.2MW | +263.7MW | 1.77x | 1.86% / 1.05% |
| Latest complete 7 days, Sep 10-16, 168 h | ~502.0MW | ~232.7MW | ~+269.3MW | 2.16x | Not recomputed |
| Sep 15 finalized | 673.2MW | 179.6MW | +493.6MW | 3.75x | 2.06% / 0.55% |
| Sep 16 finalized | 498.1MW | 153.8MW | +344.3MW | 3.24x | 1.65% / 0.51% |
| Sep 17 provisional, 00:00-16:00 | 346.5MW | 237.6MW | +108.9MW | 1.46x | 1.19% / 0.81% |

The seven-day MAE is approximated by weighting published daily MAEs by hours. The 30-day summary, 14-day chart and 10-day table have different scopes; label those explicitly.

A 1-2% demand-scale average absolute error does not establish TEPCO parity. Recent relative gaps are substantial, not merely a visual illusion. However, possible TEPCO past-value revisions prevent these numbers from establishing the exact advance-forecast gap. Earlier matched snapshots also showed a deficit, so it cannot all be dismissed as presentation bias.

Chart changes:

1. Keep a shared zero-based axis and stable colors. Do not expand the axis artificially or use dual axes to disguise differences.
2. Offer MAE/WAPE modes. WAPE is total absolute error / total actual over identical samples, not a simple mean of daily percentages.
3. Tooltips should include both MAEs, absolute gap, both WAPEs, sample count and provisional status. Ratios are secondary; handle zero denominators explicitly.
4. Units are correct: **1万kW = 10MW**, so 50万kW is about 500MW. Current formatting rounds ko/ja to integers and en GW to one decimal; provide precise MW in detailed tooltips.
5. Do not rename WAPE 1.86% as accuracy 98.14%. Separate average error, tails, bias and curve-shape errors.

## Delivery Checks

UI-only commits; no retraining, paid AI regeneration or ETL rerun required. Test utilization provenance/missing denominators, unit conversion, metric sample consistency and incomplete days. Verify three languages on mobile and desktop, including loading/error/empty states. Preserve JSON values and evaluation boundaries. [Ops Report Tab](ops-report-tab.md) reflects Phase 1; update [Model Evaluation](model-evaluation.md) during Phase 2.

## Progress and Handoff

### Completed: Phase 1

- [x] Wrap long notes and collapse technical catalogs, with keyboard expansion. Recognize the actual Japanese translation `運用調整信号カタログ` as well as generator labels. Keep ordinary and unknown notes visible.
- [x] Separate Today/Tomorrow utilization by observed, TEPCO and model source. Model metrics are secondary details; supply belongs to the corresponding utilization peak timestamp. Yesterday's finalized summary is unchanged.
- [x] Exclude `tepco_forecast_fallback` from observations; retain compatibility with finalized CSV rows without source fields. Match model forecasts by date/full timestamp. Missing supply or forecasts never silently switch sources.
- [x] Keep mobile language buttons on one line; use three desktop/two mobile columns for today's summary.

Files: `web/src/usageMetrics.ts`, `web/src/reportNotes.ts`, `web/src/App.tsx`, `web/src/components/OpsReportPanel.tsx`, `web/src/index.css`, `web/tests/*.test.mjs`, `web/package.json`.

### Verification

- `npm test` in `web`: **25/25 passed**, covering provenance, missing/invalid denominators, timestamps, ties, rounding and multilingual catalog detection.
- `npm run build`: TypeScript/Vite passed on Node 22.17.1. Tests use `--experimental-strip-types`; Node type-stripping warnings and existing Vite CJS/bundle-size warnings remain.
- Browser: Today across ko/en/ja at 360/390/430px (9 combinations); Ops Report collapsed/expanded at the same sizes (18 states). No document-wide horizontal overflow. Intentional tab scrolling remains.
- Checked 1440px desktop layout, keyboard disclosure, peak/supply timestamp alignment and Tomorrow's missing-supply `-` state.
- Local UI data is **September 17 08:32 JST**, older than the deployed-data review above. No `web/public` refresh, ETL, AI call or model evaluation was performed.
- Full browser loading/network-error regression remains pending. Existing `<html lang>` does not track the language selector; record this as follow-up accessibility work.

### Resume Here

1. Stop after Phase 1. Changes remain uncommitted; do not include the existing untracked `web/public/` in the UI commit.
2. Next session: read this handoff and `git status --short`; do not repeat completed model analysis or ETL.
3. Start **Phase 2: Validation comparison contract and MAE/WAPE presentation**. Inspect actual vintage JSON fields, lead boundaries, coverage and period before implementing types/tests/UI. Matched capture does not mean identical publication time.
4. Verify 30/14/10-day scope labels, provisional/insufficient samples, precise MW and same-sample WAPE. Then check all languages, accessibility and loading/error states.
5. The September 20 post-ETL model review is separate. Do not initiate promotion, retraining or paid report generation for this UI task. Commit/push only when requested.

Preview: `http://127.0.0.1:5173/`. If stopped, run `npm run dev -- --host 127.0.0.1 --port 5173 --strictPort` in `web`. Check an occupied port before starting on another port.
