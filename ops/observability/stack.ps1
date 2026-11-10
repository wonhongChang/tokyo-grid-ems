param([Parameter(Mandatory)][ValidateSet('Start','Stop','Status','Restart','Down','Verify')][string]$Action)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    function Invoke-Stack([string[]]$Arguments) {
        & docker compose --project-name tgems-observe --env-file defaults.env -f compose.yml @Arguments
        if ($LASTEXITCODE -ne 0) { throw 'Observability Compose operation failed' }
    }
    function Wait-Readiness {
        foreach ($url in @('http://collector:13133/','http://tempo:3200/ready','http://grafana:3000/api/health','http://localhost:9090/-/ready')) {
            $deadline = (Get-Date).AddSeconds(90)
            do {
                & docker compose --project-name tgems-observe --env-file defaults.env -f compose.yml exec -T prometheus wget -T 3 -qO /dev/null $url
                if ($LASTEXITCODE -eq 0) { break }
                if ((Get-Date) -ge $deadline) { throw "Observability readiness failed: $url" }
                Start-Sleep -Seconds 3
            } while ($true)
        }
    }
    if ($Action -eq 'Start') {
        $local = Join-Path $PSScriptRoot '.local'
        if (-not (Test-Path -LiteralPath $local)) { New-Item -ItemType Directory $local | Out-Null }
        if ((Get-Item -Force -LiteralPath $local).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked secret directory' }
        $secret = Join-Path $local 'admin_password'
        if ($env:OS -eq 'Windows_NT') {
            $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
            & icacls $local /inheritance:r /grant:r ("*{0}:(OI)(CI)F" -f $sid) '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not restrict secret directory' }
        } else {
            & chmod 700 $local
            if ($LASTEXITCODE -ne 0) { throw 'Could not restrict secret directory' }
        }
        if (-not (Test-Path -LiteralPath $secret)) {
            $bytes = New-Object byte[] 32
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
            $stream = [IO.File]::Open($secret,[IO.FileMode]::CreateNew)
            try {
                $encoded = [Text.Encoding]::ASCII.GetBytes([Convert]::ToBase64String($bytes))
                $stream.Write($encoded,0,$encoded.Length)
            } finally { $stream.Dispose() }
        }
        if ((Get-Item -Force -LiteralPath $secret).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked secret file' }
        # On Linux keep the directory private; the file-mounted Compose secret
        # must still be readable by Grafana's non-root container UID.
        Invoke-Stack @('up','-d','--wait','--wait-timeout','180')
        Wait-Readiness
    } elseif ($Action -eq 'Verify') {
        Wait-Readiness
        Invoke-Stack @('exec','-T','prometheus','promtool','check','rules','/etc/tgems/rules.yml')
    } elseif ($Action -eq 'Stop') { Invoke-Stack @('stop') }
    elseif ($Action -eq 'Down') { Invoke-Stack @('down') }
    elseif ($Action -eq 'Restart') { Invoke-Stack @('restart'); Wait-Readiness }
    else { Invoke-Stack @('ps') }
} finally { Pop-Location }
