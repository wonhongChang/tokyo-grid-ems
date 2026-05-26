param(
    [switch]$Publish,
    [switch]$Build,
    [switch]$SkipRestore,
    [switch]$SkipDeploy,
    [switch]$SkipValidation,
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
        [bool]$DeployTriggered = $false
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
    }
    $payload | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $opsDir "local_etl_status.json") -Encoding UTF8
}

Push-Location $RepoRoot
try {
    Start-Transcript -Path $LogPath -Append | Out-Null
    Write-LocalEtlStatus -Status "running" -Stage "starting" -Message "Local ETL started"

    if (-not $SkipRestore) {
        Write-LocalEtlStatus -Status "running" -Stage "restore_data_branch" -Message "Restoring web/public from origin/data"
        Invoke-Native -FilePath "py" -Arguments @("-3.14", "scripts/restore_public_from_data_branch.py")
    }

    $composeArgs = @("compose", "up", "--force-recreate", "--exit-code-from", "etl")
    if ($Build) {
        $composeArgs += "--build"
    }
    $composeArgs += "etl"
    Write-LocalEtlStatus -Status "running" -Stage "docker_etl" -Message "Running Docker ETL"
    Invoke-Native -FilePath "docker" -Arguments $composeArgs

    $published = $false
    $deployTriggered = $false
    if ($Publish) {
        if (-not $SkipValidation) {
            Write-LocalEtlStatus -Status "running" -Stage "validate_public" -Message "Validating web/public before publish"
            Invoke-Native -FilePath "py" -Arguments @("-3.14", "scripts/validate_public_before_publish.py")
        }

        Write-LocalEtlStatus -Status "running" -Stage "publish_data_branch" -Message "Publishing web/public to origin/data"
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
        }
    }

    Write-LocalEtlStatus -Status "ok" -Stage "completed" -Message "Local ETL completed" -Published $published -DeployTriggered $deployTriggered
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
