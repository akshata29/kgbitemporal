# Starts the demo UI on http://127.0.0.1:8765 (run deploy.ps1 first).
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m uvicorn app:app --port 8765
