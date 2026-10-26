param([switch]$DryRun)
. (Join-Path $PSScriptRoot 'common.ps1')
$path = Assert-WorkspacePath (Join-Path $script:ProjectRoot '.env')
$value = Get-ConfigurationValue 'DIFY_AGENT_SECRET'
$decodedLength = 0
try { $decodedLength = [Convert]::FromBase64String($value.Replace('-','+').Replace('_','/') + ('=' * ((4-$value.Length%4)%4))).Length } catch { }
if ($decodedLength -eq 32) { Write-Host 'Dify agent secret already decodes to exactly 32 bytes; unchanged.'; return }
if ($value -notmatch '^[a-f0-9]{64}$') { throw 'Refusing to replace an unrecognized existing agent secret.' }
if ($DryRun) { Write-Host 'PLAN: back up private new-platform configuration; replace only the incompatible generated agent key with 32 random bytes encoded as base64url.'; return }
$content = [IO.File]::ReadAllText($path)
if ([regex]::Matches($content,'(?m)^DIFY_AGENT_SECRET=[^\r\n]*').Count -ne 1) { throw 'Expected exactly one agent secret entry.' }
$backup = Assert-WorkspacePath (Join-Path $script:ProjectRoot ('.env.agent-secret-before-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N')))
Copy-Item -LiteralPath $path -Destination $backup
Protect-PrivatePath $backup
$replacement = 'DIFY_AGENT_SECRET=' + (New-Secret -Base64Url)
$content = [regex]::Replace($content,'(?m)^DIFY_AGENT_SECRET=[^\r\n]*',$replacement)
[IO.File]::WriteAllText($path,$content,(New-Object Text.UTF8Encoding $false))
Protect-PrivatePath $path
Write-Host 'Repaired only the new Dify agent key. A private reversible configuration backup remains beside platform/.env.'
