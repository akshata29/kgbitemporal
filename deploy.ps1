<#
.SYNOPSIS
  Deploys the entity-governance bitemporal KG demo into YOUR Azure subscription and seeds it with synthetic data.

.DESCRIPTION
  Creates: 1 resource group + 1 Azure Database for PostgreSQL Flexible Server (PostgreSQL 17, Burstable,
  public access limited by firewall to your machine). Enables the AGE, btree_gist, temporal_tables,
  fuzzystrmatch and pg_trgm extensions, creates the database, loads the synthetic corpus, writes .env,
  creates a local Python virtual environment, and (optionally) starts the demo UI.

  Re-runnable: pass the same -ResourceGroup and -ServerName to resume/re-seed an existing server.

.PARAMETER SubscriptionId   Subscription to deploy into (default: current az CLI subscription).
.PARAMETER ResourceGroup    Resource group name (created if missing).
.PARAMETER Location         Preferred Azure region for the server.
.PARAMETER FallbackLocations Regions tried in order if the preferred one rejects the SKU.
.PARAMETER ServerName       Globally unique server name (default: pg-kgdemo-<random>).
.PARAMETER Sku              Force one SKU; default tries Standard_B2ms, Standard_B2s, Standard_B1ms.
.PARAMETER AllowedCidr      Client address (or start-end range) for the firewall; default = your public IP.
.PARAMETER DiscoverEgress   If the server is unreachable with the default firewall rule (corporate NAT/proxy), briefly
                            open the firewall, learn the real client address, then lock it down - without prompting.
.PARAMETER Start            Start the UI when finished.
.PARAMETER Yes              Do not prompt for confirmation.

.EXAMPLE
  .\deploy.ps1 -SubscriptionId 00000000-0000-0000-0000-000000000000 -Location eastus2 -Start
#>
[CmdletBinding()]
param(
    [string]$SubscriptionId = "",
    [string]$ResourceGroup = "rg-kgdemo",
    [string]$Location = "centralus",
    [string[]]$FallbackLocations = @("eastus2", "westus3", "northcentralus", "southcentralus"),
    [string]$ServerName = "",
    [string]$Sku = "",
    [string]$AdminUser = "kgadmin",
    [string]$AllowedCidr = "",
    [switch]$DiscoverEgress,
    [switch]$Start,
    [switch]$Yes
)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$Database = "kgdemo"

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

function Invoke-Az {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $out = & az @args 2>&1 | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return [pscustomobject]@{ Code = $code; Out = $out }
}

Step "Pre-flight checks"
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Fail "Azure CLI not found. Install from https://aka.ms/installazurecli" }
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Fail "Python 3.10+ not found on PATH." }
$pyVer = (& python -c "import sys;print('%d.%d'%sys.version_info[:2])").Trim()
if ([version]$pyVer -lt [version]"3.10") { Fail "Python $pyVer found; 3.10 or newer is required." }

$acct = Invoke-Az account show -o json
if ($acct.Code -ne 0) { Fail "Not logged in. Run 'az login' first." }
if ($SubscriptionId) {
    $r = Invoke-Az account set --subscription $SubscriptionId
    if ($r.Code -ne 0) { Fail "Cannot select subscription $SubscriptionId : $($r.Out)" }
}
$acct = (Invoke-Az account show -o json).Out | ConvertFrom-Json
Write-Host "Tenant:        $($acct.tenantId)"
Write-Host "Subscription: $($acct.name) ($($acct.id))"
Write-Host "Resource group: $ResourceGroup    Preferred region: $Location"
Write-Host "This creates a billable PostgreSQL Flexible Server. Pricing: https://aka.ms/postgres-pricing"
if (-not $Yes) {
    $a = Read-Host "Continue? (y/N)"
    if ($a -notmatch '^(y|yes)$') { Write-Host "Aborted."; exit 0 }
}

if (-not $AllowedCidr) {
    try { $AllowedCidr = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 15).Trim() }
    catch { Fail "Could not determine your public IP; pass -AllowedCidr <ip or start-end>." }
}
if (-not $ServerName) { $ServerName = "pg-kgdemo-" + (Get-Random -Minimum 10000 -Maximum 99999) }

