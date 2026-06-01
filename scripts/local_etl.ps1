param(
    [switch]$Publish,
    [switch]$Build,
    [switch]$SkipRestore,
    [switch]$SkipDeploy,
    [switch]$SkipIntradayDispatch,
    [switch]$SkipValidation,
    [switch]$ForceHistoricalEtl,
    [switch]$AllowOffSchedule,
    [string]$LogDir = "logs/local_etl"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$StartedAt = Get-Date
$LogRoot = Join-Path $RepoRoot $LogDir
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$LogPath = Join-Path $LogRoot ($StartedAt.ToString("yyyy-MM-dd_HH-mm-ss") + ".log")

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Write-LocalEtlStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Stage,
        [string]$Message = "",
        [bool]$Published = $false,
        [bool]$DeployTriggered = $false,
        [bool]$IntradayTriggered = $false,
        [bool]$HistoricalEtlSkipped = $false,
        [string]$HistoricalEtlDate = "",
        [string]$HistoricalEtlReason = ""
    )

    $opsDir = Join-Path $RepoRoot "web/public/ops"
    New-Item -ItemType Directory -Force -Path $opsDir | Out-Null
    $payload = [ordered]@{
        lastRunAt = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        startedAt = $StartedAt.ToString("yyyy-MM-ddTHH:mm:sszzz")
        status = $Status
        stage = $Stage
        message = $Message
        logPath = $LogPath
        dataBranchPublished = $Published
        deployTriggered = $DeployTriggered
        intradayTriggered = $IntradayTriggered
        historicalEtlSkipped = $HistoricalEtlSkipped
        historicalEtlDate = $HistoricalEtlDate
        historicalEtlReason = $HistoricalEtlReason
    }
    $payload | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $opsDir "local_etl_status.json") -Encoding UTF8
}

function Get-JstToday {
    try {
        $timezone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Tokyo Standard Time")
        return ([System.TimeZoneInfo]::ConvertTime((Get-Date), $timezone)).Date
    }
    catch {
        return (Get-Date).Date
    }
}

function Get-JstNow {
    try {
        $timezone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Tokyo Standard Time")
        return [System.TimeZoneInfo]::ConvertTime((Get-Date), $timezone)
    }
    catch {
        return Get-Date
    }
}

function Test-LocalEtlScheduleWindow {
    $now = Get-JstNow
    $start = $now.Date.AddHours(7)
    $end = $now.Date.AddHours(10).AddMinutes(30)
    return ($now -ge $start -and $now -le $end)
}

function Get-ProjectOpenAiKeySource {
    $projectKeyName = "TOKYO_GRID_EMS_OPENAI_API_KEY"
    $standardKeyName = "OPENAI_API_KEY"
    $projectKey = [Environment]::GetEnvironmentVariable($projectKeyName, "Process")
    if (-not [string]::IsNullOrWhiteSpace($projectKey)) {
        return "process_env"
    }

    $envPath = Join-Path $RepoRoot ".env"
    if (Test-Path -LiteralPath $envPath) {
        foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
            $trimmed = $line.Trim()
            if ($trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
                continue
            }

            $parts = $trimmed.Split("=", 2)
            if ($parts[0].Trim() -ne $projectKeyName) {
                continue
            }

            $value = $parts[1].Trim().Trim('"').Trim("'")
            if (-not [string]::IsNullOrWhiteSpace($value) -and $value -ne "your_openai_api_key_here") {
                return ".env"
            }
        }
    }

    $standardKey = [Environment]::GetEnvironmentVariable($standardKeyName, "Process")
    if (-not [string]::IsNullOrWhiteSpace($standardKey)) {
        return "standard_env_ignored"
    }

    return "missing"
}

