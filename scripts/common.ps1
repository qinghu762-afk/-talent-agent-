Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $script:ProjectRoot

function Invoke-Docker {
    # A Parameter attribute enables common parameters: -d would bind Debug instead
    # of reaching Compose. Keep this a simple function and forward literal arguments.
    $dockerArguments = @($args)
    & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) { throw "docker command failed (exit $LASTEXITCODE): $($dockerArguments[0])" }
}
function New-Secret {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}
function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stream = [IO.File]::OpenRead([IO.Path]::GetFullPath($Path))
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '') }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
function Ensure-LocalImages {
    param([string[]]$Images)
    foreach ($image in $Images) {
        & docker image inspect $image *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Using cached pinned image: $image"
        } else {
            Invoke-Docker pull $image
        }
    }
}
function Initialize-Configuration {
    $path = Join-Path $script:ProjectRoot '.env'
    if (!(Test-Path -LiteralPath $path)) {
        $template = [IO.File]::ReadAllText((Join-Path $script:ProjectRoot '.env.example'))
        foreach ($name in @('POSTGRES_PASSWORD', 'JWT_SECRET', 'ADMIN_PASSWORD', 'MINIO_ROOT_PASSWORD')) {
            $template = [regex]::Replace($template, "(?m)^$name=.*$", "$name=$(New-Secret)")
        }
        [IO.File]::WriteAllText($path, $template, (New-Object Text.UTF8Encoding $false))
        Write-Host 'Created .env with unique credentials. Keep this file private; admin password is ADMIN_PASSWORD.'
    }
    if ((Get-Content -LiteralPath $path -Raw) -match 'REPLACE_WITH_') {
        throw 'Replace all placeholders in .env before starting.'
    }
}
function Get-ConfigurationValue {
    param([string]$Name, [string]$Default = '')
    $match = Get-Content -LiteralPath (Join-Path $script:ProjectRoot '.env') | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
    if ($null -eq $match) { return $Default }
    return $match.Substring($Name.Length + 1).Trim()
}
function Get-DockerIdentity {
    $engineId = (& docker info --format '{{.ID}}').Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($engineId)) { throw 'Cannot verify Docker engine identity.' }
    return $engineId
}
function Assert-DockerIdentity {
    $engineId = Get-DockerIdentity
    $marker = Join-Path $script:ProjectRoot '.docker-runtime.json'
    if (Test-Path -LiteralPath $marker) {
        $expected = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ($expected.schema -ne 1 -or $expected.engine_id -ne $engineId) {
            throw 'Docker engine differs from the verified deployment. Refusing startup before creating containers or volumes. Check the original Docker data disk; do not reset Docker.'
        }
    } else {
        $originals = Join-Path $script:ProjectRoot 'data/originals'
        if ((Test-Path -LiteralPath $originals) -and @(Get-ChildItem -LiteralPath $originals -File -Recurse | Select-Object -First 1).Count -gt 0) {
            throw 'Existing resume originals have no verified Docker identity. Refusing a potentially empty database. Restore and verify the original environment first.'
        }
    }
    return $engineId
}
function Save-DockerIdentity {
    param([Parameter(Mandatory = $true)][string]$ExpectedEngineId)
    $actual = Get-DockerIdentity
    if ($actual -ne $ExpectedEngineId) { throw 'Docker engine changed during the operation; verified identity was not updated.' }
    $state = @{schema = 1; engine_id = $actual; verified_utc = [DateTime]::UtcNow.ToString('o')}
    [IO.File]::WriteAllText((Join-Path $script:ProjectRoot '.docker-runtime.json'), ($state | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
}
function Assert-Docker {
    if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop with Linux containers first.' }
    Invoke-Docker info --format '{{.OSType}}'
    Invoke-Docker compose version
}
function Get-RunningServices {
    return @(Invoke-Docker compose ps --services --status running)
}
function Assert-WorkspacePath {
    param([string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    if (!$resolved.StartsWith($script:ProjectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Operation outside project refused: $resolved"
    }
    return $resolved
}
function Expand-VerifiedZip {
    param([string]$Archive, [string]$Destination)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destinationFull = [IO.Path]::GetFullPath($Destination)
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $destinationFull $entry.FullName))
            if (!$target.StartsWith($destinationFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Archive contains a path outside its destination.'
            }
            if ($entry.FullName.Contains(':') -or $entry.FullName.Contains('\')) { throw 'Archive contains unsafe paths.' }
            # UNIX symbolic links and special files are never restored.
            $kind = ($entry.ExternalAttributes -shr 16) -band 0xF000
            if ($kind -ne 0 -and $kind -ne 0x8000 -and $kind -ne 0x4000) { throw 'Archive contains a special file.' }
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
}
function Compress-PortableDirectory {
    param([Parameter(Mandatory = $true)][string]$Source, [Parameter(Mandatory = $true)][string]$Archive)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $sourceRoot = [IO.Path]::GetFullPath($Source).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $entries = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force)
    if (@($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0) {
        throw 'Backup source contains a symbolic link or reparse point.'
    }
    $zip = [IO.Compression.ZipFile]::Open($Archive, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in ($entries | Where-Object { !$_.PSIsContainer })) {
            $full = [IO.Path]::GetFullPath($file.FullName)
            if (!$full.StartsWith($sourceRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Backup source escaped its directory.' }
            $relative = $full.Substring($sourceRoot.Length).Replace('\', '/')
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $full, $relative) | Out-Null
        }
    } finally { $zip.Dispose() }
}
