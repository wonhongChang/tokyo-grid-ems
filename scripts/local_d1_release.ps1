param([Parameter(Mandatory=$true)][string]$OperationsRoot, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$release = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$operations = (Resolve-Path $OperationsRoot).Path
Push-Location $operations
try {
    try {
        # Never overlay an independently changed forecasting implementation.
        & git diff --quiet '4739dcd50c88234eeea18fdba0636e01bd38804d' -- python/etl/run_batch.py python/forecast
        if ($LASTEXITCODE -ne 0) { throw 'Operational base changed; inspect release compatibility.' }
        $extras = & git ls-files --others --exclude-standard -- python/forecast
        if ($LASTEXITCODE -ne 0 -or $extras) { throw 'Unverified local forecast modules.' }
        if ($env:COMPOSE_FILE) { throw 'Existing Compose override; refusing to replace it.' }
        $env:D1_RELEASE_ROOT = $release.Replace('\','/')
        $files = (Join-Path $operations 'docker-compose.yml'),(Join-Path $release 'scripts/d1-local.compose.yml')
        if ($files | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }) { throw 'Missing Compose file.' }
        $env:COMPOSE_FILE = $files -join [IO.Path]::PathSeparator
    } catch {
        if ($CheckOnly) { throw }
        Write-Warning "D-1 overlay not selected: $_. Running the unmodified ETL."
    }
    if ($CheckOnly) {
        if (-not $env:D1_RELEASE_ROOT) { throw 'Release unavailable.' }
        & docker compose run --rm --no-deps --no-TTY --entrypoint python etl -B -c "from datetime import date; import yaml; from python.forecast import d1_component as d; from python.etl import run_batch as b; c=d.with_trial(yaml.safe_load(open('config.yaml'))); print('ETL selector:',hasattr(b,'_select_tomorrow_point'),'Enabled targets:',[t for t in d.APPROVED_TARGETS if d.requested(c,date.fromisoformat(t))]); assert hasattr(b,'_select_tomorrow_point')"
        exit $LASTEXITCODE
    }
    if ($env:D1_RELEASE_ROOT -and $env:COMPOSE_FILE -and (Test-Path 'data/raw/.d1-point/trial.json')) {
        $tomorrow=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow,'Tokyo Standard Time').Date.AddDays(1).ToString('yyyy-MM-dd')
        if ($tomorrow -in @('2026-11-30','2026-12-03','2026-12-05')) {
            try {
                $branch = & git ls-remote --exit-code --heads origin refs/heads/data
                if ($LASTEXITCODE -ne 0 -or $branch -notmatch '^([0-9a-f]{40})\s+refs/heads/data$') { throw 'Could not attest remote head.' }
                $headSha = $Matches[1]
                $kind = $headSha | git cat-file '--batch-check=%(objecttype)'
                if ($LASTEXITCODE -ne 0 -or $kind -ne 'commit') {
                    & git fetch --quiet --no-tags --no-write-fetch-head '--refmap=' origin $headSha
                    if ($LASTEXITCODE -ne 0) { throw 'Public data not fetched.' }
                }
                & py -3.14 -B (Join-Path $release 'scripts/prepare_d1_receipt.py') --repository $operations --ref $headSha --target $tomorrow
                if ($LASTEXITCODE -ne 0) { throw 'No new receipt.' }
            } catch { Write-Warning "D-1 proof unavailable: $_; no update without a verified prior origin." }
        }
    }
    & (Join-Path $operations 'scripts/local_etl.ps1') -Publish
    exit $LASTEXITCODE
} finally { Pop-Location }
