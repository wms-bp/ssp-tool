# CHM Documentation Search Tool

Search and navigate Crestron SIMPL# Pro SDK documentation (~55,000 documents). Works as both a CLI tool and an MCP server for Claude Code.

The installed binary (`chm-docs`) runs in two modes:
- **No arguments** — starts as an MCP server (stdio) for Claude Code
- **With a command** — runs as a CLI tool (e.g. `chm-docs search "HttpClient"`)

## Getting Started

### 1. Build and install

Both platforms produce a standalone binary — no Python needed at runtime.

**macOS:**
```bash
brew install chmlib        # extraction tool
bash build.sh
sudo installer -pkg chm-docs-*.pkg -target /
# Or double-click the .pkg file
```

**Windows (PowerShell):**
```powershell
winget install 7zip.7zip              # extraction tool
winget install JRSoftware.InnoSetup   # installer builder
.\build.ps1
# Run chm-docs-X.Y.Z-setup.exe
```

Build requires Python 3.13.

### 2. Add the CHM file

The CHM file is not included in the repo or installer. Copy `SIMPLSharpPro.chm` to the app's data directory:

**Windows:** The tool checks these locations in order:
1. `%LOCALAPPDATA%\chm-docs\SIMPLSharpPro.chm`
2. `C:\Program Files (x86)\Crestron\Cresdb\Help\SIMPLSharpPro.chm` (auto-detected if Crestron DB is installed)

**macOS:** Copy it to:
```
/usr/local/share/chm-docs/SIMPLSharpPro.chm
```

If the CHM can't be found, the tool prints an error showing exactly where it looked and where to place the file.

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

Start Claude Code in this project directory — the 9 `chm-docs` tools appear automatically.

### 4. First run

The search index cache is built automatically on first run (~1 minute). After that, all queries are instant.

## Install locations

**macOS (.pkg):**
- `/usr/local/lib/chm-docs/` — application bundle
- `/usr/local/share/chm-docs/` — place `SIMPLSharpPro.chm` here
- `/usr/local/bin/chm-docs` — launcher

**Windows (installer):**
- `%LOCALAPPDATA%\chm-docs\` — application bundle (also accepts CHM here)

To upgrade, install the new package over the previous one.

## MCP Tools

When running as an MCP server, these tools are available to Claude Code:

| Tool | Description |
|------|-------------|
| `search` | Full-text keyword search across all docs |
| `search_title` | Title-only search for precise type/member lookup |
| `inspect` | Detailed view of any type — signature, params, enum values, references |
| `get_class_info` | Class overview with members grouped by category |
| `api_chain` | Trace event/property chains: class → delegate → eventargs → properties |
| `browse_namespace` | List all types within a namespace |
| `list_namespaces` | List all SDK namespaces with item counts |
| `get_example` | Get C# code example for a type |
| `show_document` | Read full document text by path |

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
| `api <class> [member]` | `a` | Follow API chains (event → handler → parameters) |

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

### Following Property Return Types

```bash
chm-docs api LoadEventArgs Load
```

Output:
```
LoadEventArgs Class
  └─> Load Property
      Signature: public LightLoad Load { get; }
    └─> LightLoad Class
        Properties: DeviceLoadIsOn, Number, Parent, Type, ...
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

When inspecting a type, the tool indicates if an example exists:
```
*** This document has a CODE EXAMPLE ***
    Use the get_example tool with "Din1Dim4 Class"
```

## Common Patterns in SIMPL# Pro SDK

### Event Handlers

Events follow this pattern:
- **Event** (e.g., `LoadStateChange`) → returns a **Delegate** type
- **Delegate** (e.g., `LoadEventHandler`) → defines parameters
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

## Cache

Extracted CHM files and search index are cached at:
```
~/.cache/chm-search/chm_<hash>/
```

To rebuild the index:
```bash
chm-docs rebuild
```
