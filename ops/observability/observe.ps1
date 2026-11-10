param([Parameter(Mandatory)][ValidateSet('restore','batch','fetch','validate','publish','dispatch')][string]$Command,
      [switch]$Docker, [switch]$NoTelemetry, [string[]]$Arguments = @())
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '../..')
Push-Location $root
$before = $env:TGEMS_OTEL_ENABLED
try {
    $env:TGEMS_OTEL_ENABLED = if ($NoTelemetry) { '0' } else { '1' }
    if ($Docker) {
        & python -m python.observability.host --docker $Command @Arguments
    } else {
        & python -m python.observability.host $Command @Arguments
    }
    $exitCode = $LASTEXITCODE
} finally {
    $env:TGEMS_OTEL_ENABLED = $before
    Pop-Location
}
exit $exitCode
