param(
    [string]$TaskName = "TokyoGridEMS Local ETL"
)

$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[SCHEDULER] Unregistered '$TaskName'"
