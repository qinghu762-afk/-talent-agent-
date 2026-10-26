. (Join-Path $PSScriptRoot 'common.ps1')
$script:imageCalls = [Collections.Generic.List[string]]::new()
function docker {
    $command = $args -join ' '
    $script:imageCalls.Add($command)
    $global:LASTEXITCODE = if ($command -eq 'image inspect cached:1') { 0 } elseif ($command -eq 'pull missing:1') { 0 } else { 1 }
}
Ensure-LocalImages @('cached:1', 'missing:1')
if ('pull cached:1' -in $script:imageCalls) { throw 'Cached pinned image was unnecessarily pulled.' }
if ('pull missing:1' -notin $script:imageCalls) { throw 'Missing pinned image was not pulled.' }
$refused = $false
try { Ensure-LocalImages @('unavailable:1') } catch { $refused = $true }
if (!$refused) { throw 'Failed download was treated as prepared.' }
Write-Host 'Image preparation checks passed: cached reuse, missing download, failure propagation.'
