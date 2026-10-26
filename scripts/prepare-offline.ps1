param([ValidateSet('huggingface', 'modelscope')][string]$ModelSource = 'huggingface', [switch]$ExportImages)
. (Join-Path $PSScriptRoot 'common.ps1')
Initialize-Configuration
Assert-Docker
Assert-DockerIdentity | Out-Null
if (!(Get-Command ollama -ErrorAction SilentlyContinue)) { throw 'Install and run Windows native Ollama first; this script does not install host software.' }
foreach ($model in @((Get-ConfigurationValue CHAT_MODEL 'qwen3:4b'), (Get-ConfigurationValue EMBEDDING_MODEL 'bge-m3'))) {
    & ollama pull $model
    if ($LASTEXITCODE -ne 0) { throw "Ollama model preparation failed: $model" }
}
$serviceImages = @(& docker compose --profile prepare config --format json | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Compose images.' }
$imagesToPrepare = @($serviceImages[0].services.PSObject.Properties |
    Where-Object { !$_.Value.PSObject.Properties['build'] } |
    ForEach-Object { $_.Value.image } | Sort-Object -Unique)
Ensure-LocalImages $imagesToPrepare
Invoke-Docker compose build
$previousSource = $env:MINERU_DOWNLOAD_SOURCE
try {
    $env:MINERU_DOWNLOAD_SOURCE = $ModelSource
    Invoke-Docker compose --profile prepare run --rm --no-deps prepare-models
} finally { $env:MINERU_DOWNLOAD_SOURCE = $previousSource }
if ($ExportImages) {
    New-Item -ItemType Directory -Force -Path 'backups' | Out-Null
    $images = @(& docker compose --profile prepare config --images | Sort-Object -Unique)
    Invoke-Docker image save -o (Join-Path $script:ProjectRoot 'backups/images.tar') @images
    Write-Host ('images.tar SHA256: ' + (Get-Sha256 -Path (Join-Path $script:ProjectRoot 'backups/images.tar')))
}
Write-Host 'Preparation complete. Runtime start uses cached images and local models; it never pulls them automatically.'
Write-Host 'Ollama weights and mineru-models Docker volume must also be transferred for a different offline machine; images.tar contains images only.'
