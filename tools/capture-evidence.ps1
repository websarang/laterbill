param(
    [string]$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$htmlPath = Join-Path $repoRoot "docs\evidence.html"
$outputDir = Join-Path $repoRoot "docs\assets\evidence"
$profileDir = Join-Path $env:TEMP ("laterbill-edge-profile-{0}" -f [guid]::NewGuid().ToString("N"))

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $Edge)) {
    throw "Microsoft Edge not found: $Edge"
}

$baseUri = ([System.Uri]$htmlPath).AbsoluteUri
foreach ($number in 1..5) {
    $pngPath = Join-Path $outputDir ("evidence-{0}.png" -f $number)
    $arguments = @(
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--window-size=1536,1024",
        "--user-data-dir=$profileDir",
        "--screenshot=$pngPath",
        "$baseUri`?slide=$number"
    )
    $process = Start-Process -FilePath $Edge -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $pngPath)) {
        throw "Screenshot failed for slide $number"
    }
}

Write-Output "Captured 5 evidence PNG files in $outputDir"
