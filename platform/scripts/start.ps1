param([switch]$Build,[switch]$DryRun,[switch]$SkipBootstrap)
. (Join-Path $PSScriptRoot 'common.ps1')
if ($DryRun) {
 Write-Host 'PLAN: validate preserved Docker identity; create only platform/.env; build own images if requested; up talent-platform only; initialize new Dify and safe SQL views; check readiness.'
 return
}
Assert-DockerIdentity | Out-Null
Initialize-Configuration
if ($Build) { Invoke-Compose build }
Invoke-Compose up -d --no-build --pull never
if (!$SkipBootstrap) { & (Join-Path $PSScriptRoot 'bootstrap.ps1') }
& (Join-Path $PSScriptRoot 'check.ps1')
Write-Host 'Platform: http://127.0.0.1:18080   Independent Dify: http://127.0.0.1:18081'
