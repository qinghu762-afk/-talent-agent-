$ErrorActionPreference = 'Stop'
$common = Join-Path $PSScriptRoot 'common.ps1'
if (!(Test-Path -LiteralPath $common)) { throw 'Safety helpers must exist.' }
. $common
$sample = New-Secret -Base64Url
$decoded = [Convert]::FromBase64String($sample.Replace('-','+').Replace('_','/')+'=')
if ($decoded.Length -ne 32) { throw 'Dify Agent base64url generation must encode exactly 32 bytes.' }
$script:observed = New-Object Collections.Generic.List[string]
function docker {
 $script:observed.Add(($args -join ' '))
 $global:LASTEXITCODE = 0
 if ($args[0] -eq 'info') { return 'FAKE-ENGINE' }
 throw 'Dry-run attempted a Docker action.'
}
$refused = $false
try { Assert-WorkspacePath (Join-Path $script:ProjectRoot '../data') | Out-Null } catch { $refused = $true }
if (!$refused) { throw 'Path escape was accepted.' }
$refused = $false
try { Assert-DockerIdentity | Out-Null } catch { $refused = $true }
if (!$refused) { throw 'Mismatched Docker identity was accepted.' }
& (Join-Path $PSScriptRoot 'start.ps1') -DryRun
& (Join-Path $PSScriptRoot 'check.ps1') -DryRun
& (Join-Path $PSScriptRoot 'backup.ps1') -DryRun
$refused = $false
try { & (Join-Path $PSScriptRoot 'restore.ps1') -BackupDirectory '../data' -DryRun } catch { $refused = $true }
if (!$refused) { throw 'Restore path escape accepted.' }
if (@($script:observed | Where-Object { $_ -notlike 'info*' }).Count) { throw 'Dry run made a Docker call.' }
Write-Host 'PASS: root confinement, engine mismatch, no Docker mutation in dry-run, restore escape rejection.'
