param([Parameter(Mandatory)][ValidateSet('Install','Start','Stop','Restart','Enable','Disable','Remove','Status')][string]$Action)
$ErrorActionPreference = 'Stop'
$name = 'TokyoGridEMS Observability Public Reader'
$description = 'TokyoGridEMS public observability only; isolated user-logon reader.'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$exe = Join-Path $PSScriptRoot '.local/reader-venv/Scripts/pythonw.exe'
$entry = Join-Path $PSScriptRoot 'run-reader.py'
$argsText = '-I -B "' + $entry + '"'
$dir = Join-Path $repo 'logs/observability/public-reader'
$task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
if ($task -and ($task.Description -ne $description -or @($task.Actions).Count -ne 1 -or
    $task.Actions[0].Execute -ne $exe -or $task.Actions[0].Arguments -ne $argsText)) {
    throw 'Task ownership/path mismatch; refusing to change it.'
}
function Stop-Reader {
    $current = Get-ScheduledTask -TaskName $name -TaskPath '\'
    if ($current.State -ne 'Running') {return}
    $until = [datetime]::UtcNow.AddSeconds(30)
    do {
        $status = Join-Path $dir 'status.json'
        if (Test-Path -LiteralPath $status) {
            $instance = (Get-Content -LiteralPath $status -Raw | ConvertFrom-Json).instance
            if ($instance -match '^[0-9a-f]{32}$') {
                [IO.File]::WriteAllText((Join-Path $dir 'stop.request'),$instance,[Text.Encoding]::ASCII)
            }
        }
        Start-Sleep -Seconds 1
        if ((Get-ScheduledTask -TaskName $name -TaskPath '\').State -ne 'Running') {return}
    } while ([datetime]::UtcNow -lt $until)
    Stop-ScheduledTask -TaskName $name -TaskPath '\'
    $until = [datetime]::UtcNow.AddSeconds(10)
    while ((Get-ScheduledTask -TaskName $name -TaskPath '\').State -eq 'Running') {
        if ([datetime]::UtcNow -ge $until) {throw 'Reader did not stop.'}
        Start-Sleep -Seconds 1
    }
}
if ($Action -eq 'Install') {
    if (-not (Test-Path -LiteralPath $exe)) {throw 'Prepare the private observability venv first.'}
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger = @(New-ScheduledTaskTrigger -AtLogOn -User $user)
    # Some manually started tasks do not restart on a nonzero process exit.
    # IgnoreNew means this does not launch any process or source read on healthy ticks.
    $trigger += New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 3)
    if (-not $task) {
        $run = New-ScheduledTaskAction -Execute $exe -Argument $argsText -WorkingDirectory $PSScriptRoot
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([timespan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $name -TaskPath '\' -Description $description -Action $run -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    } elseif (-not @($task.Triggers | Where-Object {$_.Repetition.Interval -eq 'PT3M'}).Count) {
        Set-ScheduledTask -TaskName $name -TaskPath '\' -Trigger $trigger | Out-Null
    }
    $Action = 'Enable'
}
elseif (-not $task) { if ($Action -in @('Status','Remove')) {Write-Output 'Not registered';return};throw 'Reader task not registered.' }
switch ($Action) {
    'Start' {Enable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null; Start-ScheduledTask -TaskName $name -TaskPath '\'}
    'Stop' {Stop-Reader; Disable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null; Stop-ScheduledTask -TaskName $name -TaskPath '\'}
    'Restart' {Stop-Reader; Enable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null; Start-ScheduledTask -TaskName $name -TaskPath '\'}
    'Enable' {Enable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null; Start-ScheduledTask -TaskName $name -TaskPath '\'}
    'Disable' {Stop-Reader; Disable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null; Stop-ScheduledTask -TaskName $name -TaskPath '\'}
    'Remove' {Stop-Reader; Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false;return}
}
$current=Get-ScheduledTask -TaskName $name -TaskPath '\'
$info=Get-ScheduledTaskInfo -TaskName $name -TaskPath '\'
$state=Join-Path $dir 'status.json'
$record=if(Test-Path -LiteralPath $state){Get-Content -LiteralPath $state -Raw | ConvertFrom-Json}
$alive=if($record){$p=Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    $p -and $p.ProcessName -eq 'pythonw' -and [math]::Abs(([DateTimeOffset]$p.StartTime).ToUnixTimeSeconds()-$record.started) -lt 15}
[pscustomobject]@{Task=$name;State=$current.State.ToString();LastStart=$info.LastRunTime;LastTaskResult=$info.LastTaskResult;
    NextTrigger=$info.NextRunTime;RecordedProcessAlive=[bool]$alive;LastRecordedReader=$record} | ConvertTo-Json -Depth 3
