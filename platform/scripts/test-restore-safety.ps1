$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$global:TalentRestoreTestEngine = (Get-Content -LiteralPath (Join-Path $script:RepositoryRoot '.docker-runtime.json') -Raw | ConvertFrom-Json).engine_id
$global:TalentRestoreTestCalls = New-Object Collections.Generic.List[string]
function docker {
 $global:TalentRestoreTestCalls.Add(($args -join ' '))
 $global:LASTEXITCODE = 0
 if ($args[0] -eq 'info') { return $global:TalentRestoreTestEngine }
 if ($args[0] -eq 'compose' -and $args -contains 'ps') { return }
 if ($args[0] -eq 'volume' -and $args[1] -eq 'inspect') { return 'talent-platform' }
 if ($args[0] -eq 'run' -and $args -contains 'sh') { $global:LASTEXITCODE = 1; return }
 throw 'Unexpected Docker action in mocked restore test.'
}
$relative = '.test-infra-safety-' + [Guid]::NewGuid().ToString('N')
$folder = Assert-WorkspacePath (Join-Path $script:ProjectRoot $relative)
New-Item -ItemType Directory -Path $folder | Out-Null
try {
 $files = @{}
 foreach ($volume in (Get-NewVolumes)) {
  $path = Join-Path $folder ($volume + '.tar.gz')
  [IO.File]::WriteAllText($path,'dummy archive; extraction must never be reached')
  $files[$volume+'.tar.gz'] = Get-Sha256 $path
 }
 $config = Join-Path $folder 'config.env'
 [IO.File]::WriteAllText($config,'TEST_ONLY=true')
 $files['config.env'] = Get-Sha256 $config
 $manifest = @{schema=1;project='talent-platform';engine_id=$global:TalentRestoreTestEngine;volumes=(Get-NewVolumes);files=$files}
 [IO.File]::WriteAllText((Join-Path $folder 'manifest.json'),($manifest | ConvertTo-Json -Depth 5))
 $rejected = $false
 try { & (Join-Path $PSScriptRoot 'restore.ps1') -BackupDirectory $relative -UseBackupConfiguration } catch {
  if ($_.Exception.Message -notmatch 'Guarded Docker operation failed') { throw }
  $rejected = $true
 }
 if (!$rejected) { throw 'Populated volume restore was accepted.' }
 if (@($global:TalentRestoreTestCalls | Where-Object { $_ -match 'tar -x|stop|remove|prune' }).Count) { throw 'Unsafe Docker operation was attempted.' }
 Write-Host 'PASS: populated target is rejected before extraction or configuration changes; no real Docker calls.'
} finally {
 foreach ($file in Get-ChildItem -LiteralPath $folder -File) { Remove-Item -LiteralPath $file.FullName }
 Remove-Item -LiteralPath $folder
 Remove-Variable -Name TalentRestoreTestEngine,TalentRestoreTestCalls -Scope Global
}
