# Tokyo Grid EMS

**Power demand forecasting / anomaly detection / monitoring dashboard** built on TEPCO's public electricity data.

> [日本語](README_ja.md) · [한국어](README_ko.md)

- Live Dashboard: [https://wonhongchang.github.io/tokyo-grid-ems/](https://wonhongchang.github.io/tokyo-grid-ems/)

---

## Project Overview

An **automated static EMS (Energy Management System) prototype** built on time-series electricity data published by Tokyo Electric Power Company (TEPCO), providing core features:

- **Demand forecasting** (hourly, with peak time and value)
- **Anomaly detection** against forecasts (spikes/drops, residual drift, supply reserve risk)
- A **static dashboard** deployable to GitHub Pages at zero cost

> Assumption: the dashboard is served from static JSON on GitHub Pages, while same-day data is refreshed from TEPCO's intraday CSV every 2 hours.
> The UI centers on **yesterday's finalized anomaly report** + **today/tomorrow forecasts** + **same-day actual/TEPCO forecast comparison**.

---

## Tech Stack

| Role | Technology |
|------|------|
| ETL / Parsing | Python (pandas) |
| Forecasting / Anomaly Detection | Python (LightGBM + statistical fallback, rule-based anomaly detection) |
| Dashboard | React + Vite |
| Hosting | GitHub Pages (static JSON) |
| Automation | GitHub Actions (daily + every 2 hours) |
| Operations report | Deterministic Python fallback + optional OpenAI narrative/localization |

---

## Architecture

![Tokyo Grid EMS Architecture](docs/assets/tokyo-grid-ems-architecture.png)

- **ETL**: Downloads TEPCO monthly ZIP daily → parses confirmed historical data → generates JSON → deploys to GitHub Pages
- **Intraday**: Fetches and updates today's TEPCO intraday CSV every 2 hours
- **Validation / Ops report**: Generates previous-day operation reports, forecast snapshots, TEPCO-comparison metrics, LightGBM backtests, UI-hidden internal diagnostics JSON, and an optional AI narrative report

---

## Dashboard Layout

**Status bar (always visible)**
- Last updated time / data availability

**5 tabs**

1. **Yesterday** — Previous day's actuals + anomaly events
   - Spike / Drop: forecast interval (95/99%) breach
   - Drift: persistent residual bias (EWMA)
   - Reserve Risk: usage rate / reserve margin threshold breach

2. **Today** — Hourly forecast + forecast bands + peak prediction (time and value)

3. **Tomorrow** — Hourly forecast + forecast bands + peak prediction (time and value)

4. **Validation** — Previous-day operation report + Model-vs-TEPCO comparison + LightGBM backtest

5. **Ops Report** — Daily operational explanation generated from deterministic metrics
   - Uses previous-day metrics, top misses, data quality, and calibration metadata
   - Runs as a rules-based fallback when no OpenAI key is configured
   - When `TOKYO_GRID_EMS_OPENAI_API_KEY` is available, creates an English master analysis and localizes it to Korean/Japanese

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
│   ├── forecast/               # Demand forecasting models
│   └── anomaly/                # Anomaly detection
├── web/                        # React/Vite dashboard
├── docs/
│   ├── en/                     # English documentation
│   ├── ko/                     # Korean documentation
│   ├── ja/                     # Japanese documentation
│   └── assets/                 # README and documentation images
└── data/
    └── raw/                    # Raw CSV data (auto-downloaded by Actions, git-ignored)
        └── YYYY/
            └── YYYYMM_power_usage/
```

---

## Quickstart

### Local setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# Fetch TEPCO data
python python/etl/fetch_tepco.py

# Run ETL → generates JSON under web/public/
python python/etl/run_batch.py --input data/raw --out web/public

# Optional: enable OpenAI-backed daily ops reports
# Windows PowerShell:
# $env:TOKYO_GRID_EMS_OPENAI_API_KEY="..."
# $env:OPENAI_DAILY_REPORT_MODEL="gpt-4o-mini"
# $env:OPENAI_DAILY_REPORT_LOCALIZATION_MODEL="gpt-4o-mini"

# Local dashboard preview
cd web && npm install && npm run dev
```

### Docker local ETL

When GitHub-hosted runners cannot download the TEPCO monthly ZIP, run the ETL locally in Docker and publish the generated static JSON from your machine:

```powershell
# First run: build the image, fetch TEPCO ZIP, run ETL, and publish data
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Build -Publish

# Later runs: reuse the image, rerun ETL, and publish data
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish
```

Docker handles the Python runtime, TEPCO fetch, and OpenAI report generation. The publish and deploy-dispatch steps run on the host so they can reuse your existing Git credentials.

### GitHub Pages deployment

See [DEPLOY.md](DEPLOY.md).

---

## Static JSON Outputs

Files generated by the ETL under `web/public/`:

| File | Contents |
|------|------|
| `status.json` | Overall status (last updated, today/tomorrow forecast summaries) |
| `alerts/YYYY-MM-DD.json` | Anomaly detection event list |
| `forecast/YYYY-MM-DD.json` | Hourly forecast + prediction intervals (95/99%) |
| `actual/YYYY-MM-DD.json` | Hourly actuals (includes intraday real-time data) |
| `forecast_snapshots/YYYY-MM-DD/*.json` | Bounded lead-time forecast snapshots for operational review, not linked directly in the UI |
| `metrics/forecast_accuracy.json` | Operational accuracy against TEPCO forecasts |
| `metrics/model_backtest.json` | LightGBM backtest against the baseline |
| `reports/daily/*.json` | Public previous-day operation summaries for the validation tab |
| `reports/ai/daily/{ko,en,ja}/*.json` | Daily Ops Report narratives; OpenAI when configured, deterministic fallback otherwise |
| `reports/internal/daily-diagnostics/*.json` | Internal lag/weather/shape diagnostics, stored with operational outputs but not linked in the UI |
| `reports/internal/operational-calibration/*.json` | Source confidence and post-processing calibration metadata for operational debugging |

> All timestamps are ISO 8601 in `Asia/Tokyo (+09:00)`.

### AI Ops Report Behavior

- AI reports are generated during ETL only; intraday/status-only runs do not rewrite report bodies.
- Existing report JSON for the same date/language is preserved on later ETL retries to avoid repeated API cost.
- OpenAI usage is capped by default to 3 calls: low-cost English master analysis (`OPENAI_DAILY_REPORT_MODEL`, default `gpt-4o-mini`), Korean/Japanese localization (`OPENAI_DAILY_REPORT_LOCALIZATION_MODEL`, default `gpt-4o-mini`), and one low-cost localization retry when the first localized output fails validation. Set `OPENAI_DAILY_REPORT_MODEL` explicitly if a stronger analysis model is needed.
- Timeout defaults are conservative for GitHub Actions: `OPENAI_DAILY_REPORT_TIMEOUT_SECONDS=90` and `OPENAI_DAILY_REPORT_LOCALIZATION_TIMEOUT_SECONDS=180`. If GitHub repository variables are not set, the Python defaults are used.
- If localization fails or times out, the localized path falls back to the English master text and records `localizationStatus: "fallback_en"`.

---

## Documentation

- [Project walkthrough for students](docs/en/project-walkthrough.md)
- [LightGBM model design](docs/en/lgbm-design.md)
- [Model operations specification](docs/en/model-operations-spec.md)
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

- [2026-06-04 morning warm-lag overreaction guard](docs/en/model-improvements/model-improvement-2026-06-04-morning-warm-lag-overreaction-guard.md)
- [2026-06-03 forecast interval tail sanity guard](docs/en/model-improvements/model-improvement-2026-06-03-forecast-interval-tail-sanity-guard.md)
- [2026-05-30 negative residual continuity floor](docs/en/model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md)
- [2026-05-29 evening level-overhang guard](docs/en/model-improvements/model-improvement-2026-05-29-evening-level-overhang-guard.md)
- [2026-05-27 evening decline continuity guard](docs/en/model-improvements/model-improvement-2026-05-27-evening-decline-continuity-guard.md)
- [2026-05-27 morning ramp continuity guard](docs/en/model-improvements/model-improvement-2026-05-27-morning-ramp-continuity-guard.md)

Full chronological log: [docs/en/model-improvements/README.md](docs/en/model-improvements/README.md)

---

## Roadmap

| Phase | Description | Status |
|---------|------|------|
| Phase 1–3 | ETL / Forecasting / Anomaly Detection / Dashboard | ✅ Done |
| Phase 4 | GitHub Pages auto-deploy | ✅ Done |
| Phase 5-A | LightGBM forecast model | ✅ In production |
| Phase 5-B | Weather data integration (Open-Meteo) | ✅ In production |
| Phase 6 | Validation tab / backtest / TEPCO comparison | ✅ Done |

---

## Author

- Chang Wonhong
- LinkedIn: https://www.linkedin.com/in/wonhong-chang-6660a0177/
