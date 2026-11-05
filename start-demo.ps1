<#
.SYNOPSIS
  One-step "get me running": starts the demo server if it is stopped, makes sure the firewall lets this machine in,
  checks the database connection, then starts the UI.

.PARAMETER OpenToAll  Open the firewall to all addresses (0.0.0.0-255.255.255.255) instead of detecting yours.
                      Fastest and most reliable behind a corporate proxy/VPN, but the server is internet-reachable
                      (password + TLS still apply). Remove with: az postgres flexible-server firewall-rule delete ... -n demo-open
.PARAMETER NoRun      Do everything except start the UI.
#>
[CmdletBinding()]
param([switch]$OpenToAll, [switch]$NoRun)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path .env)) { Fail "No .env here. Run deploy.ps1 first, or copy the .env of an existing demo server into this folder." }
$cfg = @{}; Get-Content .env | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $cfg[$matches[1]] = $matches[2] } }
$rg = $cfg["AZ_RG"]; $srv = $cfg["AZ_SERVER"]
if (-not $rg -or -not $srv) { Fail ".env has no AZ_RG / AZ_SERVER, so the server can't be managed. Add them or start the server manually." }

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"; if (-not (Test-Path $py)) { $py = "python" }
function Test-Db {
    & $py -c "import kgdb; kgdb.connect().close()" 2>$null
    return ($LASTEXITCODE -eq 0)
}

Step "Azure sign-in"
az account show -o none 2>$null
if ($LASTEXITCODE -ne 0) { Fail "Not signed in to Azure CLI. Run 'az login --tenant <tenant-id>' first." }

Step "Server '$srv'"
$state = (az postgres flexible-server show -g $rg -n $srv --query state -o tsv 2>$null)
if (-not $state) { Fail "Server not found or no access (check subscription: az account show)." }
Write-Host "State: $state"
if ($state -ne "Ready") {
    if ($state -ne "Starting") { Write-Host "Starting server..."; az postgres flexible-server start -g $rg -n $srv 2>&1 | Out-Null }
    for ($i = 1; $i -le 30 -and $state -ne "Ready"; $i++) {
        Start-Sleep 15
        $state = (az postgres flexible-server show -g $rg -n $srv --query state -o tsv 2>$null)
        Write-Host "  state: $state"
    }
    if ($state -ne "Ready") { Fail "Server did not reach 'Ready' (state: $state)." }
}

Step "Database connection"
if (Test-Db) { Write-Host "Connected." } else {
    if ($OpenToAll) {
        Write-Host "Opening firewall to all addresses (rule demo-open)..."
        az postgres flexible-server firewall-rule create -g $rg -s $srv -n demo-open --start-ip-address 0.0.0.0 --end-ip-address 255.255.255.255 -o none 2>&1 | Out-Null
    } else {
        Write-Host "Not reachable; setting firewall rule for your public IP..."
        & "$PSScriptRoot\allow-my-ip.ps1" -Quiet
    }
    $ok = $false
    for ($i = 1; $i -le 8 -and -not $ok; $i++) {
        if (Test-Db) { $ok = $true } else { Write-Host "  waiting for firewall rule ($i/8)..."; Start-Sleep 15 }
    }
    if (-not $ok -and -not $OpenToAll) {
        Write-Host "Your public IP isn't the address Azure sees (proxy/VPN). Detecting the real one..." -ForegroundColor Yellow
        & "$PSScriptRoot\allow-my-ip.ps1" -Discover
        for ($i = 1; $i -le 6 -and -not $ok; $i++) {
            if (Test-Db) { $ok = $true } else { Write-Host "  waiting ($i/6)..."; Start-Sleep 15 }
        }
    }
    if (-not $ok) { Fail "Still can't connect. Try: .\start-demo.ps1 -OpenToAll" }
    Write-Host "Connected."
}

Write-Host "`nReady: http://127.0.0.1:8765" -ForegroundColor Green
if (-not $NoRun) { & "$PSScriptRoot\run.ps1" }
