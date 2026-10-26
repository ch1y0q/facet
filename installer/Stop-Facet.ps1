# Stop every Facet process (viewer and scans) started from this install's venv.
. "$PSScriptRoot\Facet-Env.ps1"
Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($FacetVenv, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped $($_.ProcessId): $($_.CommandLine)" }
