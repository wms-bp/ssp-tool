#!/usr/bin/env python3
"""
MCP Server for CHM Documentation Search Tool

Exposes CHMSearch functionality as MCP tools for use with Claude Code
and other MCP-compatible clients.
"""

import os
import platform
import sys
from pathlib import Path


_CRESTRON_CHM_PATH = r"C:\Program Files (x86)\Crestron\Cresdb\Help\SIMPLSharpPro.chm"

_CHM_NAME = "SIMPLSharpPro.chm"


# Read version from VERSION file (bundled or local) — no heavy imports needed
def _read_version() -> str:
    for base in [getattr(sys, "_MEIPASS", None), Path(__file__).parent]:
        if base:
            p = Path(base) / "VERSION"
            if p.exists():
                return p.read_text().strip()
    return "0.0.0"


__version__ = _read_version()


def _resolve_chm_path() -> str:
    """Resolve the CHM file path using priority order:
    1. CHM_PATH environment variable
    2. PyInstaller bundle (sys._MEIPASS)
    3. Platform install location (macOS: /usr/local/share, Windows: %LOCALAPPDATA%)
    4. Crestron database install (Windows only)
    5. ./SIMPLSharpPro.chm (development fallback)
    """
    candidates = []

    # 1. Environment variable
    env_path = os.environ.get("CHM_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return env_path
        candidates.append(str(p))

    # 2. PyInstaller bundle
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / _CHM_NAME
        if p.exists():
            return str(p)
        candidates.append(str(p))

    # 3. Platform install location
    if platform.system() == "Windows":
        p = Path(os.environ.get("LOCALAPPDATA", "")) / "chm-docs" / _CHM_NAME
    else:
        p = Path("/usr/local/share/chm-docs") / _CHM_NAME
    candidates.append(str(p))
    if p.exists():
        return str(p)

    # 4. Crestron database install (Windows)
    if platform.system() == "Windows":
        p = Path(_CRESTRON_CHM_PATH)
        candidates.append(str(p))
        if p.exists():
            return _CRESTRON_CHM_PATH

    # 5. Local development
    p = Path(__file__).parent / _CHM_NAME
    candidates.append(str(p))
    if p.exists():
        return str(p)

    # Build a helpful error with the platform-specific install path
    if platform.system() == "Windows":
        install_dir = str(Path(os.environ.get("LOCALAPPDATA", "")) / "chm-docs")
    else:
        install_dir = "/usr/local/share/chm-docs"

    if platform.system() == "Windows":
        msg = (
            f"SIMPLSharpPro.chm not found.\n"
            f"\n"
            f"Install the SIMPL# Pro library from Crestron:\n"
            f"  https://www.crestron.com/Software-Firmware/Software/SIMPL-153;-Windows-174;/Crestron-Simpl-Sharp-Pro-with-Simpl-Sharp-Library/2-000-0058-01\n"
            f"\n"
            f"The CHM file is installed to:\n"
            f"  C:\\Program Files (x86)\\Crestron\\Cresdb\\Help\\SIMPLSharpPro.chm\n"
            f"\n"
            f"Or copy it manually to:\n"
            f"  {install_dir}{os.sep}{_CHM_NAME}\n"
        )
    else:
        msg = (
            f"SIMPLSharpPro.chm not found.\n"
            f"\n"
            f"Copy it to:\n"
            f"  sudo cp SIMPLSharpPro.chm /usr/local/share/chm-docs/\n"
            f"\n"
            f"The CHM file can be found on a Windows machine with the SIMPL# Pro library installed:\n"
            f"  C:\\Program Files (x86)\\Crestron\\Cresdb\\Help\\SIMPLSharpPro.chm\n"
            f"\n"
            f"Or download the library from:\n"
            f"  https://www.crestron.com/Software-Firmware/Software/SIMPL-153;-Windows-174;/Crestron-Simpl-Sharp-Pro-with-Simpl-Sharp-Library/2-000-0058-01\n"
        )

    msg += (
        f"\nSearched:\n" +
        "\n".join(f"  - {c}" for c in candidates)
    )

    raise FileNotFoundError(msg)


# ---------------------------------------------------------------------------
# Early dispatch — handle --version and CLI mode before heavy imports
# ---------------------------------------------------------------------------

def _run_cli(argv: list[str]):
    """Run in CLI mode by delegating to chm_search.main() with resolved CHM path."""
    from chm_search import main as cli_main

    chm_path = _resolve_chm_path()
    cli_main(["--chm", chm_path] + argv)


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] in ("--version", "-V"):
        print(f"chm-docs {__version__}")
        sys.exit(0)

    if args:
        _run_cli(args)
        sys.exit(0)


