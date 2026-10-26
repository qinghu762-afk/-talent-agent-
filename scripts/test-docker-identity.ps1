. (Join-Path $PSScriptRoot 'common.ps1')
$savedProjectRoot = $script:ProjectRoot
$testRoot = Assert-WorkspacePath (Join-Path $savedProjectRoot ('.tmp/docker-identity-' + [Guid]::NewGuid().ToString('N')))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$script:fakeEngineId = 'TEST_ENGINE_A'
function docker { $global:LASTEXITCODE = 0; Write-Output $script:fakeEngineId }
try {
    $script:ProjectRoot = $testRoot
    if ((Assert-DockerIdentity) -ne 'TEST_ENGINE_A') { throw 'Fresh project identity was not returned.' }
    Save-DockerIdentity -ExpectedEngineId 'TEST_ENGINE_A'
    $marker = Join-Path $testRoot '.docker-runtime.json'
    $originalMarker = [IO.File]::ReadAllText($marker)
    $script:fakeEngineId = 'TEST_ENGINE_B'
    $refused = $false
    try { Assert-DockerIdentity | Out-Null } catch { $refused = $true }
    if (!$refused) { throw 'Different Docker engine was accepted.' }
    $refused = $false
    try { Save-DockerIdentity -ExpectedEngineId 'TEST_ENGINE_A' } catch { $refused = $true }
    if (!$refused -or [IO.File]::ReadAllText($marker) -ne $originalMarker) { throw 'Engine change overwrote the verified identity.' }
    Remove-Item -LiteralPath $marker
    $originals = Join-Path $testRoot 'data/originals'
    New-Item -ItemType Directory -Path $originals -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $originals 'synthetic.txt'), 'SYNTHETIC')
    $refused = $false
    try { Assert-DockerIdentity | Out-Null } catch { $refused = $true }
    if (!$refused) { throw 'Existing originals without a verified Docker identity were accepted.' }
    Write-Host 'Docker identity checks passed: fresh setup, mismatch rejection, unchanged marker, existing-data guard.'
} finally {
    $script:ProjectRoot = $savedProjectRoot
    Remove-Item Function:docker
    $checkedRoot = Assert-WorkspacePath $testRoot
    Remove-Item -LiteralPath $checkedRoot -Recurse -Force
}
