# Crestron CHM Documentation Search Tool

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?logo=buymeacoffee)](https://buymeacoffee.com/connectedavs)

Navigate the Crestron SIMPL# Pro SDK and SIMPL Windows device documentation so you don't have to. Turns sprawling CHM files into searchable, structured knowledge -- as a CLI tool or an MCP server for Claude Code.

Supports two CHM sources:
- **SIMPLSharpPro.chm** — C# SDK API documentation (classes, methods, events, properties)
- **SIMPL_Windows.chm** — Device signal documentation (digital/analog/serial I/O, parameters, slot structure)

The installed binary (`chm-docs`) runs in two modes:
- **No arguments** — starts as an MCP server (stdio) for Claude Code
- **With a command** — runs as a CLI tool (e.g. `chm-docs search "HttpClient"`)

## Quick Start

### 1. Install

Download the latest release for your platform from [Releases](../../releases):

- **macOS:** `chm-docs-X.Y.Z.pkg` — double-click or `sudo installer -pkg chm-docs-*.pkg -target /`
- **Windows:** `chm-docs-X.Y.Z-setup.exe` — run the installer

### 2. Add the CHM files

The CHM files are not included in the release. Copy them to the app's data directory:

**macOS:**
```bash
sudo cp SIMPLSharpPro.chm /usr/local/share/chm-docs/
sudo cp SIMPL_Windows.chm /usr/local/share/chm-docs/   # optional
```

**Windows:** The tool checks these locations in order:
1. `%LOCALAPPDATA%\chm-docs\SIMPLSharpPro.chm`
2. `C:\Program Files (x86)\Crestron\Cresdb\Help\SIMPLSharpPro.chm` (auto-detected if Crestron DB is installed)

For SIMPL Windows:
1. `%LOCALAPPDATA%\chm-docs\SIMPL_Windows.chm`
2. `C:\Program Files (x86)\Crestron\Simpl\SIMPL_Windows.chm`

If a CHM can't be found, the tool prints an error showing exactly where it looked. The S#Pro CHM is required; the SIMPL Windows CHM is optional but enables signal descriptions and cross-referencing.

### 3. Configure Claude Code (MCP)

The included `.mcp.json` is configured for macOS. On Windows, update it:

```json
{
  "mcpServers": {
    "chm-docs": {
      "command": "%LOCALAPPDATA%\\chm-docs\\chm-docs.exe"
    }
  }
}
```

Start Claude Code in this project directory — the `chm-docs` tools appear automatically.

### 4. Verify

```bash
chm-docs --version
```

### 5. First run

The search index cache is built automatically on first run (~1 minute per CHM). After that, all queries are instant.

## MCP Tools

When running as an MCP server, these tools are available to Claude Code:

### SIMPL# Pro (default)

| Tool | Description |
|------|-------------|
| `search` | Full-text keyword search across all docs |
| `search_title` | Title-only search for precise type/member lookup |
| `inspect` | Detailed view of any type — signature, params, enum values, references |
| `get_class_info` | Class overview with members grouped by category |
| `api_chain` | Trace event/property chains: class -> delegate -> eventargs -> properties |
| `browse_namespace` | List all types within a namespace |
| `list_namespaces` | List all SDK namespaces with item counts |
| `get_example` | Get C# code example for a type |
| `show_document` | Read full document text by path |

All tools above accept `chm='simpl'` to query SIMPL Windows instead.

### SIMPL Windows

| Tool | Description |
|------|-------------|
| `search_signals` | Search signal definitions by name or description, optionally filtered by type |
| `get_device_signals` | Get all signals for a device grouped by slot with full descriptions |

### Cross-Referencing

| Tool | Description |
|------|-------------|
| `cross_reference` | Given a device name (SIMPL or S#Pro format), show all signals with S#Pro type mappings |
| `cross_reference_member` | Traverse from an S#Pro class member to its SIMPL Windows signal with full description |

**Signal type mapping:**

| SIMPL Windows | SIMPL# Pro |
|---|---|
| Digital input/output | BooleanInput/BooleanOutput |
| Analog input/output | UShortInput/UShortOutput |
| Serial input/output | StringInput/StringOutput |
| Parameter | Compile-time config |

**Cross-reference workflow:**
```
# Start from S#Pro, get SIMPL signal descriptions
cross_reference_member("ClwDimFlvExP", "DimmerRemoteButtonSettings")
cross_reference_member("ClwDimFlvExP", "LevelIn")

# Start from SIMPL, get S#Pro type mappings
cross_reference("CLW-DIMFLVEX-P")
get_device_signals("CLW-DIMFLVEX-P")

# Both directions accept either naming convention
cross_reference("ClwDimuEx")  # S#Pro name → finds CLW-DIMUEX-P
```

## CLI Commands

The same binary works as a CLI tool when given a command. On macOS you can also use the `./chm` wrapper script (requires Python).

Examples below use `chm-docs` (installed binary). Replace with `./chm` if using the Python wrapper.

### Search

| Command | Alias | Description |
|---------|-------|-------------|
| `search <query>` | `s` | Full-text search across all documentation |
| `title <query>` | `t` | Search document titles only (faster, more precise) |

```bash
chm-docs search "HTTP request"
chm-docs title "HttpClient"
chm-docs search "Button" --limit 50
```

### API Exploration

| Command | Alias | Description |
|---------|-------|-------------|
| `class <name>` | `c` | Show class with all members (constructors, properties, methods, events) |
| `enum <name>` | `e` | Show enumeration values |
| `inspect <type>` | `i` | Detailed view of a type with all referenced types |
| `traverse <type>` | `tr` | Follow the type tree recursively |
| `api <class> [member]` | `a` | Follow API chains (event -> handler -> parameters) |

```bash
chm-docs class HttpClient
chm-docs enum SocketStatus
chm-docs inspect "LoadEventHandler"
chm-docs api ClwDimswex LoadStateChange
chm-docs traverse LoadEventHandler --depth 3
```

### Code Examples

| Command | Alias | Description |
|---------|-------|-------------|
| `examples [namespace]` | `ex` | List documents with code examples |
| `example <type>` | `eg` | Get code example from a document |
| `examples-summary` | `exs` | Show count of examples by namespace |

```bash
chm-docs examples "Crestron.SimplSharpPro.Lighting"
chm-docs example "Din1Dim4 Class"
chm-docs examples-summary
```

### Navigation

| Command | Alias | Description |
|---------|-------|-------------|
| `namespaces` | `ns` | List all namespaces |
| `browse <namespace>` | `b` | Browse contents of a namespace |
| `show <path>` | `r` | Display a specific document |
| `toc` | - | Show table of contents |

```bash
chm-docs namespaces
chm-docs browse "Crestron.SimplSharp.CrestronSockets"
chm-docs show html/68dfb061-478b-7a9a-6362-5f957ce70b3a.htm
```

All commands support `--json` for machine-readable output.

## Recommended Workflows

### Finding a Class and Understanding Its API

```bash
# Step 1: Search for the class
chm-docs title "TCPServer"

# Step 2: See all members
chm-docs class TCPServer

# Step 3: Inspect a specific event/method
chm-docs inspect "TCPServer.SocketStatusChange Event"
```

### Understanding Event Handler Flows

Use the `api` command to see the complete chain:

```bash
chm-docs api ClwDimswex LoadStateChange
```

Output:
```
ClwDimswex Class
  └─> LoadStateChange Event
    └─> LoadEventHandler Delegate
        Signature: public delegate void LoadEventHandler(LightingBase, LoadEventArgs)
      └─> LightingBase Class (param: lightingObject)
      └─> LoadEventArgs Class (param: args)
          Properties: EventId, Index, Load
```

### Cross-Referencing Signal Descriptions

When the S#Pro docs don't explain a property well enough, get the SIMPL Windows signal description:

```
# Via MCP: cross_reference_member("ClwDimFlvExP", "LevelIn")
# Returns: Level_In [A-In -> UShortInput]: Sets the light level. Valid analog
# values range from 0% (Off) to 100%. This signal should be tied together with
# the Level_Out output...
```

### Looking Up Constants and Enums

```bash
chm-docs inspect "LoadEventIds.LevelChangeEventId"
chm-docs enum SocketStatus
```

### Finding Code Examples

```bash
# See which namespaces have examples
chm-docs examples-summary

# Get example code for a class
chm-docs example "Din1Dim4 Class"
```

## Common Patterns in SIMPL# Pro SDK

### Event Handlers

Events follow this pattern:
- **Event** (e.g., `LoadStateChange`) -> returns a **Delegate** type
- **Delegate** (e.g., `LoadEventHandler`) -> defines parameters
- **Parameters** typically include the device and an **EventArgs** class

```bash
# To understand any event:
chm-docs api <ClassName> <EventName>
```

### Key Namespaces

- `Crestron.SimplSharp` — Core classes
- `Crestron.SimplSharp.CrestronSockets` — TCP/UDP networking
- `Crestron.SimplSharp.Net.Http` — HTTP client
- `Crestron.SimplSharpPro` — Pro device classes
- `Crestron.SimplSharpPro.DeviceSupport` — Base classes and interfaces
- `Crestron.SimplSharpPro.Lighting` — Lighting control devices
- `Crestron.SimplSharpPro.UI` — User interface devices

### Inheritance

Many classes inherit from base classes. When a member isn't found on a class directly, the tool searches parent classes/interfaces. Use `inspect` to see the full type hierarchy.

## Building from Source

Both platforms produce a standalone binary — no Python needed at runtime. Build requires Python 3.13.

**macOS:**
```bash
bash build.sh
sudo installer -pkg chm-docs-*.pkg -target /
```

**Windows (PowerShell):**
```powershell
winget install JRSoftware.InnoSetup   # installer builder
.\build.ps1
# Run chm-docs-X.Y.Z-setup.exe
```

### Install locations

**macOS (.pkg):**
- `/usr/local/lib/chm-docs/` — application bundle
- `/usr/local/share/chm-docs/` — place CHM files here
- `/usr/local/bin/chm-docs` — launcher

**Windows (installer):**
- `%LOCALAPPDATA%\chm-docs\` — application bundle (also accepts CHM files here)

To upgrade, install the new package over the previous one.

## Cache

Extracted CHM files and search index are cached at:
```
~/.cache/chm-search/chm_<hash>/
```

To rebuild the index:
```bash
chm-docs rebuild
```

## Known Issues

- **Windows (ARM):** First-run cache build (extraction + indexing) can take up to 5 minutes. Subsequent launches are instant.
