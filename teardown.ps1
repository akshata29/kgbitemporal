# Deletes EVERYTHING deploy.ps1 created (the resource group: Postgres server + data). Irreversible.
param([string]$ResourceGroup = "", [switch]$Yes)
Set-Location $PSScriptRoot
if (-not $ResourceGroup -and (Test-Path .env)) {
    $m = Select-String -Path .env -Pattern '^AZ_RG=(.+)$' | Select-Object -First 1
    if ($m) { $ResourceGroup = $m.Matches[0].Groups[1].Value }
}
if (-not $ResourceGroup) { Write-Host "Pass -ResourceGroup <name>."; exit 1 }
if (-not $Yes) {
    $ans = Read-Host "Delete resource group '$ResourceGroup' and ALL resources in it? (type YES)"
    if ($ans -ne "YES") { "Aborted."; exit 0 }
}
az group delete -n $ResourceGroup --yes --no-wait
"Deletion started. Verify with: az group exists -n $ResourceGroup"
