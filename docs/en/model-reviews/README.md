# Model Review Archive

This directory records scheduled model reviews, including the evidence examined, fixed acceptance gates, promotion decisions, and residual risks.

These documents are distinct from the [Model Improvement Log](../model-improvements/README.md). A review may correctly end with no code change or promotion; an improvement document is added only after an actual implementation change is accepted.

Languages: [한국어](../../ko/model-reviews/README.md) / [日本語](../../ja/model-reviews/README.md)

## Reviews

- [2026-09-04 v15 candidate screening review](model-review-2026-09-04-v15-candidate-screening.md) - completed; retraining, configuration ablations, rolling windows, and origin-specific models produced no candidate that passed both development and holdout evidence, so v14-r2 remains deployed.
- [2026-09-03 v14-r2 operational model review](model-review-2026-09-03.md) - completed; v14-r2 remains temporary under `review_required`, with calibration correctness, contract-scoped health, and v15 challenger work prioritized.
- [2026-08-18 operational model review](model-review-2026-08-18.md) - completed; the August 14-18 stage reconstruction retains v11 only temporarily and starts immediate replay work on raw q50, the morning guard, and residual sign reversal.
- [2026-08-11 operational model review](model-review-2026-08-11.md) - completed; v11 retained, v13 rejected, and a replay-qualified non-business morning guard accepted.
