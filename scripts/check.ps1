param([switch]$PrerequisitesOnly)
. (Join-Path $PSScriptRoot 'common.ps1')
if (!(Test-Path -LiteralPath '.env')) { throw 'Run scripts/start.ps1 or scripts/prepare-offline.ps1 first.' }
Assert-Docker
Assert-DockerIdentity | Out-Null
$system = Get-CimInstance Win32_ComputerSystem
$memoryGb = [math]::Round($system.TotalPhysicalMemory / 1GB, 1)
Write-Host "Host RAM: $memoryGb GB; recommend 32 GB and Docker allocation >= 16 GB. MinerU uses CPU; Ollama uses host GPU."
$disk = Get-PSDrive -Name ([IO.Path]::GetPathRoot($script:ProjectRoot).TrimEnd(':\'))
Write-Host "Project drive free: $([math]::Round($disk.Free / 1GB, 1)) GB; reserve at least 50 GB plus original files/backups."
$models = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10
$names = @($models.models | ForEach-Object { $_.name })
foreach ($requested in @((Get-ConfigurationValue CHAT_MODEL 'qwen3:4b'), (Get-ConfigurationValue EMBEDDING_MODEL 'bge-m3'))) {
    if (!($names -contains $requested) -and !($names -contains ($requested + ':latest'))) { throw "Missing local Ollama model: $requested. Run prepare-offline.ps1 while online." }
}
Invoke-Docker compose config --quiet
if ($PrerequisitesOnly) { return }
Invoke-Docker compose ps
$port = Get-ConfigurationValue WEB_PORT '8080'
$deadline = [DateTime]::UtcNow.AddMinutes(5)
do {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health" -TimeoutSec 10
        Write-Host ($health | ConvertTo-Json -Depth 8)
        $body = @{ username = Get-ConfigurationValue ADMIN_USERNAME 'admin'; password = Get-ConfigurationValue ADMIN_PASSWORD } | ConvertTo-Json
        $login = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$port/api/v1/auth/login" -ContentType 'application/json' -Body $body -SessionVariable session -TimeoutSec 15
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/system" -WebSession $session -TimeoutSec 30
        Write-Host ($status | ConvertTo-Json -Depth 8)
        $unready = @($status.services.PSObject.Properties | Where-Object { !$_.Value.ok } | ForEach-Object { $_.Name })
        if ($unready.Count -gt 0) { throw "Dependencies not ready: $($unready -join ', ')" }
        Write-Host 'Authenticated application readiness succeeded. Run acceptance fixtures separately for model quality and recovery checks.'
        return
    } catch {
        if ([DateTime]::UtcNow -ge $deadline) { throw "Application readiness failed: $($_.Exception.Message). Inspect docker compose logs --tail 100." }
        Start-Sleep -Seconds 5
    }
} while ($true)
