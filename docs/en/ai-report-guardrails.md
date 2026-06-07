# AI Ops Report Guardrails

This document explains how TokyoGridEMS keeps the daily AI Ops Report useful without letting the language model invent unsupported operational conclusions.

The report generator is not designed as a free-form chatbot. It is an operational reporting pipeline where Python computes the facts, OpenAI writes the narrative, and a deterministic merge layer validates the final JSON before the dashboard displays it.

Languages: [한국어](../ko/ai-report-guardrails.md) · [日本語](../ja/ai-report-guardrails.md)

---

## Is This Hardcoding?

No. The implementation does not hardcode a specific date, forecast value, root cause, or recommendation.

It does use deterministic guardrails. That means the report has fixed rules for metric terms, evidence quality, recommendation targets, and summary consistency. The values themselves still come from the generated JSON inputs: daily reports, diagnostics, calibration snapshots, actuals, forecasts, and metrics.

This distinction matters:

| Not acceptable | Current design |
|---|---|
| "Always say the model failed because of warm-day bias." | Only mention a feature or guard when the input evidence supports it. |
| "Always inject a fixed 600 MW freeze explanation." | Mention forecast freeze only when a measured serving-vs-recalculated gap exists. |
| "Always make the model look better." | Summarize model-vs-TEPCO performance from MAE/WAPE/RMSE facts. |
| "Let OpenAI freely decide the metrics." | Python computes metrics; OpenAI only explains them. |

The deterministic parts are output contracts, not forecast or diagnosis hardcoding.

---

## Pipeline

```text
Daily metrics / diagnostics / calibration metadata
  -> compact FactPacket
  -> OpenAI English master analysis
  -> Korean/Japanese localization
  -> deterministic merge and validation
  -> reports/ai/daily/{ko,en,ja}/YYYY-MM-DD.json
  -> Ops Report tab
```

OpenAI creates the narrative layer. It does not own the final facts.

The final report passes through Python validation that can repair or reject wording when it conflicts with computed evidence.

---

## Division of Responsibility

| Layer | Responsibility |
|---|---|
| Python fact builder | Calculates MAE, WAPE, RMSE, top misses, coverage, time-band bias, freeze gaps, and calibration facts. |
| OpenAI master analysis | Converts the fact packet into a readable operational explanation. |
| Localization step | Converts the English master into Korean and Japanese while preserving numbers and structure. |
| Merge/guardrail layer | Removes unsupported claims, repairs terminology, validates recommendations, and enforces output consistency. |
| React UI | Displays the validated JSON without calling OpenAI from the browser. |

---

## Deterministic Guardrails

| Guardrail | Purpose |
|---|---|
| Metric terminology repair | The project uses WAPE as the primary percentage error metric; generated text must not call it MAPE. |
| TEPCO terminology repair | TEPCO values are treated as an external forecast/reference, not as this project's model. |
| Signed-error validation | A positive model error means overprediction; a negative error means underprediction. Contradictory hypotheses are rejected. |
| Evidence filtering | Hypotheses need concrete evidence from misses, diagnostics, calibration, or freeze metadata. |
| Coverage separation | Final actual coverage and intraday calibration snapshot coverage must not be mixed. |
| Freeze-gap validation | Forecast freeze is mentioned only when the input data contains a measurable serving-vs-recalculated gap. |
| Recommendation whitelist | Feature recommendations must target known features or operational guards. |
| Recommendation linking | Recommendations must link back to a valid root-cause hypothesis. |
| `autoApply: false` | AI recommendations are review candidates, never automatic model changes. |

---

## What OpenAI Still Adds

The guardrails do not remove the value of OpenAI. The model still helps with:

- explaining metric and shape-risk patterns in readable language;
- connecting misses to plausible lag, weather, calendar, or calibration mechanisms;
- writing bilingual operational summaries;
- turning numeric diagnostics into review tickets;
- separating "confirmed", "partial", and "not observed" evidence in a human-friendly way.

The goal is not to make the report mechanically bland. The goal is to keep the model inside the evidence boundary.

---

## Quality Criteria

A high-quality Ops Report should satisfy these checks:

- Daily winner/loser judgment matches MAE/WAPE facts.
- WAPE is not mislabeled as MAPE.
- TEPCO is described as an external forecast/reference.
- Coverage notes distinguish finalized actual coverage from calibration snapshot coverage.
- Each root-cause hypothesis has concrete evidence.
- Each root-cause hypothesis names a causal mechanism and a concrete next check.
- Freeze-policy explanations appear only when a freeze gap is present.
- Improvement candidates target real features or post-processing layers.
- Improvement candidates include a validation window, threshold, guard, or replay target rather than generic review wording.
- Recommendations remain review/backtest candidates and never auto-apply.
- Korean and Japanese reports preserve the English master analysis numbers.

---

## Maintenance Checklist

When adding or renaming a model feature, post-processing guard, or report field:

1. Add the feature/guard to the AI report feature catalog.
2. Add aliases if OpenAI may refer to the same concept with another name.
3. Add it to the recommendation whitelist only if it is a valid tuning target.
4. Update tests that validate hypothesis filtering and recommendation linking.
5. Run the AI report unit tests.
6. Generate one latest-day report locally before publishing.

Recommended checks:

```powershell
py -3 -m pytest tests\test_ai_daily_report.py -q
py -3 -m pytest -q
```

Latest-day report smoke test:

```powershell
$env:OPENAI_DAILY_REPORT_MODEL='gpt-4o-mini'
$env:OPENAI_DAILY_REPORT_LOCALIZATION_MODEL='gpt-4o-mini'
py -3 python\eval\ai_daily_report.py --public-dir web\public --out-dir tmp_ai_report_check --max-days 1 --languages ko,en,ja --use-openai --overwrite-existing --openai-max-calls 3
```

Inspect the generated JSON and UI, then delete `tmp_ai_report_check`.

---

## Operational Trade-off

The current design is intentionally conservative. It may make the report less free-form, but it reduces the chance of publishing a polished yet unsupported explanation.

For an operational power-demand dashboard, that trade-off is appropriate: the narrative should be readable, but the numbers and claims must remain auditable.
