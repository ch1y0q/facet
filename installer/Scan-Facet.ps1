# Scan a folder (UNC or local) with this install's environment.
# Any extra arguments go straight to facet.py, e.g. --force, --pass faces.
param([Parameter(Mandatory = $true, Position = 0)][string]$Folder,
      [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Facet-Env.ps1"
if (-not (Test-Path $FacetReady)) { & "$PSScriptRoot\Setup-Facet.ps1" }
Push-Location $FacetApp
try { & $FacetPython facet.py $Folder @Rest } finally { Pop-Location }
