# GitHub Pages Deployment Guide

Languages: [한국어](DEPLOY_ko.md) · [日本語](DEPLOY_ja.md)

## Prerequisites

- GitHub account
- **Public repository** (Private requires GitHub Pro or higher)
- All code verified working locally

---

## Step 1: Create Repository and Push Code

```bash
# After creating a new repository on GitHub
git init
git remote add origin https://github.com/<USERNAME>/<REPO_NAME>.git
git add .
git commit -m "initial commit"
git push -u origin main
```

> Generated data under `web/public/` is not committed to `main`.
> The workflows populate and persist it on the `data` branch before deploying Pages.

---

## Step 2: Enable GitHub Pages

1. Repository → **Settings** → **Pages**
2. **Source**: select `GitHub Actions` and save

---

## Step 3: Configure Actions Permissions

1. Repository → **Settings** → **Actions** → **General**
2. **Workflow permissions**: select `Read and write permissions`
3. Check `Allow GitHub Actions to create and approve pull requests`

> The workflows commit generated JSON/cache outputs to the `data` branch, so write access is required.

---

## Step 4: First Deployment (Manual Run)

1. Repository → **Actions** → **ETL + Deploy**
2. **Run workflow** → `main` branch → **Run workflow**
3. Completes in approximately 2–3 minutes
4. Check your Pages URL: `https://<USERNAME>.github.io/<REPO_NAME>/`

---

## Workflow Overview

| Workflow | Schedule | Role |
|---|---|---|
| `ETL + Deploy` | Daily at 09:20 JST | Download TEPCO monthly ZIP → process confirmed historical data → metrics → deploy |
| `Intraday Update` | 00:10 JST + 01:40–23:40 JST every 2 hours | Refresh same-day TEPCO intraday CSV → forecasts/status → deploy |

---

## Troubleshooting

```
Actions tab → workflow run → check each Step's logs
```

Common issues:

| Error | Cause | Fix |
|---|---|---|
| `Permission denied` on git push | Workflow permissions not configured | Revisit Step 3 |
| 404 after build | Pages Source is not set to `Actions` | Revisit Step 2 |
| `ModuleNotFoundError` | Package missing from requirements.txt | Run `pip install` locally and update requirements.txt |
| Chart shows no data | Data branch has not been populated yet | Run `ETL + Deploy`, then `Intraday Update` if same-day data is needed |

---

## Vite BASE_URL

The workflow automatically sets `VITE_BASE_PATH: /${{ github.event.repository.name }}/`.
If you rename the repository, this value updates automatically — no manual change needed.
