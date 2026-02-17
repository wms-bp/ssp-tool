
<#
.SYNOPSIS
    Build chm-docs MCP server as a Windows installer.
.DESCRIPTION
    Creates a standalone .exe installer using PyInstaller and Inno Setup.
    Requires: Python 3.13, Inno Setup 6, C compiler (MSVC).
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$Version = (Get-Content VERSION).Trim()
$ChmFile = "SIMPLSharpPro.chm"
$CrestronChmPath = "C:\Program Files (x86)\Crestron\Cresdb\Help\SIMPLSharpPro.chm"
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

# CHM file not required in repo — the server finds it at the Crestron install path on first run.
# But warn if it's not available anywhere (user may be building on a non-Crestron machine).
if (-not (Test-Path $ChmFile) -and -not (Test-Path $CrestronChmPath)) {
    Write-Host "WARNING: $ChmFile not found in repo or at Crestron install path." -ForegroundColor Yellow
    Write-Host "The server will look for it at:" -ForegroundColor Yellow
    Write-Host "  $CrestronChmPath" -ForegroundColor Yellow
    Write-Host "The cache will be built on first run if the CHM is available." -ForegroundColor Yellow
    Write-Host ""
}

# Create/reuse venv
$Venv = Join-Path $ScriptDir ".venv"
if (-not (Test-Path $Venv)) {
    Write-Host "Creating virtual environment..."
    python -m venv $Venv
}
& "$Venv\Scripts\Activate.ps1"

# Install build dependencies
python -c "import mcp" 2>$null
$mcpMissing = $LASTEXITCODE -ne 0
python -c "import PyInstaller" 2>$null
$pyiMissing = $LASTEXITCODE -ne 0
if ($mcpMissing -or $pyiMissing) {
    Write-Host "Installing build dependencies..."
    pip install --quiet mcp pyinstaller setuptools
}

Write-Host "All prerequisites met."
Write-Host ""

# ---------------------------------------------------------------------------
# 2. Build _chmlib C extension (vendored CHMLib)
# ---------------------------------------------------------------------------
Write-Host "--- Building _chmlib C extension ---"

python setup.py build_ext --inplace
Write-Host "C extension built."
Write-Host ""

# ---------------------------------------------------------------------------
# 3. PyInstaller build (--onedir)
# ---------------------------------------------------------------------------
Write-Host "--- Running PyInstaller ---"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name $AppName `
    --add-data "chm_search.py;." `
    --add-data "chmextract.py;." `
    --add-data "VERSION;." `
    --hidden-import _chmlib `
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
# 4. Stage payload
# ---------------------------------------------------------------------------
Write-Host "--- Staging payload ---"

$Payload = Join-Path $ScriptDir "win-payload"
if (Test-Path $Payload) { Remove-Item -Recurse -Force $Payload }

# App bundle (CHM not included — server reads from Crestron install path at runtime)
$AppDir = Join-Path $Payload $AppName
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
Copy-Item -Recurse "dist\$AppName\*" $AppDir
Copy-Item "configure-mcp.ps1" $AppDir

Write-Host "Payload staged at $Payload"
Write-Host ""

# ---------------------------------------------------------------------------
# 5. Create installer (Inno Setup)
# ---------------------------------------------------------------------------
$InnoCompiler = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $InnoCompiler) {
    Write-Error "Inno Setup 6 not found. Install from https://jrsoftware.org/isinfo.php`nor: winget install JRSoftware.InnoSetup"
    exit 1
}

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
ChangesEnvironment=yes

[Files]
Source: "$Payload\$AppName\*"; DestDir: "{app}"; Flags: recursesubdirs

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Icons]
Name: "{group}\Uninstall CHM Docs"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""& '{app}\configure-mcp.ps1'"""; StatusMsg: "Configuring Claude Code MCP..."; Flags: runhidden

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
"@

$IssPath = Join-Path $ScriptDir "chm-docs.iss"
Set-Content -Path $IssPath -Value $IssContent
& $InnoCompiler $IssPath
Remove-Item $IssPath

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