function Test-HistoricalEtlNeeded {
    if ($ForceHistoricalEtl) {
        return [ordered]@{
            Needed = $true
            Yesterday = (Get-JstToday).AddDays(-1).ToString("yyyy-MM-dd")
            Reason = "manual_force"
        }
    }

    $yesterday = (Get-JstToday).AddDays(-1).ToString("yyyy-MM-dd")
    $publicDir = Join-Path $RepoRoot "web/public"
    $statePath = Join-Path $publicDir ".etl_state.json"
    $actualPath = Join-Path $publicDir "actual/$yesterday.json"

    if (-not (Test-Path -LiteralPath $statePath)) {
        return [ordered]@{ Needed = $true; Yesterday = $yesterday; Reason = "missing_etl_state" }
    }
    if (-not (Test-Path -LiteralPath $actualPath)) {
        return [ordered]@{ Needed = $true; Yesterday = $yesterday; Reason = "missing_yesterday_actual" }
    }

    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return [ordered]@{ Needed = $true; Yesterday = $yesterday; Reason = "invalid_etl_state" }
    }

    $okDates = @($state.okDates)
    if ($okDates -notcontains $yesterday) {
        return [ordered]@{ Needed = $true; Yesterday = $yesterday; Reason = "yesterday_not_finalized" }
    }

    try {
        $actual = Get-Content -LiteralPath $actualPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return [ordered]@{ Needed = $true; Yesterday = $yesterday; Reason = "invalid_yesterday_actual" }
    }

    $observedHours = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($point in @($actual.series)) {
        if ($null -eq $point.actualMw) {
            continue
        }
        if ($point.actualSource -eq "tepco_forecast_fallback") {
            continue
        }

        $ts = [string]$point.ts
        if (-not $ts.StartsWith($yesterday) -or $ts.Length -lt 13) {
            continue
        }

        $hour = 0
        if ([int]::TryParse($ts.Substring(11, 2), [ref]$hour)) {
            [void]$observedHours.Add($hour)
        }
    }

    if ($observedHours.Count -ge 24) {
        return [ordered]@{
            Needed = $false
            Yesterday = $yesterday
            Reason = "yesterday_already_finalized"
        }
    }

    return [ordered]@{
        Needed = $true
        Yesterday = $yesterday
        Reason = "only_$($observedHours.Count)_observed_hours"
    }
}

function Invoke-IntradayDispatch {
    param(
        [bool]$Published = $false,
        [bool]$DeployTriggered = $false,
        [bool]$HistoricalEtlSkipped = $false,
        [string]$HistoricalEtlDate = "",
        [string]$HistoricalEtlReason = ""
    )

    if ($SkipDeploy -or $SkipIntradayDispatch) {
        return
    }

    Write-LocalEtlStatus `
        -Status "running" `
        -Stage "trigger_intraday" `
        -Message "Triggering Intraday Update workflow" `
        -Published $Published `
        -DeployTriggered $DeployTriggered `
        -HistoricalEtlSkipped $HistoricalEtlSkipped `
        -HistoricalEtlDate $HistoricalEtlDate `
        -HistoricalEtlReason $HistoricalEtlReason
    Invoke-Native -FilePath "py" -Arguments @("-3.14", "scripts/trigger_deploy_workflow.py", "--workflow", "intraday.yml")
}

