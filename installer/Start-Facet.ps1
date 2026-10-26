# Start the Facet viewer in the background (no window) and open it in the browser.
# -Lan binds 0.0.0.0 so other devices can connect (needs a firewall rule for the port).
param([int]$Port = 5000, [switch]$Lan, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Facet-Env.ps1"

if (-not (Test-Path $FacetReady)) {
    Write-Host 'First run: setting up the Python environment (downloads about 6 GB, 10-20 minutes).'
    & "$PSScriptRoot\Setup-Facet.ps1"
}

$url = "http://localhost:$Port/"
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $owner = (Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue).Path
    if ($owner -and $owner.StartsWith($FacetVenv, [StringComparison]::OrdinalIgnoreCase)) {
        if (-not $NoBrowser) { Start-Process $url }
        return
    }
    throw "Port $Port is already used by $owner. Stop it, or run Start-Facet.ps1 -Port <other>."
}

New-Item -ItemType Directory -Force $FacetLogs | Out-Null
$bind = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
Start-Process -FilePath $FacetPython -ArgumentList @('viewer.py', '--port', $Port, '--host', $bind) `
    -WorkingDirectory $FacetApp -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $FacetLogs 'viewer.out.log') `
    -RedirectStandardError (Join-Path $FacetLogs 'viewer.log')

for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
}
if (-not $NoBrowser) { Start-Process $url }
