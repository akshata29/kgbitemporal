<#
.SYNOPSIS
  Adds/updates the Postgres firewall rule so this machine can reach the demo database.

.PARAMETER Cidr      Single IP or "start-end" range. Default: your public IP as seen by a web service.
.PARAMETER Discover  Use when the default does not work (corporate NAT/proxy: the address Azure sees for database
                     connections differs from the web-facing one). Opens 0.0.0.0-255.255.255.255 for ~1 minute,
                     asks the server which address you connect from, restricts the rule to that /24, and removes
                     the temporary rule. The database password still protects the server during that minute.
#>
[CmdletBinding()]
param([string]$Cidr = "", [switch]$Discover, [switch]$Quiet)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
if (-not (Test-Path .env)) { Write-Host "No .env found. Run deploy.ps1 first."; exit 1 }
$cfg = @{}; Get-Content .env | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $cfg[$matches[1]] = $matches[2] } }
$rg = $cfg["AZ_RG"]; $srv = $cfg["AZ_SERVER"]

function Set-Rule($name, $start, $end) {
    & az postgres flexible-server firewall-rule create -g $rg -s $srv -n $name --start-ip-address $start --end-ip-address $end -o none 2>&1 | Out-Null
    return $LASTEXITCODE
}

if ($Discover) {
    $venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) { $venvPy = "python" }
    Write-Host "Temporarily opening firewall to discover this machine's address..."
    [void](Set-Rule "tmp-discover" "0.0.0.0" "255.255.255.255")
    try {
        $addr = $null
        for ($i = 0; $i -lt 8 -and -not $addr; $i++) {
            Start-Sleep 10
            $addr = (& $venvPy -c "import kgdb;c=kgdb.connect(dbname='postgres');print(c.execute('select inet_client_addr()::text a').fetchone()['a'])" 2>$null | Select-Object -Last 1)
        }
    } finally {
        & az postgres flexible-server firewall-rule delete -g $rg -s $srv -n tmp-discover --yes 2>&1 | Out-Null
    }
    if (-not $addr) { Write-Host "Could not discover the address; temporary rule removed. Use -Cidr <range>."; exit 2 }
    $ip = ($addr -replace '/\d+$', '').Trim()
    $o = $ip.Split('.')
    # Egress addresses can rotate within the same /24 behind a NAT, so allow that /24 rather than one address.
    $start = "$($o[0]).$($o[1]).$($o[2]).0"; $end = "$($o[0]).$($o[1]).$($o[2]).255"
    [void](Set-Rule "demo-client" $start $end)
    Write-Host "Firewall rule demo-client = $start - $end (temporary open rule removed)."
    exit 0
}

if (-not $Cidr) { $Cidr = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 15).Trim() }
if ($Cidr -match '^(.+)-(.+)$') { $start = $matches[1]; $end = $matches[2] } else { $start = $Cidr; $end = $Cidr }
$code = Set-Rule "demo-client" $start $end
if ($code -ne 0) { Write-Host "Failed to set firewall rule."; exit 1 }
if (-not $Quiet) { Write-Host "Firewall rule demo-client = $start - $end" }
exit 0
