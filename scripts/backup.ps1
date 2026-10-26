param([string]$OutputDirectory = 'backups')
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Docker
Assert-DockerIdentity | Out-Null
$output = Assert-WorkspacePath (Join-Path $script:ProjectRoot $OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stage = Assert-WorkspacePath (Join-Path $output "stage-$stamp")
New-Item -ItemType Directory -Path $stage | Out-Null
$running = @(Get-RunningServices)
$paused = @($running | Where-Object { $_ -in @('web', 'api', 'worker', 'beat') })
try {
    if ($paused.Count -gt 0) { Invoke-Docker compose stop -t 960 @paused }
    Invoke-Docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file=/tmp/talent-backup.dump'
    $postgres = (& docker compose ps -q postgres).Trim()
    Invoke-Docker cp "${postgres}:/tmp/talent-backup.dump" (Join-Path $stage 'database.dump')
    Invoke-Docker compose exec -T postgres rm -f /tmp/talent-backup.dump
    Copy-Item -LiteralPath '.env' -Destination (Join-Path $stage 'config.env')
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (!(Test-Path -LiteralPath 'data')) { New-Item -ItemType Directory -Path 'data' | Out-Null }
    Compress-PortableDirectory -Source (Join-Path $script:ProjectRoot 'data') -Archive (Join-Path $stage 'originals.zip')
    $files = @{}
    foreach ($name in @('database.dump', 'config.env', 'originals.zip')) { $files[$name] = Get-Sha256 -Path (Join-Path $stage $name) }
    $manifest = @{ schema = 1; created_utc = [DateTime]::UtcNow.ToString('o'); files = $files; index_restore = 'python -m talent.cli reindex' }
    [IO.File]::WriteAllText((Join-Path $stage 'manifest.json'), ($manifest | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
    $archive = Join-Path $output "talent-$stamp.zip"
    Compress-PortableDirectory -Source $stage -Archive $archive
    Get-Sha256 -Path $archive | Set-Content -LiteralPath ($archive + '.sha256') -Encoding ascii
    $checkedStage = Assert-WorkspacePath $stage
    Remove-Item -LiteralPath $checkedStage -Recurse -Force
    Write-Host "Backup saved: $archive. Contains resume originals and credentials; store with restricted access."
} finally {
    if ($paused.Count -gt 0) { Invoke-Docker compose start @paused }
}
