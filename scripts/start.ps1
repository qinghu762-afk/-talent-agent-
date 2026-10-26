param([switch]$Build)
. (Join-Path $PSScriptRoot 'common.ps1')
Initialize-Configuration
Assert-Docker
$startupEngineId = Assert-DockerIdentity
New-Item -ItemType Directory -Force -Path (Join-Path $script:ProjectRoot 'data') | Out-Null
& (Join-Path $PSScriptRoot 'check.ps1') -PrerequisitesOnly
if ($Build) { Invoke-Docker compose build }
Invoke-Docker compose up -d --no-build --pull never
$webPort = Get-ConfigurationValue WEB_PORT '8080'
Write-Host "Startup requested. Readiness may take several minutes. Open http://127.0.0.1:$webPort after check.ps1 passes."
& (Join-Path $PSScriptRoot 'check.ps1')
Save-DockerIdentity -ExpectedEngineId $startupEngineId
