. (Join-Path $PSScriptRoot 'common.ps1')
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
$base = Assert-WorkspacePath (Join-Path $script:ProjectRoot ('.tmp/ops-' + [Guid]::NewGuid().ToString('N')))
New-Item -ItemType Directory -Force -Path $base | Out-Null
$failures = 0
function Test-Assertion {
    param([bool]$Condition, [string]$Message)
    if (!$Condition) { $script:failures++; Write-Warning $Message }
}
try {
    function docker { $script:capturedDockerArguments = @($args); $global:LASTEXITCODE = 0 }
    try {
        Invoke-Docker compose up -d --no-build
        Test-Assertion ($script:capturedDockerArguments -contains '-d') 'Docker detached flag was swallowed by PowerShell common parameters.'
    } finally { Remove-Item Function:docker }
    Test-Assertion ((New-Secret) -match '^[a-f0-9]{64}$') 'Cryptographic secret has unexpected encoding.'
    Test-Assertion ((New-Secret) -ne (New-Secret)) 'Secrets unexpectedly repeat.'
    $refused = $false
    try { Assert-WorkspacePath (Join-Path (Split-Path $script:ProjectRoot) 'sibling/file') | Out-Null } catch { $refused = $true }
    Test-Assertion $refused 'Sibling path was not refused.'
    $safe = Join-Path $base 'safe.zip'
    $zip = [IO.Compression.ZipFile]::Open($safe, [IO.Compression.ZipArchiveMode]::Create)
    try {
        $entry = $zip.CreateEntry('folder/original.txt')
        $writer = New-Object IO.StreamWriter($entry.Open())
        try { $writer.Write('original evidence') } finally { $writer.Dispose() }
    } finally { $zip.Dispose() }
    Expand-VerifiedZip -Archive $safe -Destination (Join-Path $base 'safe')
    Test-Assertion ((Get-Content -LiteralPath (Join-Path $base 'safe/folder/original.txt') -Raw) -eq 'original evidence') 'Safe archive did not round-trip.'
    $hashFile = Join-Path $base 'hash.txt'
    [IO.File]::WriteAllText($hashFile, 'abc', (New-Object Text.UTF8Encoding $false))
    Test-Assertion ((Get-Sha256 -Path $hashFile) -eq 'BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD') 'SHA256 differs from the known abc digest.'
    $portable = Join-Path $base 'portable.zip'
    Compress-PortableDirectory -Source (Join-Path $base 'safe') -Archive $portable
    Expand-VerifiedZip -Archive $portable -Destination (Join-Path $base 'portable')
    Test-Assertion ((Get-Content -LiteralPath (Join-Path $base 'portable/folder/original.txt') -Raw) -eq 'original evidence') 'Portable backup archive did not round-trip.'
    $unsafe = Join-Path $base 'unsafe.zip'
    $zip = [IO.Compression.ZipFile]::Open($unsafe, [IO.Compression.ZipArchiveMode]::Create)
    try { $null = $zip.CreateEntry('../escape.txt') } finally { $zip.Dispose() }
    $refused = $false
    try { Expand-VerifiedZip -Archive $unsafe -Destination (Join-Path $base 'unsafe') } catch { $refused = $true }
    Test-Assertion $refused 'Zip traversal was not refused.'
    Test-Assertion (!(Test-Path -LiteralPath (Join-Path $base 'escape.txt'))) 'Archive wrote outside destination.'
    $parseCount = 0
    foreach ($file in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1')) {
        $tokens = $null
        $errors = $null
        [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors) | Out-Null
        Test-Assertion ($errors.Count -eq 0) "PowerShell syntax failed: $($file.Name)"
        $parseCount++
    }
    if ($failures -gt 0) { throw "$failures operations checks failed." }
    Write-Host "Operations checks passed: unique secrets, path boundary, ZIP round-trip, ZIP traversal rejection, $parseCount script syntax checks."
} finally {
    $checked = Assert-WorkspacePath $base
    Remove-Item -LiteralPath $checked -Recurse -Force
}
