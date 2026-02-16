
<#
.SYNOPSIS
    Build chm-docs MCP server as a Windows installer.
.DESCRIPTION
    Creates a standalone .exe installer using PyInstaller and Inno Setup.
    Requires: Python 3.13, 7-Zip, Inno Setup (optional, for .exe installer).
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$Version = (Get-Content VERSION).Trim()
$ChmFile = "SIMPLSharpPro.chm"
$AppName = "chm-docs"

Write-Host "=== Building $AppName v$Version (Windows) ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------
Write-Host "--- Checking prerequisites ---"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install Python 3.13 from https://python.org"
    exit 1
}

$pyVersion = python --version 2>&1
Write-Host "Using: $pyVersion"

if (-not (Test-Path $ChmFile)) {
    Write-Error "$ChmFile not found in $ScriptDir`nCopy it from: C:\Program Files (x86)\Crestron\Cresdb\Help\SIMPLSharpPro.chm"
    exit 1
}

# Create/reuse venv
$Venv = Join-Path $ScriptDir ".venv"
if (-not (Test-Path $Venv)) {
    Write-Host "Creating virtual environment..."
    python -m venv $Venv
}
& "$Venv\Scripts\Activate.ps1"

# Install build dependencies
$needInstall = $false
try { python -c "import mcp" 2>$null } catch { $needInstall = $true }
try { python -c "import PyInstaller" 2>$null } catch { $needInstall = $true }
if ($needInstall) {
    Write-Host "Installing build dependencies..."
    pip install --quiet mcp pyinstaller
}

Write-Host "All prerequisites met."
Write-Host ""

# ---------------------------------------------------------------------------
# 2. PyInstaller build (--onedir)
# ---------------------------------------------------------------------------
Write-Host "--- Running PyInstaller ---"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name $AppName `
    --add-data "chm_search.py;." `
    --hidden-import mcp `
    --hidden-import mcp.server `
    --hidden-import mcp.server.fastmcp `
    --hidden-import mcp.server.stdio `
    --hidden-import anyio `
    --hidden-import anyio._backends `
    --hidden-import anyio._backends._asyncio `
    --hidden-import httpx `
    --hidden-import httpx._transports `
    --hidden-import pydantic `
    --hidden-import pydantic.deprecated `
    --hidden-import pydantic.deprecated.decorator `
    --hidden-import starlette `
    --hidden-import sse_starlette `
    --hidden-import uvicorn `
    chm_mcp_server.py

Write-Host "PyInstaller build complete."
Write-Host ""

# ---------------------------------------------------------------------------
# 3. Stage payload
# ---------------------------------------------------------------------------
Write-Host "--- Staging payload ---"

$Payload = Join-Path $ScriptDir "win-payload"
if (Test-Path $Payload) { Remove-Item -Recurse -Force $Payload }

# App bundle
$AppDir = Join-Path $Payload $AppName
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
Copy-Item -Recurse "dist\$AppName\*" $AppDir

# CHM data file
Copy-Item $ChmFile $AppDir

Write-Host "Payload staged at $Payload"
Write-Host ""

# ---------------------------------------------------------------------------
# 4. Create installer (Inno Setup) or zip fallback
# ---------------------------------------------------------------------------
$InnoCompiler = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($InnoCompiler) {
    Write-Host "--- Building installer with Inno Setup ---"

    $IssContent = @"
[Setup]
AppName=CHM Docs MCP Server
AppVersion=$Version
AppPublisher=Crestron Tools
DefaultDirName={localappdata}\$AppName
DefaultGroupName=$AppName
OutputDir=$ScriptDir
OutputBaseFilename=$AppName-$Version-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "$Payload\$AppName\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Uninstall CHM Docs"; Filename: "{uninstallexe}"
"@

    $IssPath = Join-Path $ScriptDir "chm-docs.iss"
    Set-Content -Path $IssPath -Value $IssContent
    & $InnoCompiler $IssPath
    Remove-Item $IssPath
} else {
    Write-Host "--- Inno Setup not found, creating zip ---"
    $ZipName = "$AppName-$Version-win.zip"
    Compress-Archive -Path "$Payload\$AppName\*" -DestinationPath $ZipName -Force
    Write-Host "Created: $ZipName"
}

Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Install location: %LOCALAPPDATA%\$AppName"
Write-Host ""
Write-Host "Claude Code .mcp.json config:"
Write-Host @"
{
  "mcpServers": {
    "chm-docs": {
      "command": "%LOCALAPPDATA%\\chm-docs\\chm-docs.exe"
    }
  }
}
"@