Push-Location $RepoRoot
try {
    Start-Transcript -Path $LogPath -Append | Out-Null
    Write-LocalEtlStatus -Status "running" -Stage "starting" -Message "Local ETL started"

    if (-not $AllowOffSchedule -and -not $ForceHistoricalEtl -and -not (Test-LocalEtlScheduleWindow)) {
        $jstNow = Get-JstNow
        $message = "Skipped off-schedule local ETL at $($jstNow.ToString("yyyy-MM-dd HH:mm:ss zzz")); pass -AllowOffSchedule for manual recovery runs"
        Write-Host "[SCHEDULE] $message"
        Write-LocalEtlStatus -Status "ok" -Stage "skipped_off_schedule" -Message $message
        return
    }

    $openAiKeySource = Get-ProjectOpenAiKeySource
    Write-Host "[OPENAI] TOKYO_GRID_EMS_OPENAI_API_KEY source: $openAiKeySource"
    if ($openAiKeySource -eq "standard_env_ignored") {
        Write-Host "[OPENAI] Ignoring process OPENAI_API_KEY; use TOKYO_GRID_EMS_OPENAI_API_KEY for report generation"
    }

    if (-not $SkipRestore) {
        Write-LocalEtlStatus -Status "running" -Stage "restore_data_branch" -Message "Restoring web/public from origin/data"
        Invoke-Native -FilePath "py" -Arguments @("-3.14", "scripts/restore_public_from_data_branch.py")
    }

    $historicalCheck = Test-HistoricalEtlNeeded
    if ($Publish -and -not $historicalCheck.Needed) {
        Write-LocalEtlStatus `
            -Status "running" `
            -Stage "historical_etl_skipped" `
            -Message "Yesterday is already finalized; skipping Docker ETL and dispatching intraday only" `
            -HistoricalEtlSkipped $true `
            -HistoricalEtlDate $historicalCheck.Yesterday `
            -HistoricalEtlReason $historicalCheck.Reason

        $intradayTriggered = $false
        if (-not $SkipDeploy -and -not $SkipIntradayDispatch) {
            Invoke-IntradayDispatch `
                -HistoricalEtlSkipped $true `
                -HistoricalEtlDate $historicalCheck.Yesterday `
                -HistoricalEtlReason $historicalCheck.Reason
            $intradayTriggered = $true
        }
        $completedMessage = if ($intradayTriggered) {
            "Local ETL skipped because yesterday is already finalized; intraday dispatch queued current-day refresh"
        }
        else {
            "Local ETL skipped because yesterday is already finalized; intraday dispatch was not requested"
        }

        Write-LocalEtlStatus `
            -Status "ok" `
            -Stage "completed" `
            -Message $completedMessage `
            -IntradayTriggered $intradayTriggered `
            -HistoricalEtlSkipped $true `
            -HistoricalEtlDate $historicalCheck.Yesterday `
            -HistoricalEtlReason $historicalCheck.Reason
        return
    }

    if ($Build) {
        Write-LocalEtlStatus -Status "running" -Stage "docker_build" -Message "Building Docker ETL image"
        Invoke-Native -FilePath "docker" -Arguments @("compose", "build", "etl")
    }

    # Use a one-shot container for Task Scheduler reliability. `docker compose up`
    # can leave the scheduler waiting even after the ETL container exits.
    $composeArgs = @("compose", "run", "--rm", "--no-TTY", "etl")
    Write-LocalEtlStatus -Status "running" -Stage "docker_etl" -Message "Running Docker ETL"
    Invoke-Native -FilePath "docker" -Arguments $composeArgs
    Write-LocalEtlStatus -Status "running" -Stage "docker_etl_finished" -Message "Docker ETL finished; preparing publish"

    $published = $false
    $deployTriggered = $false
    $intradayTriggered = $false
    if ($Publish) {
        if (-not $SkipValidation) {
            Write-LocalEtlStatus -Status "running" -Stage "validate_public" -Message "Validating web/public before publish"
            Invoke-Native -FilePath "py" -Arguments @("-3.14", "scripts/validate_public_before_publish.py")
        }

        # This status file is included in the data branch commit. If the publish
        # succeeds, this snapshot is accurate; if it fails, catch{} overwrites the
        # local copy with the failure details and no data-branch commit is made.
        Write-LocalEtlStatus -Status "ok" -Stage "ready_to_publish" -Message "Generated artifacts validated; publishing this snapshot to origin/data" -Published $true
        $publishArgs = @("-3.14", "scripts/publish_data_branch.py")
        if ($SkipValidation) {
            $publishArgs += "--skip-validation"
        }
        Invoke-Native -FilePath "py" -Arguments $publishArgs
        $published = $true

        if (-not $SkipDeploy) {
            Write-LocalEtlStatus -Status "running" -Stage "trigger_deploy" -Message "Triggering Deploy Only workflow" -Published $published
            Invoke-Native -FilePath "py" -Arguments @("-3.14", "scripts/trigger_deploy_workflow.py", "--workflow", "deploy.yml")
            $deployTriggered = $true

            if (-not $SkipIntradayDispatch) {
                Invoke-IntradayDispatch -Published $published -DeployTriggered $deployTriggered
                $intradayTriggered = $true
            }
        }
    }

    Write-LocalEtlStatus -Status "ok" -Stage "completed" -Message "Local ETL completed" -Published $published -DeployTriggered $deployTriggered -IntradayTriggered $intradayTriggered
}
catch {
    Write-LocalEtlStatus -Status "failed" -Stage "failed" -Message $_.Exception.Message
    throw
}
finally {
    try {
        Stop-Transcript | Out-Null
    }
    catch {
        # Transcript may not have started if PowerShell failed very early.
    }
    Pop-Location
}
