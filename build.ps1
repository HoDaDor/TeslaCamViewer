param(
    [switch]$Force,
    [switch]$Installer,
    [switch]$Zip
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command pyside6-deploy -ErrorAction SilentlyContinue)) {
    throw "pyside6-deploy was not found on PATH. Activate your project environment first."
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$specPath = Join-Path $projectRoot "pysidedeploy.spec"
$specText = Get-Content -Path $specPath -Raw
$buildDir = Join-Path $projectRoot "build"
$generatedSpec = Join-Path $buildDir "pysidedeploy.generated.spec"
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
Copy-Item -Path $specPath -Destination $generatedSpec -Force

$args = @("qtTeslaCam.py", "--config-file", $generatedSpec)
if ($Force) {
    $args += "--force"
}

Write-Host "Running pyside6-deploy for TeslaCamViewer..."
try {
    & pyside6-deploy @args
}
finally {
    Set-Content -Path $specPath -Value $specText -NoNewline
}

if ($LASTEXITCODE -ne 0) {
    throw "pyside6-deploy failed with exit code $LASTEXITCODE."
}

$expectedExe = Join-Path $projectRoot "dist\TeslaCamViewer.dist\qtTeslaCam.exe"
if (-not (Test-Path $expectedExe)) {
    throw "pyside6-deploy finished, but the expected executable was not found: $expectedExe"
}

$distDir = Split-Path -Parent $expectedExe
$noticeDir = Join-Path $distDir "notices"
New-Item -ItemType Directory -Path $noticeDir -Force | Out-Null
Copy-Item -Path "LICENSE", "THIRD_PARTY_NOTICES.md" -Destination $distDir -Force
Copy-Item -Path "docs\PYSIDE6-LICENSING.md" -Destination $noticeDir -Force
Copy-Item -Path "licenses\*" -Destination $noticeDir -Force

Write-Host "Build complete. Output directory: $(Join-Path $projectRoot 'dist')"

if ($Installer) {
    $versionMatch = Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    $env:TESLACAMVIEWER_VERSION = if ($versionMatch) { $versionMatch.Matches[0].Groups[1].Value } else { "dev" }
    $installerScript = Join-Path $projectRoot "packaging\windows\TeslaCamViewer.iss"
    $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue

    if (-not $iscc) {
        throw "Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 6 to create the installer."
    }

    & $iscc.Source $installerScript

    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE."
    }

    Write-Host "Installer complete. Output directory: $(Join-Path $projectRoot 'dist\installer')"
}

if ($Zip) {
    $versionMatch = Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    $version = if ($versionMatch) { $versionMatch.Matches[0].Groups[1].Value } else { "dev" }
    $zipPath = Join-Path $projectRoot "dist\TeslaCamViewer-$version-windows-x64.zip"

    if (Test-Path $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }

    Compress-Archive -Path $distDir -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Host "Package complete. Zip file: $zipPath"
}
