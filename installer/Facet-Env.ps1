# Shared paths for the Facet Windows launchers. Dot-source it: . "$PSScriptRoot\Facet-Env.ps1"
# Layout (per user, no admin):
#   %LOCALAPPDATA%\Facet\app     code + built client, owned by the MSI (replaced on upgrade)
#   %LOCALAPPDATA%\Facet\venv    Python 3.12 + CUDA torch, built by Setup-Facet.ps1
#   %LOCALAPPDATA%\Facet\data    photo_scores_pro.db, logs
#   %LOCALAPPDATA%\Facet\config  scoring_config.json (the operator override)
$FacetRoot   = if ($env:FACET_HOME) { $env:FACET_HOME } else { Join-Path $env:LOCALAPPDATA 'Facet' }
$FacetApp    = Split-Path $PSScriptRoot -Parent
$FacetVenv   = Join-Path $FacetRoot 'venv'
$FacetData   = Join-Path $FacetRoot 'data'
$FacetConfig = Join-Path $FacetRoot 'config'
$FacetLogs   = Join-Path $FacetData 'logs'
$FacetPython = Join-Path $FacetVenv 'Scripts\python.exe'
$FacetUv     = Join-Path $PSScriptRoot 'bin\uv.exe'
$FacetReady  = Join-Path $FacetVenv '.facet-setup-ok'

$env:FACET_CONFIG       = Join-Path $FacetConfig 'scoring_config.json'
$env:DB_PATH            = Join-Path $FacetData 'photo_scores_pro.db'
$env:PYTHONIOENCODING   = 'utf-8'

# Facet processes of THIS install. A uv venv's python.exe is a launcher that runs the base
# interpreter as a child, so match the launcher by path and take its children with it.
function Get-FacetProcesses {
    $all = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'")
    $launchers = @($all | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($FacetVenv, [StringComparison]::OrdinalIgnoreCase) })
    $ids = $launchers.ProcessId
    $launchers + @($all | Where-Object { $ids -contains $_.ParentProcessId })
}

function Test-PortOpen([int]$Port) {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.ConnectAsync('127.0.0.1', $Port).Wait(500) -and $c.Connected } catch { $false } finally { $c.Dispose() }
}
