param([Parameter(Mandatory=$true)][string]$BackupDirectory,[switch]$UseBackupConfiguration,[switch]$DryRun)
. (Join-Path $PSScriptRoot 'common.ps1')
$source = Assert-WorkspacePath (Join-Path $script:ProjectRoot $BackupDirectory)
if ($DryRun) { Write-Host 'PLAN: verify manifest, hashes, engine and stopped services; restore only empty new-platform volumes; refuse populated data; no deletion.'; return }
Assert-DockerIdentity | Out-Null
$manifestFile = Join-Path $source 'manifest.json'
$manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or $manifest.project -ne 'talent-platform' -or $manifest.engine_id -ne (Assert-DockerIdentity)) { throw 'Backup identity or schema mismatch.' }
if (@(Invoke-Compose ps --services --status running).Count) { throw 'Stop the new talent-platform services before restoring.' }
$expected = Get-NewVolumes
$toolImage = Get-LockedImage 'postgres:16.10-bookworm'
if (@($manifest.volumes).Count -ne $expected.Count) { throw 'Backup volume set mismatch.' }
foreach ($property in $manifest.files.PSObject.Properties) {
 if ($property.Name -notmatch '^(config\.env|talent-platform_[a-z-]+\.tar\.gz)$') { throw 'Unsafe backup manifest filename.' }
 $file = Assert-WorkspacePath (Join-Path $source $property.Name)
 if ((Get-Sha256 $file) -ne $property.Value) { throw 'Backup checksum mismatch.' }
}
foreach ($volume in $expected) {
 if ($volume -notin $manifest.volumes -or !($manifest.files.PSObject.Properties.Name -contains "$volume.tar.gz")) { throw 'Backup missing required volume.' }
 Assert-NewVolume $volume
 Invoke-GuardedDocker run --rm --pull never --network none --mount "type=volume,source=$volume,target=/snapshot,readonly" $toolImage sh -c 'test -z "$(ls -A /snapshot)"'
 # Validate archive members in Python before allowing extraction.
 Invoke-GuardedDocker run --rm --pull never --network none --mount "type=bind,source=$source,target=/backup,readonly" --mount "type=bind,source=$script:ProjectRoot/infra/validate_archive.py,target=/validate.py,readonly" talent-platform-api:0.2.0 python /validate.py "/backup/$volume.tar.gz"
}
$config = Join-Path $script:ProjectRoot '.env'
if (!$UseBackupConfiguration -and (Test-Path -LiteralPath $config) -and (Get-Sha256 $config) -ne (Get-Sha256 (Join-Path $source 'config.env'))) { throw 'Configuration differs. Explicitly use -UseBackupConfiguration to restore the matching private config.' }
foreach ($volume in $expected) {
 Invoke-GuardedDocker run --rm --pull never --network none --mount "type=volume,source=$volume,target=/snapshot" --mount "type=bind,source=$source,target=/backup,readonly" $toolImage tar -xzf "/backup/$volume.tar.gz" -C /snapshot
}
Copy-Item -LiteralPath (Join-Path $source 'config.env') -Destination $config -Force
Protect-PrivatePath $config
Write-Host 'Restored all new-platform volumes and matching config. Run start.ps1 when ready.'
