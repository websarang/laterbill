param(
    [string]$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$htmlPath = Join-Path $repoRoot "docs\evidence.html"
$outputDir = Join-Path $repoRoot "docs\assets\evidence"
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $Edge)) {
    throw "Microsoft Edge not found: $Edge"
}

$baseUri = ([System.Uri]$htmlPath).AbsoluteUri
foreach ($number in 1..5) {
    $profileDir = Join-Path $env:TEMP ("laterbill-evidence-edge-{0}" -f [guid]::NewGuid().ToString("N"))
    $pngPath = Join-Path $outputDir ("evidence-{0}.png" -f $number)
    $captureStartedAt = [DateTime]::UtcNow
    $arguments = @(
        "--headless=new",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--no-sandbox",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=2000",
        "--hide-scrollbars",
        "--window-size=1536,1024",
        "--force-device-scale-factor=1",
        "--user-data-dir=$profileDir",
        "--screenshot=$pngPath",
        "$baseUri`?slide=$number"
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

Write-Output "Captured 5 evidence PNG files in $outputDir"
