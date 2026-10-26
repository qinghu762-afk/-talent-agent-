param([switch]$DryRun,[switch]$PrerequisitesOnly,[int]$WaitSeconds=180)
. (Join-Path $PSScriptRoot 'common.ps1')
if ($DryRun) { Write-Host 'PLAN: read-only engine identity and new-project health; local gateway reachability; no Docker global changes.'; return }
Assert-DockerIdentity | Out-Null
if (!(Test-Path -LiteralPath (Join-Path $script:ProjectRoot '.env'))) { throw 'Run platform/scripts/start.ps1 to initialize new configuration.' }
Invoke-Compose config --quiet
if ($PrerequisitesOnly) { return }
$expected = @(Invoke-Compose config --services)
$deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
do {
 $raw = (Invoke-Compose ps --all --format json) -join "`n"
 $containers = @()
 if ($raw.Trim().StartsWith('[')) { $containers = @($raw | ConvertFrom-Json) }
 else { $containers = @($raw -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json }) }
 $unready = @()
 foreach ($name in $expected) {
  $container = @($containers | Where-Object { $_.Service -eq $name })
  if (!$container.Count) { $unready += "$name (missing)"; continue }
  $item = $container[0]
  if ($name -in @('dify-init-permissions','milvus-init')) {
   if ($item.State -ne 'exited' -or $item.ExitCode -ne 0) { $unready += "$name (initialization incomplete)" }
  } elseif ($item.State -ne 'running' -or ($item.Health -and $item.Health -ne 'healthy')) { $unready += "$name ($($item.State)/$($item.Health))" }
 }
 if (!$unready.Count) { break }
 if ([DateTime]::UtcNow -ge $deadline) { throw ('New platform services are not ready: ' + ($unready -join ', ')) }
 Start-Sleep -Seconds 3
} while ($true)
foreach ($url in @('http://127.0.0.1:18080/api/v1/health','http://127.0.0.1:18081/console/api/setup')) {
 $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 15
 if ($response.StatusCode -ne 200) { throw "Readiness failed: $url" }
}
$setup = Invoke-RestMethod -Uri 'http://127.0.0.1:18081/console/api/setup' -TimeoutSec 15
if ($setup.step -ne 'finished') { throw 'Dedicated Dify administrator bootstrap is incomplete.' }
$models = (Invoke-Compose exec -T model-gateway python -c 'import urllib.request; print(urllib.request.urlopen("http://localhost:11434/api/tags",timeout=10).read().decode())') -join "`n"
$available = @((($models | ConvertFrom-Json).models) | ForEach-Object { $_.name })
foreach ($model in @((Get-ConfigurationValue 'CHAT_MODEL' 'qwen3:4b'),(Get-ConfigurationValue 'EMBEDDING_MODEL' 'bge-m3'))) {
 if ($model -notin $available -and ($model + ':latest') -notin $available) { throw "Required Ollama model is unavailable through the container gateway: $model" }
}
foreach ($key in @('DIFY_APP_ID','DIFY_APP_KEY','DIFY_DATASET_KEY')) {
 if (!(Get-ConfigurationValue $key)) { throw "Dedicated Dify bootstrap configuration is incomplete: $key" }
}
Write-Host 'New-platform readiness checks passed.'
