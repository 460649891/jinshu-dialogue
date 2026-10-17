[CmdletBinding()]
param(
    [string]$Python = '.venv\Scripts\python.exe',
    [string]$OutputDir = 'release'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$version = '0.3.0'
$env:PYTHONUTF8 = '1'

function Get-ProjectPath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $projectRoot $Path))
}

function Assert-BuildPath([string]$Path) {
    $buildRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.build'))
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -ne $buildRoot -and -not $full.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing an unmanaged build path: $full"
    }
    $candidate = $full
    while ($candidate -ne $projectRoot) {
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -LiteralPath $candidate -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing a build path through a junction or symbolic link: $candidate"
            }
        }
        $candidate = [IO.Path]::GetDirectoryName($candidate)
    }
}

$pythonPath = Get-ProjectPath $Python
$outputPath = Get-ProjectPath $OutputDir
$buildPath = Join-Path $projectRoot '.build'
$distPath = Join-Path $buildPath 'dist'
$workPath = Join-Path $buildPath 'work'
$applicationPath = Join-Path $distPath 'JinshuDialogue'
$packager = Join-Path $PSScriptRoot 'package_source.py'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "Python not found: $pythonPath" }
foreach ($path in @($buildPath, $distPath, $workPath, $applicationPath, (Join-Path $workPath 'JinshuDialogue'))) {
    Assert-BuildPath $path
}
if ($outputPath -eq $projectRoot -or $outputPath.StartsWith($buildPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or $outputPath -eq $buildPath) {
    throw 'OutputDir must be a dedicated output folder outside .build, not the project root.'
}

$dependencyCheck = @'
import sys, struct, importlib.metadata as metadata
assert sys.platform == "win32", "Build on Windows"
assert sys.version_info[:2] == (3, 12), "Python 3.12 required"
assert struct.calcsize("P") == 8, "x64 Python required"
expected = {"frida": "17.23.3", "PySide6-Essentials": "6.12.0", "shiboken6": "6.12.0", "PyInstaller": "6.22.3"}
actual = {name: metadata.version(name) for name in expected}
assert actual == expected, (actual, expected)
print("Build dependencies verified.")
'@
$dependencyCheck | & $pythonPath -
if ($LASTEXITCODE -ne 0) { throw 'Build dependency check failed. Install requirements-build.txt first.' }

# No game is started or attached during packaging. PyInstaller only clears its
# own generated cache/output inside the validated project .build directory.
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
Push-Location $projectRoot
try {
    & $pythonPath -m PyInstaller --noconfirm --clean --distpath $distPath --workpath $workPath (Join-Path $projectRoot 'JinshuDialogue.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    if (-not (Test-Path -LiteralPath (Join-Path $applicationPath 'JinshuDialogue.exe') -PathType Leaf)) {
        throw 'PyInstaller did not produce JinshuDialogue.exe.'
    }
    foreach ($name in @('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $applicationPath
    }
    $publicDocs = @('architecture.md', 'development.md', 'compatibility.md', 'releasing.md', 'documentation.md', 'release-notes-template.md')
    $docsDir = Join-Path $applicationPath 'docs'
    New-Item -ItemType Directory -Path $docsDir -Force | Out-Null
    foreach ($name in $publicDocs) {
        Copy-Item -LiteralPath (Join-Path $projectRoot "docs\$name") -Destination $docsDir
    }
    $screenshot = Join-Path $projectRoot 'docs\screenshots\desktop-demo.png'
    if (Test-Path -LiteralPath $screenshot -PathType Leaf) {
        $screenshotDir = Join-Path $applicationPath 'docs\screenshots'
        New-Item -ItemType Directory -Path $screenshotDir -Force | Out-Null
        Copy-Item -LiteralPath $screenshot -Destination $screenshotDir
    }
    & $pythonPath $packager --collect-licenses (Join-Path $applicationPath 'LICENSES')
    if ($LASTEXITCODE -ne 0) { throw 'Offline license collection failed.' }
    $binaryZip = Join-Path $outputPath "JinshuDialogue-$version-windows-x64.zip"
    $sourceZip = Join-Path $outputPath "JinshuDialogue-$version-source.zip"
    & $pythonPath $packager --application-dir $applicationPath --application-output $binaryZip
    if ($LASTEXITCODE -ne 0) { throw 'Application archive failed.' }
    & $pythonPath $packager --output $sourceZip
    if ($LASTEXITCODE -ne 0) { throw 'Source archive failed.' }
    & $pythonPath $packager --checksums $binaryZip $sourceZip --checksums-output (Join-Path $outputPath 'SHA256SUMS')
    if ($LASTEXITCODE -ne 0) { throw 'Checksum generation failed.' }
    Write-Host "Portable archives ready: $outputPath"
} finally {
    Pop-Location
}
