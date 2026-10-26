param([switch]$DryRun)
. (Join-Path $PSScriptRoot 'common.ps1')
if ($DryRun) { Write-Host 'PLAN: initialize safe analytics views and only new Dify; save generated app keys to platform/.env; recreate only new application consumers.'; return }
Assert-DockerIdentity | Out-Null
Invoke-Compose exec -T dify-api flask upgrade-db
$python = Join-Path $script:RepositoryRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Provide the local bootstrap Python with httpx and PyYAML installed at ../.venv/Scripts/python.exe.' }
for ($attempt=0; $attempt -lt 120; $attempt++) {
 try {
  $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:18080/api/v1/health' -TimeoutSec 5
  if ($response.StatusCode -eq 200) { break }
 } catch { }
 if ($attempt -eq 119) { throw 'Platform API did not become ready before analytics view setup.' }
 Start-Sleep -Seconds 3
}
$payload = @{ANALYTICS_PASSWORD=(Get-ConfigurationValue 'ANALYTICS_PASSWORD');MYSQL_ROOT_PASSWORD=(Get-ConfigurationValue 'MYSQL_ROOT_PASSWORD')} | ConvertTo-Json -Compress
Assert-DockerIdentity | Out-Null
$payload | & docker @script:ComposePrefix exec -T api python /bootstrap/setup_readonly_views.py
if ($LASTEXITCODE -ne 0) { throw 'Safe analytics view setup failed.' }
& $python (Join-Path $script:ProjectRoot 'infra/bootstrap_dify.py') --env-file (Join-Path $script:ProjectRoot '.env')
if ($LASTEXITCODE -ne 0) { throw 'Independent Dify bootstrap failed; inspect only the new workspace.' }
# Models and service secrets are injected at creation time; refresh new consumers.
Invoke-Compose up -d --no-build --pull never api ai analytics worker
Write-Host 'New Dify bootstrap completed; private keys remain in platform/.env.'
