# CHM Documentation Search Tool

A CLI tool for searching and navigating CHM (Compiled HTML Help) documentation files. Designed for large SDK documentation like Crestron SIMPL# Pro (~55,000 documents).

## Requirements

- Python 3.6+
- `chmlib` (install via Homebrew: `brew install chmlib`)

## Quick Start

```bash
# First run will extract CHM and build search index (takes ~1 minute)
./chm search "HttpClient"

# Search for a class and see its full API chain
./chm api TCPServer SocketStatusChange
```

## Commands Reference

### Search Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `search <query>` | `s` | Full-text search across all documentation |
| `title <query>` | `t` | Search document titles only (faster, more precise) |

```bash
# Full-text search
./chm search "HTTP request"

# Title search - better for finding specific classes/methods
./chm title "HttpClient"
./chm title "TCPServer"

# Limit results
./chm search "Button" --limit 50
```

### API Exploration Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `class <name>` | `c` | Show class with all members (constructors, properties, methods, events) |
| `inspect <type>` | `i` | Detailed view of a type with all referenced types |
| `traverse <type>` | `tr` | Follow the type tree recursively |
| `api <class> [member]` | `a` | Follow API chains (event → handler → parameters) |

```bash
# See all members of a class
./chm class HttpClient

# Inspect a type to see its signature, parameters, and references
./chm inspect "LoadEventHandler"

# Follow an event handler chain to understand the full API flow
./chm api ClwDimswex LoadStateChange

# Traverse a type tree with custom depth
./chm traverse LoadEventHandler --depth 3
```

### Code Example Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `examples [namespace]` | `ex` | List documents with code examples |
| `example <type>` | `eg` | Get code example from a document |
| `examples-summary` | `exs` | Show count of examples by namespace |

```bash
# List all documents with examples in a namespace
./chm examples "Crestron.SimplSharpPro.Lighting"

# Get a specific code example
./chm example "Din1Dim4 Class"

# See which namespaces have examples
./chm examples-summary
```

### Navigation Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `namespaces` | `ns` | List all namespaces |
| `browse <namespace>` | `b` | Browse contents of a namespace |
| `show <path>` | `r` | Display a specific document |
| `toc` | - | Show table of contents |

```bash
# List all namespaces
./chm namespaces

# Browse a specific namespace
./chm browse "Crestron.SimplSharp.CrestronSockets"

# Read a specific document by path
./chm show html/68dfb061-478b-7a9a-6362-5f957ce70b3a.htm
```

## Recommended Workflows

### 1. Finding a Class and Understanding Its API

```bash
# Step 1: Search for the class
./chm title "TCPServer"

# Step 2: See all members of the class
./chm class TCPServer

# Step 3: Inspect a specific event/method
./chm inspect "TCPServer.SocketStatusChange Event"
```

### 2. Understanding Event Handler Flows

When working with events, use the `api` command to see the complete chain:

```bash
./chm api ClwDimswex LoadStateChange
```

Output shows the full flow:
```
ClwDimswex Class
  └─> LoadStateChange Event
    └─> LoadEventHandler Delegate
        Signature: public delegate void LoadEventHandler(LightingBase, LoadEventArgs)
      └─> LightingBase Class (param: lightingObject)
      └─> LoadEventArgs Class (param: args)
          Properties: EventId, Index, Load
```

### 3. Following Property Return Types

The `api` command also works with properties and methods:

```bash
# See what type a property returns and its members
./chm api LoadEventArgs Load
```

Output:
```
LoadEventArgs Class
  └─> Load Property
      Signature: public LightLoad Load { get; }
    └─> LightLoad Class
        Properties: DeviceLoadIsOn, Number, Parent, Type, ...
```

### 4. Looking Up Constant Fields

```bash
# Find constant values and their documentation
./chm api LoadEventIds LevelChangeEventId
./chm inspect "LoadEventIds.LevelChangeEventId"
```

Output:
```
LoadEventIds.LevelChangeEventId Field
  Signature: public const int LevelChangeEventId = 7
  Description: The level of the load changed.
```

### 5. Exploring a Namespace

```bash
# List available namespaces
./chm namespaces

# Browse contents
./chm browse "Crestron.SimplSharp.Net.Http" --limit 100
```

### 6. Deep Type Inspection

Use `traverse` to recursively explore type relationships:

```bash
./chm traverse "LoadEventHandler" --depth 3
```

### 7. Reading Full Documentation

```bash
# Get the path from search/inspect results, then read
./chm show html/e6dae853-e52a-aea1-01e7-aa7dd979a343.htm
```