# ---------------------------------------------------------------------------
# MCP server setup — only runs if no CLI args (MCP mode) or imported as module
# ---------------------------------------------------------------------------

import contextlib
import io

from mcp.server.fastmcp import FastMCP

from chm_search import CHMSearch


# On Windows without a console, sys.stderr may be None — ensure it's usable
# so progress messages (which write to stderr directly) are visible.
if sys.stderr is None:
    sys.stderr = io.open(os.devnull, "w")

# Redirect any stray stdout print() calls to stderr so they don't corrupt MCP stdio.
_stderr_redirect = contextlib.redirect_stdout(sys.stderr)

mcp = FastMCP("chm-docs", instructions=(
    "Crestron SIMPL# Pro SDK documentation search. "
    "Use search/search_title to find types, inspect for details, "
    "get_class_info for member listings, api_chain for event flows."
))
mcp._mcp_server.version = __version__


_startup_error = None


def _get_searcher() -> CHMSearch:
    """Lazy-init the CHMSearch instance. Raises RuntimeError with a helpful
    message if the CHM file can't be found."""
    if _startup_error:
        raise RuntimeError(_startup_error)
    if not hasattr(_get_searcher, "_instance"):
        try:
            chm_path = _resolve_chm_path()
        except FileNotFoundError as e:
            raise RuntimeError(str(e))
        with _stderr_redirect:
            _get_searcher._instance = CHMSearch(chm_path)
    return _get_searcher._instance


# ---------------------------------------------------------------------------
# Formatting helpers - produce clean text output for MCP tool results
# ---------------------------------------------------------------------------

