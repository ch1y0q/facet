# Start the Facet viewer in the background (no window) and open it in the browser.
# -Lan binds 0.0.0.0 so other devices can connect (needs a firewall rule for the port).
param([int]$Port = 5000, [switch]$Lan, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Facet-Env.ps1"

if (-not (Test-Path $FacetReady) -or -not (Test-Path (Join-Path $FacetExifTool 'exiftool.exe'))) {
    Write-Host 'First run: setting up the Python environment (downloads about 6 GB, 10-20 minutes).'
    & "$PSScriptRoot\Setup-Facet.ps1"
}

$url = "http://localhost:$Port/"
# Probe the port by connecting: a listener behind WSL mirrored networking (the Docker
# install) is invisible to Get-NetTCPConnection but still owns the port.
if (Test-PortOpen $Port) {
    $ours = Get-FacetProcesses | Where-Object { $_.CommandLine -match 'viewer\.py' -and $_.CommandLine -match "--port $Port\b" }
    if ($ours) {
        if (-not $NoBrowser) { Start-Process $url }
        return
    }
    throw "Port $Port is already in use by another program (the Docker install?). Stop it, or run Start-Facet.ps1 -Port <other>."
}

New-Item -ItemType Directory -Force $FacetLogs | Out-Null
$bind = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$proc = Start-Process -FilePath $FacetPython -ArgumentList @('viewer.py', '--production', '--port', $Port, '--host', $bind) `
    -WorkingDirectory $FacetApp -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $FacetLogs 'viewer.out.log') `
    -RedirectStandardError (Join-Path $FacetLogs 'viewer.log')

for ($i = 0; $i -lt 90; $i++) {
    if ($proc.HasExited) {
        $tail = Get-Content (Join-Path $FacetLogs 'viewer.log') -Tail 15 -ErrorAction SilentlyContinue
        throw "Facet viewer exited during start (code $($proc.ExitCode)). Log:`n$($tail -join "`n")"
    }
    if (Test-PortOpen $Port) { break }
    Start-Sleep -Seconds 1
}
if (-not $NoBrowser) { Start-Process $url }
