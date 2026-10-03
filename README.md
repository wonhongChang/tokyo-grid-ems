# Tokyo Grid EMS

**Power demand forecasting / anomaly detection / monitoring dashboard** built on TEPCO's public electricity data.

> [日本語](README_ja.md) · [한국어](README_ko.md)

- Live Dashboard: [https://wonhongchang.github.io/tokyo-grid-ems/](https://wonhongchang.github.io/tokyo-grid-ems/)

---

## Project Overview

An **automated static EMS (Energy Management System) prototype** built on time-series electricity data published by Tokyo Electric Power Company (TEPCO), providing core features:

- **Demand forecasting** (hourly, with peak time and value)
- **Anomaly detection** against forecasts (spikes/drops, residual drift, supply reserve risk)
- A **static dashboard** delivered through GitHub Pages without a backend inference server

> Historical data is refreshed by local Windows/Docker ETL. GitHub Actions refresh same-day data on a schedule with additional morning and catch-up runs, then build and deploy the static dashboard.
> The UI centers on **yesterday's finalized anomaly report** + **today/tomorrow forecasts** + **same-day actual/TEPCO forecast comparison**.

---

## Tech Stack

| Role | Technology |
|------|------|
| ETL / Parsing | Python (pandas) |
| Forecasting / Anomaly Detection | Python (LightGBM + statistical fallback, rule-based anomaly detection) |
| Dashboard | React + Vite |
| Hosting | GitHub Pages (static JSON) |
| Automation | Local Windows/Docker ETL + scheduled GitHub Actions intraday updates and deployment |
| Operations report | Deterministic Python fallback + optional OpenAI narrative/localization |

---

## Architecture

![Tokyo Grid EMS Architecture](docs/assets/tokyo-grid-ems-architecture.png)

- **ETL**: Local Windows orchestration runs Docker ETL to refresh confirmed TEPCO history, prepare features, and publish static artifacts to the data branch.
- **Intraday / delivery**: Scheduled GitHub Actions update same-day observations and calibrated forecasts; the static build delivers JSON and the React/Vite dashboard through GitHub Pages.
- **Reports / validation**: Daily metrics and optional AI narratives support operations. Review Evidence Bundle, replay, and isolated shadow evaluation analyze evidence separately from production serving.

[Architecture notes and editable source](docs/architecture/tokyo-grid-ems-architecture.md)

---

## Dashboard Layout

The status bar shows update time and data availability.

| Tab | Contents |
|---|---|
| Yesterday | Previous-day actuals and spike/drop, residual-drift, and reserve-risk events |
| Today | Hourly forecast, prediction intervals, actuals, and peak forecast |
| Tomorrow | Next-day hourly forecast, prediction intervals, and peak forecast |
| Validation | Daily metrics, model/TEPCO comparison, and LightGBM backtest |
| Ops Report | Evidence-based daily explanation; optional OpenAI English analysis with Korean/Japanese localization, or rules-based fallback |

---

## TEPCO Data Format

| Item | Details |
|------|------|
| Source | TEPCO public electricity supply/demand data |
| Encoding | **cp932 (Shift-JIS)** |
| Unit | **万kW (= 10 MW)** |
| Format | **Multi-section CSV** with multiple tables separated by blank lines |

---

## Repository Structure

```
.
├── python/
│   ├── tepc_parser.py          # TEPCO multi-section CSV parser
│   ├── etl/
│   │   ├── run_batch.py        # Batch runner (CSV → JSON)
│   │   ├── fetch_tepco.py      # TEPCO monthly ZIP downloader
│   │   ├── fetch_today.py      # Intraday real-time data fetcher
│   │   └── quality_gate.py     # Data quality checks
│   ├── forecast/              # Demand models, calibration, and intervals
│   ├── anomaly/               # Anomaly detection
│   └── eval/                  # Metrics, reports, replay, Review Bundle, and challenger tooling
├── scripts/                   # Local orchestration, data restore, and publication
├── docker/                    # Isolated shadow runtime image
├── docker-compose.yml         # Local ETL and independent shadow services
├── web/                        # React/Vite dashboard
├── docs/
│   ├── en/                     # English documentation
│   ├── ko/                     # Korean documentation
│   ├── ja/                     # Japanese documentation
│   └── assets/                 # README and documentation images
└── data/
    └── raw/                    # Raw CSV data (normally fetched locally, git-ignored)
        └── YYYY/
            └── YYYYMM_power_usage/
```

---

## Quickstart

### Preview the dashboard

With Git, Python 3, and Node.js installed, run from the repository root:

```bash
python scripts/restore_public_from_data_branch.py
cd web
npm ci
npm run dev
```

The restore command replaces `web/public/` with the published `origin/data` contents. Preserve any unpublished local artifacts first. This preview does not run ETL or call OpenAI.

### Run and publish operational ETL

The Windows host script requires Docker Desktop, Python 3.14 via the `py` launcher, Git credentials, and workflow-dispatch authentication. Run from the repository root:

```powershell
# First manual run: build the image if historical ETL is needed
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Build -Publish -AllowOffSchedule

# Later manual runs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish -AllowOffSchedule
```

The host restores published data/model state, runs Docker ETL when yesterday is not finalized, validates and publishes outputs, and dispatches deployment/intraday workflows. If yesterday is already finalized, it skips historical ETL; a missing/fallback AI report can be recovered separately. `-AllowOffSchedule` allows manual runs outside the morning schedule. Publication uses host Git credentials, not container credentials.

For a Python-only local rebuild, install `requirements.txt`, then run `python python/etl/fetch_tepco.py` and `python python/etl/run_batch.py --input data/raw --out web/public`. Without restored model/state artifacts, a fresh rebuild is not guaranteed to reproduce the deployed Champion.

### GitHub Pages deployment

See [DEPLOY.md](DEPLOY.md).

---

## Static JSON Outputs

Common artifacts under `web/public/`, restored from `data` or generated by the relevant pipeline/tool:

| File | Contents |
|------|------|
| `status.json` | Overall status (last updated, today/tomorrow forecast summaries) |
| `alerts/YYYY-MM-DD.json` | Anomaly detection event list |
| `forecast/YYYY-MM-DD.json` | Hourly forecast + prediction intervals (95/99%) |
| `actual/YYYY-MM-DD.json` | Hourly actuals (includes intraday real-time data) |
| `metrics/forecast_accuracy.json` | Latest-published-value operational reference against TEPCO; not a formal same-vintage benchmark |
| `metrics/forecast_vintage_accuracy.json` | Same-capture, lead-time-matched model/TEPCO evaluation |
| `reports/daily/*.json` | Public previous-day operation summaries for the validation tab |
| `reports/ai/daily/{ko,en,ja}/*.json` | Daily Ops Report narratives; OpenAI when configured, deterministic fallback otherwise |
| `forecast_snapshots/`, `reports/internal/` | Retained forecast vintages, calibration stages, and diagnostics for review; not directly linked in the UI |

Backtest, replay, and promotion artifacts are documented in the [model operations specification](docs/en/model-operations-spec.md). In particular, `model_contract_comparison.json` is written by explicit promotion tools, not regenerated by every ETL. Files named `internal` are not an access-control boundary and may be included in static deployment.

> All timestamps are ISO 8601 in `Asia/Tokyo (+09:00)`.

### AI Ops Report Behavior

- Intraday/status-only runs do not generate AI narratives. Normal generation targets the latest finalized daily report; successful existing OpenAI reports are preserved, while missing/fallback reports can be recovered separately.
- Both analysis and localization default to `gpt-4o-mini`. The default per-run budget is **2 logical calls**, not a hard cap on HTTP attempts or spending; transport retries are separate.
- To opt in during ETL, configure `TOKYO_GRID_EMS_OPENAI_API_KEY` and `OPENAI_DAILY_REPORT_AUTO_ENABLE=true` before launching it. The dedicated report CLI instead accepts `--use-openai`. Do not commit `.env` or keys, and do not use the generic `OPENAI_API_KEY` runtime variable for project reports.
- If analysis is unavailable, rules-based fallback is used; failed localization retains the English master with `localizationStatus: "fallback_en"`. AI recommendations never auto-apply to forecasting.

See [Ops Report configuration and cost controls](docs/en/ops-report-tab.md) for activation examples, retry budgets, timeouts, and report-only recovery.

---

## Documentation

- [Project walkthrough for first-time readers](docs/en/project-walkthrough.md)
- [LightGBM model design](docs/en/lgbm-design.md)
- [Model operations specification](docs/en/model-operations-spec.md)
- [Model promotion and degraded Champion policy](docs/en/model-promotion-policy.md)
- [Operations runbook](docs/en/operations-runbook.md)
- [Model review archive](docs/en/model-reviews/README.md)
- Model review tooling: [evidence bundle and read-only CLI](docs/en/review-bundle-cli.md), [validation summary](docs/en/review-bundle-validation.md)
- Experimental [learned intraday challenger and isolated shadow evaluation](docs/en/learned-intraday-challenger.md)
- Independent [Docker multi-challenger shadow service](docs/en/docker-intraday-shadow.md)
- [Weather integration design](docs/en/weather-integration.md)
- [Data retention and archive strategy](docs/en/data-retention-strategy.md)
- [Model evaluation report](docs/en/model-evaluation.md)
- [Anomaly detection criteria](docs/en/anomaly-criteria.md)
- [Ops Report tab](docs/en/ops-report-tab.md)
- [AI Ops Report guardrails](docs/en/ai-report-guardrails.md)
- [JSON schema contract](docs/en/json_schema.md)

---

## Model Improvement Log

Selected recent operational changes:

- [2026-09-21 observed recovery before weekend residual damping](docs/en/model-improvements/model-improvement-2026-09-21-observed-evening-recovery.md)
- [2026-09-13 observed weekend morning shape support and AI evidence repair](docs/en/model-improvements/model-improvement-2026-09-13-observed-weekend-shape-support.md)
- [2026-09-11 model review, sustained-decline restoration and replay-origin repair](docs/en/model-improvements/model-improvement-2026-09-11-review-and-sustained-decline.md)

Full chronological log: [docs/en/model-improvements/README.md](docs/en/model-improvements/README.md)

---

## Roadmap

| Phase | Description | Status |
|---------|------|------|
| Phase 1–3 | ETL / Forecasting / Anomaly Detection / Dashboard | ✅ Done |
| Phase 4 | GitHub Pages auto-deploy | ✅ Done |
| Phase 5-A | LightGBM forecast model | ✅ In production |
| Phase 5-B | JMA observations/forecast + guarded Open-Meteo humidity/history support | ✅ In production |
| Phase 6 | Validation tab / backtest / TEPCO comparison | ✅ Done |

---

## Author

- Chang Wonhong
- LinkedIn: https://www.linkedin.com/in/wonhong-chang-6660a0177/

---

## License

This project is licensed under the [MIT License](LICENSE).