def _format_search_results(results: list, query: str) -> str:
    if not results:
        return f"No results found for '{query}'"
    lines = [f"Found {len(results)} results for '{query}':\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        if r.get("namespace"):
            lines.append(f"   Namespace: {r['namespace']}")
        lines.append(f"   Path: {r['path']}")
        if r.get("snippet"):
            snippet = r["snippet"].replace(">>>", "**").replace("<<<", "**")
            lines.append(f"   ...{snippet}...")
        lines.append("")
    return "\n".join(lines)


def _format_title_results(results: list, query: str) -> str:
    if not results:
        return f"No titles found matching '{query}'"
    lines = [f"Found {len(results)} titles matching '{query}':\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        if r.get("namespace"):
            lines.append(f"   Namespace: {r['namespace']}")
        lines.append(f"   Path: {r['path']}")
        lines.append("")
    return "\n".join(lines)


def _format_inspect(info: dict) -> str:
    lines = []
    lines.append(f"{'=' * 70}")
    lines.append(f"Title: {info['title']}")
    lines.append(f"Category: {info['category']}")
    lines.append(f"Namespace: {info['namespace']}")
    lines.append(f"Path: {info['path']}")
    if info.get("description"):
        lines.append(f"Description: {info['description']}")
    lines.append(f"{'=' * 70}")

    if info.get("signature"):
        lines.append(f"\nSignature:")
        lines.append(f"  {info['signature']}")

    if info.get("parameters"):
        lines.append(f"\nParameters:")
        for p in info["parameters"]:
            type_ref = f" -> {p['type_path']}" if p.get("type_path") else ""
            lines.append(f"  {p['name']}: {p['type_name']}{type_ref}")
            if p.get("description"):
                lines.append(f"    {p['description']}")

    if info.get("return_type"):
        rt = info["return_type"]
        lines.append(f"\nReturn/Value Type:")
        lines.append(f"  {rt['name']}")
        if rt.get("path"):
            lines.append(f"  -> {rt['path']}")

    if info.get("enum_members"):
        lines.append(f"\nEnum Members:")
        max_name = max(len(m["name"]) for m in info["enum_members"])
        max_val = max(len(m["value"]) for m in info["enum_members"])
        for m in info["enum_members"]:
            desc = f"  - {m['description']}" if m.get("description") else ""
            lines.append(f"  {m['name']:<{max_name}}  = {m['value']:>{max_val}}{desc}")

    if info.get("properties"):
        lines.append(f"\nProperties:")
        for p in info["properties"][:15]:
            lines.append(f"  {p['name']}: {p.get('description', '')[:60]}")
            lines.append(f"    -> {p['path']}")

    if info.get("references"):
        seen = set()
        ref_lines = []
        for r in info["references"]:
            if r["title"] not in seen:
                seen.add(r["title"])
                ref_lines.append(f"  [{r['category']}] {r['title']}")
                ref_lines.append(f"    -> {r['path']}")
        if ref_lines:
            lines.append(f"\nReferenced Types ({len(seen)}):")
            lines.extend(ref_lines)

    if info.get("has_example"):
        lines.append(f"\n*** This document has a CODE EXAMPLE ***")
        lines.append(f'    Use the get_example tool with "{info["title"]}"')

    return "\n".join(lines)


def _format_class_info(info: dict) -> str:
    lines = []
    lines.append(f"{'=' * 60}")
    lines.append(f"Class: {info['main']['title']}")
    if info["main"].get("namespace"):
        lines.append(f"Namespace: {info['main']['namespace']}")
    lines.append(f"Path: {info['main']['path']}")
    lines.append(f"{'=' * 60}")

    sections = [
        ("Constructors", info["constructors"]),
        ("Properties", info["properties"]),
        ("Methods", info["methods"]),
        ("Events", info["events"]),
        ("Fields", info["fields"]),
        ("Operators", info["operators"]),
        ("Other", info["other"]),
    ]

    for section_name, items in sections:
        if items:
            lines.append(f"\n{section_name}:")
            lines.append("-" * 40)
            for item in items:
                lines.append(f"  {item['title']}")
                lines.append(f"    Path: {item['path']}")

    return "\n".join(lines)


def _format_api_chain(chain: dict) -> str:
    if chain.get("error"):
        return f"Error: {chain['error']}"

    lines = []
    lines.append(f"{'=' * 70}")
    lines.append(f"API Chain: {chain['start_class']}")
    if chain.get("member"):
        lines.append(f"Member: {chain['member']}")
    lines.append(f"{'=' * 70}\n")

    for item in chain["chain"]:
        indent = "  " * item["level"]
        arrow = "└─>" if item["level"] > 0 else ""
        lines.append(f"{indent}{arrow} [{item['type']}] {item['title']}")
        lines.append(f"{indent}    Path: {item['path']}")

        if item.get("signature"):
            sig = item["signature"]
            if len(sig) > 70:
                sig = sig[:70] + "..."
            lines.append(f"{indent}    Signature: {sig}")

        if item.get("description"):
            lines.append(f"{indent}    Description: {item['description'][:100]}")

        if item.get("param_name"):
            lines.append(f"{indent}    (Parameter: {item['param_name']})")

        if item.get("enum_members"):
            lines.append(f"{indent}    Values:")
            for m in item["enum_members"]:
                desc = f"  - {m.get('description', '')}" if m.get("description") else ""
                lines.append(f"{indent}      {m['name']} = {m['value']}{desc}")

        if item.get("properties"):
            lines.append(f"{indent}    Properties:")
            for p in item["properties"][:8]:
                lines.append(f"{indent}      - {p['name']}: {p.get('description', '')[:50]}")

        lines.append("")

    return "\n".join(lines)


def _format_namespaces(results: list) -> str:
    if not results:
        return "No namespaces found."
    lines = [f"Found {len(results)} namespaces:\n"]
    for r in results:
        lines.append(f"  {r['namespace']} ({r['count']} items)")
    return "\n".join(lines)


def _format_browse(results: list, namespace: str) -> str:
    if not results:
        return f"No items found in namespace '{namespace}'"
    lines = [f"Found {len(results)} items in '{namespace}':\n"]
    for r in results:
        lines.append(f"  {r['title']}")
        lines.append(f"    Path: {r['path']}")
    return "\n".join(lines)


def _format_example(result: dict) -> str:
    lines = []
    lines.append(f"{'=' * 70}")
    lines.append(f"Example: {result['title']}")
    lines.append(f"Namespace: {result['namespace']}")
    lines.append(f"{'=' * 70}\n")
    lines.append(result["example"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tool definitions
# ---------------------------------------------------------------------------

@mcp.tool()
def version() -> str:
    """Return the chm-docs server version."""
    return f"chm-docs {__version__}"


@mcp.tool()
def search(query: str, limit: int = 20) -> str:
    """Full-text keyword search across all Crestron SIMPL# Pro SDK documentation.

    Use this to find types, methods, properties, events, or any concept.
    Returns titles, namespaces, paths, and text snippets with matches highlighted.

    Args:
        query: Search keywords (e.g. "HttpClient", "lighting control", "relay")
        limit: Maximum number of results (default 20)
    """
    chm = _get_searcher()
    with _stderr_redirect:
        results = chm.search(query, limit)
    return _format_search_results(results, query)


@mcp.tool()
def search_title(query: str, limit: int = 20) -> str:
    """Search only in document titles for precise type/member lookup.

    Faster and more targeted than full-text search. Best for finding a specific
    class, interface, enum, delegate, or member by name.

    Args:
        query: Type or member name to search for (e.g. "BasicTriList", "LoadEventArgs")
        limit: Maximum number of results (default 20)
    """
    chm = _get_searcher()
    with _stderr_redirect:
        results = chm.search_title(query, limit)
    return _format_title_results(results, query)


@mcp.tool()
def inspect(type_name: str) -> str:
    """Detailed view of any SDK type or member.

    Shows signature, parameters, return type, enum values, properties,
    referenced types, and whether a code example exists. Accepts either
    a type name (e.g. "LoadEventArgs") or a document path (e.g. "html/abc123.htm").

    Args:
        type_name: Type/member name or document path to inspect
    """
    chm = _get_searcher()
    with _stderr_redirect:
        info = chm.inspect(type_name)
    if not info:
        return f"Type not found: {type_name}"
    return _format_inspect(info)


@mcp.tool()
def get_class_info(class_name: str) -> str:
    """Get a class overview with all its members grouped by category.

    Lists constructors, properties, methods, events, fields, and operators.
    Use inspect on individual members for details.

    Args:
        class_name: Class name to look up (e.g. "BasicTriList", "ClwDimswex")
    """
    chm = _get_searcher()
    with _stderr_redirect:
        # Check if it's actually an enum
        enum_check = chm.inspect(class_name)
        if enum_check and enum_check.get("category") == "enum" and enum_check.get("enum_members"):
            return _format_inspect(enum_check)

        info = chm.get_class_info(class_name)
    if not info:
        return f"Class not found: {class_name}"
    return _format_class_info(info)


@mcp.tool()
def api_chain(class_name: str, member_name: str | None = None) -> str:
    """Follow an event/property/method chain through the SDK type system.

    Starting from a class, optionally focusing on a specific member, traces
    the chain: class → event → delegate → eventargs → properties.
    Essential for understanding Crestron event handler wiring.

    Args:
        class_name: Starting class name (e.g. "ClwDimswex")
        member_name: Optional member to focus on (e.g. "LoadStateChange")
    """
    chm = _get_searcher()
    with _stderr_redirect:
        chain = chm.api_chain(class_name, member_name)
    return _format_api_chain(chain)


@mcp.tool()
def browse_namespace(namespace: str, limit: int = 50) -> str:
    """List all types within a specific SDK namespace.

    Args:
        namespace: Namespace to browse (e.g. "Crestron.SimplSharpPro.Lighting")
        limit: Maximum number of results (default 50)
    """
    chm = _get_searcher()
    with _stderr_redirect:
        results = chm.browse_namespace(namespace, limit)
    return _format_browse(results, namespace)


@mcp.tool()
def list_namespaces() -> str:
    """List all available namespaces in the Crestron SIMPL# Pro SDK.

    Returns namespace names with item counts. Use browse_namespace to
    explore a specific namespace.
    """
    chm = _get_searcher()
    with _stderr_redirect:
        results = chm.list_namespaces()
    return _format_namespaces(results)


@mcp.tool()
def get_example(type_name: str) -> str:
    """Get the C# code example for a specific SDK type.

    Args:
        type_name: Type name or document path (e.g. "BasicTriList", "html/abc123.htm")
    """
    chm = _get_searcher()
    with _stderr_redirect:
        result = chm.get_example(type_name)
    if not result:
        return f"No example found for: {type_name}"
    return _format_example(result)


@mcp.tool()
def show_document(path: str) -> str:
    """Read the full formatted text of any SDK document by its path.

    Use paths from search results or inspect output. Returns the complete
    document content as formatted text.

    Args:
        path: Document path (e.g. "html/abc123.htm")
    """
    chm = _get_searcher()
    with _stderr_redirect:
        content = chm.show(path)
    if not content:
        return f"Document not found: {path}"
    return content


# ---------------------------------------------------------------------------
# MCP server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Eagerly build cache so tool calls don't block on first use.
    # If CHM is missing, store the error and let the server start —
    # the error surfaces through tool calls so Claude can relay it.
    try:
        searcher = _get_searcher()
        searcher.ensure_extracted()
        searcher.build_index()
    except (FileNotFoundError, RuntimeError) as e:
        _startup_error = str(e)
        print(f"chm-docs: {e}", file=sys.stderr)

    mcp.run(transport="stdio")
