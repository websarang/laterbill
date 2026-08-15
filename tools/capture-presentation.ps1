param(
    [string]$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$htmlPath = Join-Path $repoRoot "docs\presentation\index.html"
$outputDir = Join-Path $repoRoot "docs\assets\presentation"
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $Edge)) {
    throw "Microsoft Edge not found: $Edge"
}
if (-not (Test-Path -LiteralPath $htmlPath)) {
    throw "Presentation not found: $htmlPath"
}

$baseUri = ([System.Uri]$htmlPath).AbsoluteUri
foreach ($number in 1..10) {
    $profileDir = Join-Path $env:TEMP ("laterbill-presentation-edge-{0}" -f [guid]::NewGuid().ToString("N"))
    $pngPath = Join-Path $outputDir ("slide-{0:D2}.png" -f $number)
    $captureStartedAt = [DateTime]::UtcNow
    $arguments = @(
        "--headless=new",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--no-sandbox",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=2000",
        "--hide-scrollbars",
        "--window-size=1920,1080",
        "--force-device-scale-factor=1",
        "--user-data-dir=$profileDir",
        "--screenshot=$pngPath",
        "$baseUri`?slide=$number&capture=1"
    )
    $process = Start-Process -FilePath $Edge -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (
        (-not (Test-Path -LiteralPath $pngPath) -or
        (Get-Item -LiteralPath $pngPath).LastWriteTimeUtc -lt $captureStartedAt) -and
        [DateTime]::UtcNow -lt $deadline
    ) {
        Start-Sleep -Milliseconds 250
    }
    if (
        -not (Test-Path -LiteralPath $pngPath) -or
        (Get-Item -LiteralPath $pngPath).LastWriteTimeUtc -lt $captureStartedAt
    ) {
        throw "Screenshot failed for slide $number"
    }
}

Write-Output "Captured 10 presentation PNG files in $outputDir"
