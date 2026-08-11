# Non-Business Morning Observed Anchor Extension

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-08-11-non-business-morning-anchor-extension.md) / [日本語](../../ja/model-improvements/model-improvement-2026-08-11-non-business-morning-anchor-extension.md)

## Incident

On the 2026-08-11 Mountain Day holiday, calendar routing correctly selected the non-business path, but morning raw q50 remained too high. At 09:00, pre-calibration demand was about 33.0 GW while observed demand was 28.56 GW. Intraday residual correction reached its -1.2 GW global cap and still left a material near-term overhang.

The existing `morning_observed_anchor_cap` was business-day-only. Weekend and holiday forecasts therefore had no equivalent final near-term cap after same-day actuals had already confirmed overprediction.

## Change

The existing anchor-cap controller now has an independent `non_business_extension` configuration. It does not create a fixed weekend shape and does not modify raw LightGBM output. It limits only the remaining near-term operational adjustment when all of the following are true:

- the target date is a weekend or Japanese holiday;
- the latest usable actual is hour 08 or 09;
- the latest model residual confirms at least 400 MW of overprediction;
- the target is within four lead hours;
- lag-24 or recent same-business deltas provide a finite shape path;
- the forecast remains above the observed level plus cumulative shape support.

The excess is reduced with 0.75 shrinkage and a 1,000 MW hard cap. The extension turns off after hour 09 so later same-day controllers can take over.

## Strong-Ramp Veto

A weekend or holiday may have a real late-start demand surge. The cap is bypassed when all three observations hold:

- latest actual slope is at least 4,000 MW;
- mean of the last two actual slopes is at least 2,500 MW;
- cumulative lag/recent shape support is at least 2,500 MW.

This veto protected the confirmed 2026-08-08 morning ramp in replay.

## Replay

Historical calibration snapshots supplied 68 comparable forecast-hour records across nine non-business mornings from 2026-07-18 through 2026-08-09.

| Metric | Existing | Candidate |
|---|---:|---:|
| Morning snapshot MAE | 1,456.2 MW | 1,282.9 MW |
| MAE change | - | -173.3 MW (-11.9%) |
| Records changed | 0 | 13 |
| Maximum reduction | 0 MW | 1,000 MW |

One affected July 18 record worsened slightly. The change was accepted because aggregate error improved, intervention remained sparse, the reduction was capped, explosive ramps were vetoed, and the layer handed off early. It is not claimed to improve every non-business hour.

## Rejected Alternatives

- The v13 Challenger was not promoted: its recent 28-day MAE was 1,208.1 MW and WAPE was 3.256%, both above fixed limits.
- Shorter 730-, 548-, and 365-day training windows worsened the recent replay.
- q50 blend changes and business residual-weight changes did not provide a stable gain.
- Increasing the global intraday residual cap caused large regressions after raw forecasts recovered.
- No date-specific condition, fixed holiday offset, or TEPCO forecast calibration was introduced.

## Verification And Scope

- `155` focused intraday/batch/interval tests passed after the separate interval change.
- Full suite in the primary workspace: `500 passed`.
- Public artifact validation and production-equivalent status generation passed.
- The v11 Champion, raw quantile models, business-day lunch logic, and promotion thresholds remain unchanged. The separate interval-floor change is documented in the same-date band report.
- The next scheduled review is 2026-08-17 after the following weekend is finalized.
