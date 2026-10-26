Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $script:ProjectRoot '..'))
if ([IO.Path]::GetFileName($script:ProjectRoot) -ne 'platform' -or !(Test-Path -LiteralPath (Join-Path $script:ProjectRoot 'backend/talent_platform/api.py'))) { throw 'Expected the new platform root with application sources.' }
$script:ComposePrefix = @('compose','--project-name','talent-platform','--project-directory',$script:ProjectRoot,'--env-file',(Join-Path $script:ProjectRoot '.env'),'-f',(Join-Path $script:ProjectRoot 'compose.yaml'))
function Assert-WorkspacePath {
 param([Parameter(Mandatory=$true)][string]$Path)
 $full = [IO.Path]::GetFullPath($Path)
 $prefix = $script:ProjectRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
 if ($full -ne $script:ProjectRoot -and !$full.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Path must remain inside the new platform root.' }
 $cursor = $full
 while ($cursor -and $cursor.Length -ge $script:ProjectRoot.Length) {
  if (Test-Path -LiteralPath $cursor) {
   if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are not permitted in deployment paths.' }
  }
  $cursor = [IO.Path]::GetDirectoryName($cursor)
 }
 return $full
}
function New-Secret {
 param([switch]$Base64Url)
 $buffer = New-Object byte[] 32
 $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
 try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
 if ($Base64Url) { return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+','-').Replace('/','_') }
 return ([BitConverter]::ToString($buffer)).Replace('-','').ToLowerInvariant()
}
function Initialize-Configuration {
 $target = Assert-WorkspacePath (Join-Path $script:ProjectRoot '.env')
 if (!(Test-Path -LiteralPath $target)) {
  $template = [IO.File]::ReadAllText((Join-Path $script:ProjectRoot '.env.example'))
  $template = [regex]::Replace($template, '(?m)^([A-Z_]+)=GENERATE\r?$', { param($m) $name=$m.Groups[1].Value; $name + '=' + (New-Secret -Base64Url:($name -eq 'DIFY_AGENT_SECRET')) })
  [IO.File]::WriteAllText($target,$template,(New-Object Text.UTF8Encoding $false))
  # Restrict locally generated credentials to the current Windows identity.
  if ($env:OS -eq 'Windows_NT') {
   $acl = New-Object Security.AccessControl.FileSecurity
   $acl.SetAccessRuleProtection($true,$false)
   $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
   $acl.SetOwner($identity)
   $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($identity,'FullControl','Allow')))
   Set-Acl -LiteralPath $target -AclObject $acl
  }
  Write-Host 'Created platform/.env with new private credentials.'
 }
 if ([IO.File]::ReadAllText($target) -match '(?m)=GENERATE\r?$') { throw 'Ungenerated configuration secret.' }
}
function Get-ConfigurationValue {
 param([string]$Name,[string]$Default='')
 $file = Join-Path $script:ProjectRoot '.env'
 if (!(Test-Path -LiteralPath $file)) { return $Default }
 $line = @(Get-Content -LiteralPath $file | Where-Object { $_.StartsWith($Name+'=') })
 if (!$line.Count) { return $Default }
 return $line[-1].Substring($Name.Length+1).Trim()
}
function Assert-DockerIdentity {
 $marker = Join-Path $script:RepositoryRoot '.docker-runtime.json'
 if (!(Test-Path -LiteralPath $marker)) { throw 'Verified parent Docker identity marker is missing; refusing all Docker actions.' }
 $expected = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
 $actual = (& docker info --format '{{.ID}}').Trim()
 if ($LASTEXITCODE -ne 0 -or $expected.schema -ne 1 -or !$actual -or $expected.engine_id -ne $actual) { throw 'Docker engine identity does not match the preserved parent marker. No resources were changed.' }
 return $actual
}
function Invoke-Compose {
 Assert-DockerIdentity | Out-Null
 & docker @script:ComposePrefix @args
 if ($LASTEXITCODE -ne 0) { throw "New platform Compose operation failed (exit $LASTEXITCODE)." }
}
function Invoke-GuardedDocker {
 Assert-DockerIdentity | Out-Null
 & docker @args
 if ($LASTEXITCODE -ne 0) { throw "Guarded Docker operation failed (exit $LASTEXITCODE)." }
}
function Get-NewVolumes {
 $names = @('postgres','mysql','redis','etcd','minio','milvus','app-data','dify-redis','dify-storage','dify-sandbox-deps','dify-sandbox-conf','dify-plugins','dify-agent-home','dify-agent-workspace')
 return @($names | ForEach-Object { 'talent-platform_' + $_ })
}
function Assert-NewVolume {
 param([string]$Name)
 if ($Name -notin (Get-NewVolumes)) { throw 'Volume is outside the fixed new-platform allowlist.' }
 $label = Invoke-GuardedDocker volume inspect --format '{{index .Labels "com.docker.compose.project"}}' $Name
 if ($label.Trim() -ne 'talent-platform') { throw 'Volume project identity mismatch.' }
}
function Get-Sha256 { param([string]$Path) return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Get-LockedImage {
 param([Parameter(Mandatory=$true)][string]$Tag)
 $lock = Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'infra/images.lock.json') -Raw | ConvertFrom-Json
 $property = $lock.images.PSObject.Properties[$Tag]
 if (!$property -or $property.Value -notmatch '@sha256:[a-f0-9]{64}$') { throw 'A verified immutable tool image is required.' }
 return $property.Value
}
function Protect-PrivatePath {
 param([Parameter(Mandatory=$true)][string]$Path)
 $target = Assert-WorkspacePath $Path
 if ($env:OS -eq 'Windows_NT') {
  $isDirectory = (Get-Item -LiteralPath $target).PSIsContainer
  # Build only owner and discretionary access entries. Copying Get-Acl's
  # complete descriptor can request SACL privileges ordinary users lack.
  if ($isDirectory) { $acl = New-Object Security.AccessControl.DirectorySecurity }
  else { $acl = New-Object Security.AccessControl.FileSecurity }
  $acl.SetAccessRuleProtection($true,$false)
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
  $acl.SetOwner($identity)
  if ($isDirectory) {
   $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
  } else { $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity,'FullControl','Allow') }
  $acl.AddAccessRule($rule)
  Set-Acl -LiteralPath $target -AclObject $acl
 }
}
