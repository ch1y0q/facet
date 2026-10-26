# Build (or repair) the Facet Python environment. Runs once after install; safe to re-run.
# Mirrors the CUDA Dockerfile: torch 2.11.0+cu128 first, both lock files with torch held,
# then the CPU onnxruntime swapped for onnxruntime-gpu 1.26.0 (the last CUDA 12 build).
param([switch]$Force)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Facet-Env.ps1"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

if ((Test-Path $FacetReady) -and -not $Force) {
    Write-Host "Facet environment already set up ($FacetVenv). Use -Force to rebuild."
    return
}
New-Item -ItemType Directory -Force $FacetData, $FacetConfig, $FacetLogs | Out-Null

Step 'Python 3.12 virtual environment'
& $FacetUv venv $FacetVenv --python 3.12 --allow-existing
if ($LASTEXITCODE) { throw 'uv venv failed' }

$hasCuda = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$constraint = Join-Path $env:TEMP 'facet-torch-constraint.txt'
if ($hasCuda) {
    Step 'PyTorch 2.11.0 (CUDA 12.8)'
    & $FacetUv pip install --python $FacetPython 'torch==2.11.0' 'torchvision==0.26.0' --index-url https://download.pytorch.org/whl/cu128
    Set-Content $constraint "torch==2.11.0+cu128`ntorchvision==0.26.0+cu128" -Encoding ascii
    $extra = @('--extra-index-url', 'https://download.pytorch.org/whl/cu128', '--index-strategy', 'unsafe-best-match')
} else {
    Step 'PyTorch 2.11.0 (CPU, no NVIDIA driver found)'
    & $FacetUv pip install --python $FacetPython 'torch==2.11.0' 'torchvision==0.26.0' --index-url https://download.pytorch.org/whl/cpu
    Set-Content $constraint "torch==2.11.0+cpu`ntorchvision==0.26.0+cpu" -Encoding ascii
    $extra = @('--extra-index-url', 'https://download.pytorch.org/whl/cpu', '--index-strategy', 'unsafe-best-match')
}
if ($LASTEXITCODE) { throw 'torch install failed' }

Step 'Facet dependencies (requirements.lock.txt + restricted lock)'
& $FacetUv pip install --python $FacetPython -c $constraint @extra `
    -r (Join-Path $FacetApp 'requirements.lock.txt') -r (Join-Path $FacetApp 'requirements.restricted.lock.txt')
if ($LASTEXITCODE) { throw 'dependency install failed' }

if ($hasCuda) {
    Step 'onnxruntime-gpu 1.26.0 (GPU face detection)'
    & $FacetUv pip uninstall --python $FacetPython onnxruntime onnxruntime-gpu
    & $FacetUv pip install --python $FacetPython 'onnxruntime-gpu==1.26.0'
    if ($LASTEXITCODE) { throw 'onnxruntime-gpu install failed' }
}

if (-not (Test-Path $env:FACET_CONFIG)) {
    Step "New config: $env:FACET_CONFIG"
    Set-Content $env:FACET_CONFIG '{}' -Encoding ascii
    Write-Host 'Set viewer.edition_password in it before editing in the viewer (see docs/CONFIGURATION.md).'
}

Step 'Check'
& $FacetPython -c "import torch, onnxruntime as o; print('torch', torch.__version__, 'CUDA' if torch.cuda.is_available() else 'CPU'); print('onnxruntime', o.__version__, o.get_available_providers())"
if ($LASTEXITCODE) { throw 'import check failed' }
Push-Location $FacetApp
try { & $FacetPython database.py; if ($LASTEXITCODE) { throw 'database init failed' } } finally { Pop-Location }

Set-Content $FacetReady (Get-Date -Format s) -Encoding ascii
Write-Host "`nFacet is ready. Start it from the Start menu: Facet." -ForegroundColor Green
