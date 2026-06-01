param(
    [string]$TaskName = "TokyoGridEMS Local ETL",
    [string[]]$Times = @("07:30", "08:30", "09:30")
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ScriptPath = Join-Path $RepoRoot "scripts/local_etl.ps1"
$Argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Publish"

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Argument -WorkingDirectory $RepoRoot
$Triggers = foreach ($Time in $Times) {
    New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.Add([TimeSpan]::Parse($Time)))
}
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "Run TokyoGridEMS local Docker ETL until yesterday is finalized; later morning runs dispatch Intraday Update only." `
    -Force | Out-Null

Write-Host "[SCHEDULER] Registered '$TaskName' at $($Times -join ', ')"
