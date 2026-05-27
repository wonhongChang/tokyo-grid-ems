# GitHub Pages Deployment Guide

Languages: [Korean](DEPLOY_ko.md) / [Japanese](DEPLOY_ja.md)

## Prerequisites

- GitHub account
- Public repository, or a GitHub plan that supports private Pages
- GitHub Pages source set to **GitHub Actions**
- Actions workflow permissions set to **Read and write permissions**
- Docker Desktop installed for local historical ETL

Generated data under `web/public/` is not committed to `main`. It is published to the `data` branch, then the Pages workflow restores that branch before building the Vite app.

## Operating Model

Historical TEPCO monthly ZIP downloads are run locally because GitHub-hosted runners can receive HTTP 403 from TEPCO. Intraday updates still run in GitHub Actions.

```text
Local Windows Task Scheduler
  -> scripts/local_etl.ps1 -Publish
    -> restore origin/data into web/public
    -> run Docker ETL and OpenAI daily report generation
    -> push web/public to origin/data
    -> dispatch Deploy Only
    -> dispatch Intraday Update
```

## Workflows

| Workflow | Trigger | Role |
|---|---|---|
| `Manual ETL + Deploy` | Manual only | Emergency historical ETL from GitHub Actions. Scheduled runs are disabled because TEPCO ZIP fetch can be blocked from GitHub-hosted runners. |
| `Intraday Update` | Scheduled + manual | Refresh same-day actuals, forecasts, status, and deploy. The local ETL script dispatches this after its own publish/deploy so the morning chart is refreshed with the latest same-day CSV. |
| `Deploy Only` | Manual dispatch | Restore `origin/data`, build the Vite app, and deploy Pages without running ETL. The local ETL script dispatches this after publishing `data`. |

## Local Docker ETL

First run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish -Build
```

Normal run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_etl.ps1 -Publish
```

Before publish, the local script validates `web/public`:

- `status.json` must be `availability: ok`.
- `coverageTo` must include yesterday.
- Yesterday's `actual/YYYY-MM-DD.json` must have 24 observed hours.
- Today and tomorrow forecast JSONs must contain 24 forecast rows.

The Docker fetch step overwrites the most recent 3 JST dates in `data/raw` so delayed TEPCO CSV corrections can be absorbed before ETL.

Register the recommended local schedule, 07:30 / 08:30 / 09:30 JST:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_local_etl_task.ps1
```

Remove the local schedule:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\unregister_local_etl_task.ps1
```

## Monitoring

- Windows Task Scheduler: check `LastRunTime`, `LastTaskResult`, and `NextRunTime`.
- Local logs: `logs/local_etl/*.log`.
- Local status JSON: `web/public/ops/local_etl_status.json`.
- GitHub: check the latest `data` branch commit and the `Deploy Only` workflow result.
- Docker Desktop: the ETL container normally ends in `Exited` state because it is a batch job.

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| TEPCO monthly ZIP returns `403` in Actions | GitHub-hosted runner IP is blocked by TEPCO | Use local Docker ETL: `scripts\local_etl.ps1 -Publish` |
| Deploy Only dispatch fails | No GitHub token available locally | Set `GH_TOKEN` or `GITHUB_TOKEN`, sign in with GitHub CLI, or trigger `Deploy Only` manually in Actions |
| Intraday dispatch fails after local ETL | No GitHub token available locally, or GitHub Actions dispatch failed | Run `Intraday Update` manually in Actions, then check `logs/local_etl/*.log` |
| OpenAI report falls back | API key missing, invalid, or timed out | Check `.env` and `logs/local_etl/*.log`, then rerun local ETL |
| Chart shows stale data | `data` branch was pushed but Pages was not deployed | Run `Deploy Only` manually |
| `Permission denied` on data push | Git credentials are not available on the host | Re-authenticate Git for GitHub on Windows |

## Vite Base Path

The workflow sets `VITE_BASE_PATH: /${{ github.event.repository.name }}/`. If the repository is renamed, the base path follows the repository name automatically.
