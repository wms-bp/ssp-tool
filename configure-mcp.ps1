# Configure Claude Code global MCP settings for chm-docs
# Run automatically by the installer

$configDir = Join-Path $env:USERPROFILE ".claude"
$configFile = Join-Path $configDir "mcp.json"
$exePath = Join-Path $env:LOCALAPPDATA "chm-docs\chm-docs.exe"

# Ensure .claude directory exists
if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

# Read existing config or start fresh
if (Test-Path $configFile) {
    try {
        $config = Get-Content $configFile -Raw | ConvertFrom-Json
    } catch {
        # Malformed JSON — back up and start fresh
        Copy-Item $configFile "$configFile.bak" -Force
        $config = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
    }
} else {
    $config = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
}

# Ensure mcpServers key exists
if (-not $config.mcpServers) {
    $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{}) -Force
}

# Add or update chm-docs entry
$chmDocs = [PSCustomObject]@{ command = $exePath }
if ($config.mcpServers.'chm-docs') {
    $config.mcpServers.'chm-docs' = $chmDocs
} else {
    $config.mcpServers | Add-Member -NotePropertyName "chm-docs" -NotePropertyValue $chmDocs -Force
}

# Write config
$config | ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8