### 8. Finding Code Examples

The SDK contains ~1000+ code examples. Use these commands to find implementation guidance:

```bash
# See which namespaces have examples
./chm examples-summary

# List examples in a specific namespace
./chm examples "Crestron.SimplSharpPro.Lighting"

# Get the example code for a class
./chm example "Din1Dim4 Class"
```

When inspecting a type, the tool will indicate if it has an example:
```
*** This document has a CODE EXAMPLE ***
    Use: ./chm example "Din1Dim4 Class"
```

Example output shows actual C# implementation code:
```csharp
// Register the device within the constructor or InitializeSystem function
public ControlSystem() : base()
{
    myDin1Dim4 = new Din1Dim4(0x89, this);
    myDin1Dim4.OverrideEventHandler += new OverrideHandler(OverrideEventHandler);
    myDin1Dim4.OnlineStatusChange += new OnlineStatusChangeEventHandler(OnlineStatusChangeCallback);
    // ...
}
```

## JSON Output

All commands support `--json` flag for programmatic access:

```bash
./chm api ClwDimswex LoadStateChange --json
./chm inspect LoadEventArgs --json
./chm class HttpClient --json
```

Example JSON output for `api` command:
```json
{
  "start_class": "ClwDimswex",
  "member": "LoadStateChange",
  "chain": [
    {
      "level": 0,
      "type": "class",
      "title": "ClwDimswex Class",
      "path": "html/f3f05a02-64c2-3197-2e48-5aa8ca9670b5.htm",
      "namespace": "Crestron.SimplSharpPro.Lighting"
    },
    {
      "level": 1,
      "type": "event",
      "title": "ISwitch.LoadStateChange Event",
      "signature": "event LoadEventHandler LoadStateChange",
      "description": "Event triggered when information from a load is received."
    },
    {
      "level": 2,
      "type": "delegate",
      "title": "LoadEventHandler Delegate",
      "signature": "public delegate void LoadEventHandler(LightingBase, LoadEventArgs)"
    },
    {
      "level": 3,
      "type": "eventargs",
      "title": "LoadEventArgs Class",
      "param_name": "args",
      "properties": [
        {"name": "EventId", "description": "Property to describe what changed on the load."},
        {"name": "Index", "description": "Index into scene collections..."},
        {"name": "Load", "description": "Property to return which load triggered the event."}
      ]
    }
  ]
}
```

## Common Patterns in SIMPL# Pro SDK

### Event Handlers

Events follow this pattern:
- **Event** (e.g., `LoadStateChange`) → returns a **Delegate** type
- **Delegate** (e.g., `LoadEventHandler`) → defines parameters
- **Parameters** typically include:
  - The device/object that triggered the event
  - An **EventArgs** class with event details

```bash
# To understand any event, use:
./chm api <ClassName> <EventName>
```

### Namespaces

Key namespaces:
- `Crestron.SimplSharp` - Core classes
- `Crestron.SimplSharp.CrestronSockets` - TCP/UDP networking
- `Crestron.SimplSharp.Net.Http` - HTTP client
- `Crestron.SimplSharpPro` - Pro device classes
- `Crestron.SimplSharpPro.DeviceSupport` - Base classes and interfaces
- `Crestron.SimplSharpPro.Lighting` - Lighting control devices
- `Crestron.SimplSharpPro.UI` - User interface devices

### Inheritance

Many classes inherit from base classes. When a member isn't found on a class directly, the tool searches parent classes/interfaces. Use `inspect` to see the full type hierarchy.

## Tips for Effective Searching

1. **Use title search for classes/types**: `./chm title "ClassName"` is faster and more precise than full-text search

2. **Use `api` for events**: The `api` command automatically follows the handler chain, saving multiple lookups

3. **Check inherited members**: If a member isn't on a class directly, it's likely inherited. The `api` command handles this automatically

4. **Use JSON for complex queries**: When you need to process results programmatically, use `--json`

5. **Inspect return types**: When a method returns a custom type, use `inspect` on that type to understand it

6. **Path references**: All commands that show paths can be fed to `./chm show <path>` for full documentation

7. **Look for examples first**: When implementing a device, check if it has a code example with `./chm example "ClassName"` - examples show real-world usage patterns

8. **Browse examples by namespace**: Use `./chm examples "Crestron.SimplSharpPro.Lighting"` to find similar device implementations

## Cache Location

Extracted CHM files and search index are cached at:
```
~/.cache/chm-search/chm_<hash>/
```

To rebuild the index:
```bash
./chm rebuild
```
