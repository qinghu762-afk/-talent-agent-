param([Parameter(Mandatory = $true)][string]$Archive, [Parameter(Mandatory = $true)][string]$ExpectedSha256)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Docker
$restoreEngineId = Get-DockerIdentity
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
if ($ExpectedSha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Supply the trusted 64-character archive SHA256.' }
if ((Get-Sha256 -Path $archivePath) -ne $ExpectedSha256) { throw 'Archive SHA256 mismatch.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stage = Assert-WorkspacePath (Join-Path $script:ProjectRoot "backups/restore-$stamp")
New-Item -ItemType Directory -Force -Path (Split-Path $stage) | Out-Null
Expand-VerifiedZip -Archive $archivePath -Destination $stage
$manifest = Get-Content -LiteralPath (Join-Path $stage 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1) { throw 'Unsupported backup manifest.' }
foreach ($name in @('database.dump', 'config.env', 'originals.zip')) {
    $expected = $manifest.files.PSObject.Properties[$name].Value
    if ((Get-Sha256 -Path (Join-Path $stage $name)) -ne $expected) { throw "Backup member SHA256 mismatch: $name" }
}
$originals = Join-Path $stage 'originals'
Expand-VerifiedZip -Archive (Join-Path $stage 'originals.zip') -Destination $originals
if (!(Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath (Join-Path $stage 'config.env') -Destination '.env' }
$running = @(Get-RunningServices)
$paused = @($running | Where-Object { $_ -in @('web', 'api', 'worker', 'beat') })
$completed = $false
try {
    if ($paused.Count -gt 0) { Invoke-Docker compose stop -t 960 @paused }
    Invoke-Docker compose up -d --wait --wait-timeout 600 --no-build --pull never postgres redis etcd minio milvus ollama mineru
    Invoke-Docker compose exec -T postgres sh -c 'until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do sleep 1; done'
    $postgres = (& docker compose ps -q postgres).Trim()
    Invoke-Docker cp (Join-Path $stage 'database.dump') "${postgres}:/tmp/talent-restore.dump"
    Invoke-Docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction --exit-on-error /tmp/talent-restore.dump'
    Invoke-Docker compose exec -T postgres rm -f /tmp/talent-restore.dump
    $data = Assert-WorkspacePath (Join-Path $script:ProjectRoot 'data')
    if (Test-Path -LiteralPath $data) { Move-Item -LiteralPath $data -Destination ($data + '.before-' + $stamp) }
    Move-Item -LiteralPath $originals -Destination $data
    # Queue messages may point at the database state that was replaced.
    Invoke-Docker compose exec -T redis redis-cli FLUSHDB
    Invoke-Docker compose run --rm --no-deps api python -m talent.cli reindex
    $completed = $true
    Write-Host 'Database and originals restored; derived index rebuild queued. Wait for indexing to complete before matching. Old data remains in data.before-* for manual recovery.'
} finally {
    if ($completed) {
        Invoke-Docker compose up -d --no-build --pull never api worker beat web
        Save-DockerIdentity -ExpectedEngineId $restoreEngineId
    }
    elseif ($paused.Count -gt 0) {
        Write-Warning 'Restore failed. Application remains stopped to prevent writes to a partial restore. Inspect backup and database before starting.'
    }
}
