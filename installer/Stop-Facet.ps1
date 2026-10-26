# Stop every Facet process (viewer and scans) started from this install's venv.
. "$PSScriptRoot\Facet-Env.ps1"
$procs = @(Get-FacetProcesses)
if (-not $procs) { Write-Host 'Facet is not running.'; return }
foreach ($p in $procs) {
    taskkill /T /F /PID $p.ProcessId 2>$null | Out-Null
    Write-Host "Stopped $($p.ProcessId): $($p.CommandLine)"
}
