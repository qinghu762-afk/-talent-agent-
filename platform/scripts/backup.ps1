param([string]$OutputDirectory='backups',[switch]$DryRun)
. (Join-Path $PSScriptRoot 'common.ps1')
$output = Assert-WorkspacePath (Join-Path $script:ProjectRoot $OutputDirectory)
if ($DryRun) { Write-Host 'PLAN: stop only currently running talent-platform services; cold snapshot 14 allowlisted new volumes; hash manifest and private config; restart previous services. Old models and projects are excluded.'; return }
Assert-DockerIdentity | Out-Null
$volumes = Get-NewVolumes
$toolImage = Get-LockedImage 'postgres:16.10-bookworm'
foreach ($volume in $volumes) { Assert-NewVolume $volume }
$running = @(Invoke-Compose ps --services --status running)
$destination = Assert-WorkspacePath (Join-Path $output ('platform-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
if (Test-Path -LiteralPath $destination) { throw 'Backup destination already exists.' }
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Protect-PrivatePath $destination
try {
 if ($running.Count) { Invoke-Compose stop -t 120 @running }
 $hashes = @{}
 foreach ($volume in $volumes) {
  Invoke-GuardedDocker run --rm --pull never --network none --mount "type=volume,source=$volume,target=/snapshot,readonly" --mount "type=bind,source=$destination,target=/backup" $toolImage tar -czf "/backup/$volume.tar.gz" -C /snapshot .
  $hashes["$volume.tar.gz"] = Get-Sha256 (Join-Path $destination "$volume.tar.gz")
 }
 Copy-Item -LiteralPath (Join-Path $script:ProjectRoot '.env') -Destination (Join-Path $destination 'config.env')
 $hashes['config.env'] = Get-Sha256 (Join-Path $destination 'config.env')
 $manifest = @{schema=1;project='talent-platform';engine_id=(Assert-DockerIdentity);created_utc=[DateTime]::UtcNow.ToString('o');volumes=$volumes;files=$hashes}
 [IO.File]::WriteAllText((Join-Path $destination 'manifest.json'),($manifest|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding $false))
 Write-Host "Cold backup saved: $destination. Contains private credentials and originals."
} finally {
 if ($running.Count) { Invoke-Compose start @running }
}