# Re-use an existing .env password when resuming; otherwise generate one (alphanumeric, avoids quoting issues).
$password = $null
if (Test-Path .env) {
    $m = Select-String -Path .env -Pattern '^PGPASSWORD=(.+)$' | Select-Object -First 1
    if ($m -and (Select-String -Path .env -Pattern "^AZ_SERVER=$ServerName$" -Quiet)) { $password = $m.Matches[0].Groups[1].Value }
}
if (-not $password) {
    $chars = [char[]]"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    $bytes = New-Object byte[] 28
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

Step "Resource group"
$r = Invoke-Az group create -n $ResourceGroup -l $Location --tags purpose=kg-bitemporal-demo -o none
if ($r.Code -ne 0) { Fail $r.Out }

Step "PostgreSQL Flexible Server (PostgreSQL 17)"
$existing = Invoke-Az postgres flexible-server show -g $ResourceGroup -n $ServerName -o json
$serverLocation = $null
if ($existing.Code -eq 0) {
    $serverLocation = ($existing.Out | ConvertFrom-Json).location
    Write-Host "Server $ServerName already exists in $serverLocation - resuming."
} else {
    $skus = @(); if ($Sku) { $skus = @($Sku) } else { $skus = @("Standard_B2ms", "Standard_B2s", "Standard_B1ms") }
    $regions = @($Location) + $FallbackLocations | Where-Object { $_ } | Select-Object -Unique
    foreach ($loc in $regions) {
        foreach ($s in $skus) {
            Write-Host "Trying $s in $loc ..."
            $r = Invoke-Az postgres flexible-server create -g $ResourceGroup -n $ServerName -l $loc --version 17 `
                --tier Burstable --sku-name $s --storage-size 32 --admin-user $AdminUser --admin-password $password `
                --public-access $AllowedCidr --yes -o none
            if ($r.Code -eq 0) { $serverLocation = $loc; break }
            if ($r.Out -match "SkuNotAvailable|not supported in this region|LocationNotAvailable|RegionDoesNotAllowProvisioning") { continue }
            if ($r.Out -match "already exists|ServerNameAlreadyExists") { Fail "Server name '$ServerName' is taken; rerun with -ServerName <unique>." }
            Fail $r.Out
        }
        if ($serverLocation) { break }
    }
    if (-not $serverLocation) { Fail "No region/SKU combination worked ($($regions -join ', ')). Pass -Location/-FallbackLocations/-Sku for a region where your subscription can create PostgreSQL Flexible Server." }
    Write-Host "Created $ServerName in $serverLocation"
}

Step "Enable extensions (AGE needs shared_preload_libraries + restart)"
$r = Invoke-Az postgres flexible-server parameter set -g $ResourceGroup -s $ServerName -n azure.extensions --value "AGE,BTREE_GIST,TEMPORAL_TABLES,FUZZYSTRMATCH,PG_TRGM" -o none
if ($r.Code -ne 0) { Fail $r.Out }
$r = Invoke-Az postgres flexible-server parameter set -g $ResourceGroup -s $ServerName -n shared_preload_libraries --value "age" -o none
if ($r.Code -ne 0) { Fail $r.Out }
$r = Invoke-Az postgres flexible-server restart -g $ResourceGroup -n $ServerName
if ($r.Code -ne 0) { Fail $r.Out }

Step "Write .env"
$fqdn = (Invoke-Az postgres flexible-server show -g $ResourceGroup -n $ServerName --query fullyQualifiedDomainName -o tsv).Out.Trim()
$envText = @(
    "PGHOST=$fqdn", "PGPORT=5432", "PGDATABASE=$Database", "PGUSER=$AdminUser", "PGPASSWORD=$password", "PGSSLMODE=require",
    "AZ_RG=$ResourceGroup", "AZ_SERVER=$ServerName"
) -join "`r`n"
Set-Content -Path .env -Value $envText -Encoding ASCII
Write-Host "Wrote .env (contains the database password - do not commit or share)."

Step "Firewall"
$r = Invoke-Az postgres flexible-server update -g $ResourceGroup -n $ServerName --public-access Enabled -o none
if ($r.Code -ne 0 -and $r.Out -notmatch "already|no change|nothing") { Write-Host "(public access update: $($r.Out.Trim()))" -ForegroundColor Yellow }
& "$PSScriptRoot\allow-my-ip.ps1" -Cidr $AllowedCidr -Quiet

Step "Python environment"
if (-not (Test-Path .venv)) { & python -m venv .venv }
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }

Step "Connectivity check"
$ok = $false
for ($i = 1; $i -le 6 -and -not $ok; $i++) {
    & $venvPy -c "import kgdb; kgdb.connect(dbname='postgres').close()" 2>$null
    if ($LASTEXITCODE -eq 0) { $ok = $true } else { Write-Host "  not reachable yet ($i/6); firewall rules can take up to a minute..."; Start-Sleep 15 }
}
if (-not $ok) {
    Write-Host "This machine's address as seen by Azure may differ from $AllowedCidr (corporate NAT/proxy)." -ForegroundColor Yellow
    $d = "n"
    if ($DiscoverEgress) { $d = "y" }
    elseif (-not $Yes) { $d = Read-Host "Temporarily open the firewall for ~1 minute to discover the real address and then lock it down? (y/N)" }
    if ($d -match '^(y|yes)$') { & "$PSScriptRoot\allow-my-ip.ps1" -Discover } else {
        Fail "Server is deployed but unreachable. Run .\allow-my-ip.ps1 -Discover (or -Cidr <range>), then .\deploy.ps1 -ResourceGroup $ResourceGroup -ServerName $ServerName -Yes"
    }
}

Step "Create database, extensions and seed synthetic data"
& $venvPy bootstrap.py
if ($LASTEXITCODE -ne 0) { Fail "Bootstrap failed (see messages above)." }

Write-Host "`nDone." -ForegroundColor Green
Write-Host "  Server : $fqdn  ($serverLocation)"
Write-Host "  Start  : .\run.ps1        then open http://127.0.0.1:8765"
Write-Host "  Remove : .\teardown.ps1   (deletes resource group $ResourceGroup)"
if ($Start) { & "$PSScriptRoot\run.ps1" }
