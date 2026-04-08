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


_CHM_CONFIGS = {
    'spro': {
        'name': 'SIMPLSharpPro.chm',
        'crestron_path': r"C:\Program Files (x86)\Crestron\Cresdb\Help\SIMPLSharpPro.chm",
        'env_var': 'CHM_PATH',
    },
    'simpl': {
        'name': 'SIMPL_Windows.chm',
        'crestron_path': r"C:\Program Files (x86)\Crestron\Simpl\SIMPL_Windows.chm",
        'env_var': 'SIMPL_CHM_PATH',
    },
}

# Keep backward compat
_CHM_NAME = "SIMPLSharpPro.chm"
_CRESTRON_CHM_PATH = _CHM_CONFIGS['spro']['crestron_path']


# Read version from VERSION file (bundled or local) — no heavy imports needed
def _read_version() -> str:
    for base in [getattr(sys, "_MEIPASS", None), Path(__file__).parent]:
        if base:
            p = Path(base) / "VERSION"
            if p.exists():
                return p.read_text().strip()
    return "0.0.0"


__version__ = _read_version()


def _resolve_chm_path(chm_key: str = 'spro') -> str:
    """Resolve a CHM file path using priority order:
    1. Dedicated environment variable (CHM_PATH for spro, SIMPL_CHM_PATH for simpl)
    2. CHM_PATH environment variable (legacy, for spro only)
    3. PyInstaller bundle (sys._MEIPASS)
    4. Platform install location (macOS: /usr/local/share, Windows: %LOCALAPPDATA%)
    5. Crestron database install (Windows only)
    6. ./<filename>.chm (development fallback)
    """
    cfg = _CHM_CONFIGS.get(chm_key)
    if not cfg:
        raise FileNotFoundError(f"Unknown CHM key: {chm_key}")

    chm_name = cfg['name']
    candidates = []

    # 1. Dedicated environment variable
    env_path = os.environ.get(cfg['env_var'])
    if env_path:
        p = Path(env_path)
        if p.exists():
            return str(p)
        candidates.append(str(p))

    # 1b. Legacy CHM_PATH for backward compat (spro only)
    if chm_key == 'spro':
        env_path = os.environ.get("CHM_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return str(p)
            candidates.append(str(p))

    # 2. PyInstaller bundle
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / chm_name
        if p.exists():
            return str(p)
        candidates.append(str(p))

    # 3. Platform install location
    if platform.system() == "Windows":
        p = Path(os.environ.get("LOCALAPPDATA", "")) / "chm-docs" / chm_name
    else:
        p = Path("/usr/local/share/chm-docs") / chm_name
    candidates.append(str(p))
    if p.exists():
        return str(p)

    # 4. Crestron install (Windows)
    if platform.system() == "Windows" and cfg.get('crestron_path'):
        p = Path(cfg['crestron_path'])
        candidates.append(str(p))
        if p.exists():
            return str(p)

    # 5. Local development
    p = Path(__file__).parent / chm_name
    candidates.append(str(p))
    if p.exists():
        return str(p)

    # Build error message
    if platform.system() == "Windows":
        install_dir = str(Path(os.environ.get("LOCALAPPDATA", "")) / "chm-docs")
    else:
        install_dir = "/usr/local/share/chm-docs"

    msg = (
        f"{chm_name} not found.\n"
        f"\n"
        f"Copy it to:\n"
        f"  {install_dir}{os.sep}{chm_name}\n"
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

    chm_path = _resolve_chm_path('spro')
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

import io
import threading

from mcp.server.fastmcp import FastMCP

from chm_search import CHMSearch


# On Windows without a console, sys.stderr may be None — ensure it's usable
# so progress messages (which write to stderr directly) are visible.
if sys.stderr is None:
    sys.stderr = io.open(os.devnull, "w")

mcp = FastMCP("chm-docs", instructions=(
    "Crestron SIMPL# Pro SDK and SIMPL Windows documentation search. "
    "Two CHM sources are available: 'spro' (SIMPL# Pro C# SDK) and 'simpl' (SIMPL Windows device library). "
    "Tools that accept a 'chm' parameter default to 'spro'. Pass chm='simpl' for SIMPL Windows.\n\n"

    "SIMPL# Pro tools (chm='spro'):\n"
    "  - search/search_title: find classes, methods, properties, events by keyword or name\n"
    "  - inspect: detailed view of any type — signature, parameters, return type, references\n"
    "  - get_class_info: list all members of a class grouped by category\n"
    "  - api_chain: trace event wiring — class → event → delegate → eventargs → properties\n"
    "  - get_example: retrieve C# code examples\n\n"

    "SIMPL Windows tools (chm='simpl'):\n"
    "  - search/search_title with chm='simpl': find devices, cards, slots by name\n"
    "  - inspect with chm='simpl': view device signal tables and programming slot structure\n"
    "  - search_signals: search signal definitions by name or description, optionally filtered by type\n"
    "  - get_device_signals: get all signals for a device grouped by slot with descriptions\n\n"

    "Cross-referencing between SIMPL Windows and S#Pro:\n"
    "  - cross_reference: given a SIMPL Windows device name, find the matching S#Pro class "
    "and show how all signals map to S#Pro types\n"
    "  - cross_reference_member: given an S#Pro class and member name, traverse to the "
    "matching SIMPL Windows slot and map individual signals with descriptions. "
    "Use this to get SIMPL signal descriptions that are missing from the S#Pro docs.\n\n"

    "Signal type mapping (SIMPL Windows → S#Pro):\n"
    "  Digital input/output  → BooleanInput/BooleanOutput (BoolInput/BoolOutput)\n"
    "  Analog input/output   → UShortInput/UShortOutput\n"
    "  Serial input/output   → StringInput/StringOutput\n"
    "  Parameter             → compile-time config (no runtime S#Pro equivalent)\n\n"

    "Device naming: SIMPL Windows uses hyphenated names (CLW-DIMFLVEX-P) while S#Pro uses "
    "PascalCase (ClwDimFlvExP). The cross-reference tools handle this translation automatically.\n\n"

    "Typical cross-reference workflow:\n"
    "  1. Find the S#Pro class: inspect('ClwDimFlvExP')\n"
    "  2. Get SIMPL signal descriptions: cross_reference_member('ClwDimFlvExP', 'DimmerRemoteButtonSettings')\n"
    "  3. Or start from SIMPL: get_device_signals('CLW-DIMFLVEX-P') then cross_reference('CLW-DIMFLVEX-P')\n"
    "  4. For individual signals: cross_reference_member('ClwDimFlvExP', 'LevelIn') → finds Level_In with description"
))
mcp._mcp_server.version = __version__


_searcher_lock = threading.Lock()
_searchers: dict[str, CHMSearch] = {}


def _get_searcher(chm: str = 'spro') -> CHMSearch:
    """Lazy-init a CHMSearch instance for the given CHM key. Thread-safe."""
    with _searcher_lock:
        if chm not in _searchers:
            try:
                chm_path = _resolve_chm_path(chm)
            except FileNotFoundError as e:
                raise RuntimeError(str(e))
            instance = CHMSearch(chm_path)
            instance.ensure_extracted()
            instance.build_index()
            _searchers[chm] = instance
        return _searchers[chm]


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

    # SIMPL Windows signal data
    if info.get("signals"):
        lines.append(f"\nSignals:")
        lines.append("-" * 40)
        _append_signal_lines(lines, info["signals"])

    if info.get("slots"):
        lines.append(f"\nProgramming Slots:")
        for s in info["slots"]:
            lines.append(f"  Slot {s['slot_number']:02d}: {s['name']}")
            if s.get('href'):
                lines.append(f"    -> {s['href']}")

    if info.get("has_example"):
        lines.append(f"\n*** This document has a CODE EXAMPLE ***")
        lines.append(f'    Use the get_example tool with "{info["title"]}"')

    return "\n".join(lines)


def _append_signal_lines(lines: list, signals: list):
    """Append formatted signal lines grouped by type."""
    type_labels = {
        'digital_input': 'Digital Inputs',
        'digital_output': 'Digital Outputs',
        'analog_input': 'Analog Inputs',
        'analog_output': 'Analog Outputs',
        'serial_input': 'Serial Inputs',
        'serial_output': 'Serial Outputs',
        'parameter': 'Parameters',
    }
    grouped: dict[str, list] = {}
    for s in signals:
        st = s.get('signal_type') or s.get('type', 'unknown')
        grouped.setdefault(st, []).append(s)

    for st in ('digital_input', 'digital_output', 'analog_input', 'analog_output',
               'serial_input', 'serial_output', 'parameter'):
        sigs = grouped.get(st, [])
        if not sigs:
            continue
        lines.append(f"\n  {type_labels.get(st, st)}:")
        for s in sigs:
            name = s.get('name') or s.get('signal_name', '?')
            desc = s.get('description', '')
            if len(desc) > 80:
                desc = desc[:77] + '...'
            lines.append(f"    {name}")
            if desc:
                lines.append(f"      {desc}")


def _format_signal_search(results: list, query: str) -> str:
    if not results:
        return f"No signals found for '{query}'"
    lines = [f"Found {len(results)} signals for '{query}':\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r['signal_type']}] {r['signal_name']}")
        lines.append(f"   Document: {r['document_title']}")
        lines.append(f"   Path: {r['path']}")
        desc = r.get('description', '')
        if desc:
            if len(desc) > 100:
                desc = desc[:97] + '...'
            lines.append(f"   {desc}")
        lines.append("")
    return "\n".join(lines)


def _format_device_signals(info: dict) -> str:
    if not info:
        return "Device not found"
    lines = []
    lines.append(f"{'=' * 70}")
    lines.append(f"Device: {info['title']}")
    if info.get('namespace'):
        cat = info['namespace'].replace('|', ' > ')
        lines.append(f"Category: {cat}")
    lines.append(f"Path: {info['path']}")
    if info.get('description'):
        lines.append(f"\n{info['description']}")
    lines.append(f"{'=' * 70}")

    if info.get('signals'):
        lines.append(f"\nDevice-level Signals:")
        lines.append("-" * 40)
        _append_signal_lines(lines, info['signals'])

    for slot in info.get('slots', []):
        lines.append(f"\n{'─' * 40}")
        lines.append(f"Slot {slot['slot_number']:02d}: {slot['slot_name']}")
        lines.append(f"  Path: {slot['slot_path']}")
        if slot.get('signals'):
            _append_signal_lines(lines, slot['signals'])
        else:
            lines.append("  (no signals defined)")

    return "\n".join(lines)


def _device_name_to_spro_candidates(device_name: str) -> list[str]:
    """Generate S#Pro class name candidates from a SIMPL Windows device name.

    Crestron convention: CLW-DIMFLVEX-P -> ClwDimFlvExP (PascalCase per segment).
    We generate several variants since the casing isn't always predictable.
    """
    # Normalize: strip whitespace, work with uppercase segments
    name = device_name.strip()
    parts = [p for p in name.replace('_', '-').split('-') if p]

    candidates = []

    # 1. Exact concatenation with each part title-cased: ClwDimflvexP
    candidates.append(''.join(p.capitalize() for p in parts))

    # 2. All parts lowered then capitalized first char: same as above typically
    # 3. Try stripping trailing numeric-only parts (e.g. "204" in CEN-IO-RY-204)
    alpha_parts = [p for p in parts if not p.isdigit()]
    if alpha_parts != parts:
        candidates.append(''.join(p.capitalize() for p in alpha_parts))

    # 4. Keep original casing but just remove hyphens
    candidates.append(name.replace('-', '').replace('_', ''))

    # 5. Try the raw name (might match as a partial search)
    candidates.append(name)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


import re as _re


def _normalize_signal_name(name: str) -> str:
    """Normalize a signal name for comparison.

    Strips underscores, lowercases, and expands common Crestron abbreviations
    so that S#Pro 'LevelIn' matches SIMPL 'Level_In', and
    'ParameterRemoteDoubleTapTime' matches 'RemoteDblTapTime'.
    """
    n = _re.sub(r'[_\-\s]', '', name).lower()
    # Expand common Crestron abbreviations for matching
    n = n.replace('dbl', 'double')
    n = n.replace('btn', 'button')
    n = n.replace('brt', 'bright')
    n = n.replace('dn', 'down')
    n = n.replace('fb', 'feedback')
    return n


# Additional normalization: strip verbose S#Pro suffixes for matching
_SPRO_STRIP_PATTERNS = [
    # 'ReservedButtonForLocalMode' → 'LocalButton' — needs keyword extraction
]


def _match_spro_member_to_simpl_signal(spro_name: str, simpl_signals: list) -> dict | None:
    """Find the SIMPL Windows signal that best matches an S#Pro property/method name.

    S#Pro properties often have a 'Parameter' prefix (e.g. 'ParameterRemoteHoldTime')
    that maps to a SIMPL parameter signal ('RemoteHoldTime' or 'Remote_Hold_Time').
    Signal properties like 'LevelIn' map to 'Level_In'.
    Handles abbreviation differences: DoubleTap ↔ DblTap, etc.
    """
    # Strip common S#Pro prefixes
    clean = spro_name
    for prefix in ('Parameter', 'DeviceLoad'):
        if clean.startswith(prefix) and len(clean) > len(prefix):
            clean = clean[len(prefix):]

    norm_spro = _normalize_signal_name(clean)

    best = None
    best_score = 0

    for sig in simpl_signals:
        sig_name = sig.get('name') or sig.get('signal_name', '')
        # Handle range signals: "Recall_Pre_1 through Recall_Pre_3" → use first part
        base_name = sig_name.split(' through ')[0].strip()
        norm_simpl = _normalize_signal_name(base_name)

        if norm_spro == norm_simpl:
            return sig  # exact match

        # Partial/substring match scoring
        score = 0
        if norm_spro in norm_simpl or norm_simpl in norm_spro:
            score = min(len(norm_spro), len(norm_simpl)) / max(len(norm_spro), len(norm_simpl))

        # Keyword overlap: split into words on case boundaries, score by shared words
        if score < 0.6:
            spro_words = set(_re.findall(r'[a-z]+|\d+', norm_spro))
            simpl_words = set(_re.findall(r'[a-z]+|\d+', norm_simpl))
            if spro_words and simpl_words:
                overlap = spro_words & simpl_words
                union = spro_words | simpl_words
                if overlap:
                    word_score = len(overlap) / len(union)
                    score = max(score, word_score)

        if score > best_score:
            best_score = score
            best = sig

    return best if best_score > 0.5 else None


def _slot_name_from_spro_class(spro_class_name: str, device_class_name: str) -> str:
    """Extract a SIMPL Windows slot name hint from an S#Pro settings class name.

    E.g. 'ClwDimExDimmerRemoteButtonSettings' with device 'ClwDimFlvExP'
    → strip common prefixes → 'DimmerRemoteButtonSettings' → 'Dimmer Remote Button Settings'
    """
    # The settings class name usually embeds the slot function
    # Try to extract the meaningful suffix by removing known device-family prefixes
    name = spro_class_name
    # Remove 'Class' suffix
    name = _re.sub(r'\s*Class$', '', name)
    # Remove common device family prefixes
    for prefix in ('ClwDimEx', 'ClwDimsw', 'ClwSw', 'Clw', 'Tsw', 'Tpmc', 'Cen'):
        if name.startswith(prefix) and len(name) > len(prefix) + 3:
            name = name[len(prefix):]
            break

    # Insert spaces before uppercase letters (PascalCase → words)
    spaced = _re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    spaced = _re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', spaced)
    return spaced


_SIGNAL_TYPE_MAP = {
    'digital_input': ('BooleanInput', 'BoolInput'),
    'digital_output': ('BooleanOutput', 'BoolOutput'),
    'analog_input': ('UShortInput', 'UShortInput'),
    'analog_output': ('UShortOutput', 'UShortOutput'),
    'serial_input': ('StringInput', 'StringInput'),
    'serial_output': ('StringOutput', 'StringOutput'),
}


def _format_cross_reference(device_info: dict, spro_class: dict | None) -> str:
    lines = []
    lines.append(f"{'=' * 70}")
    lines.append(f"Cross-Reference: {device_info['title']}")
    lines.append(f"SIMPL Windows -> SIMPL# Pro")
    lines.append(f"{'=' * 70}")

    if spro_class:
        lines.append(f"\nSIMPL# Pro Class: {spro_class['title']}")
        lines.append(f"  Namespace: {spro_class.get('namespace', 'N/A')}")
        lines.append(f"  Path: {spro_class['path']}")
    else:
        lines.append(f"\nNo matching SIMPL# Pro class found.")
        lines.append(f"(Tried searching for device name variants)")

    lines.append(f"\nSignal Type Mapping:")
    lines.append(f"  {'SIMPL Windows':<25} {'SIMPL# Pro':<25}")
    lines.append(f"  {'─' * 25} {'─' * 25}")
    lines.append(f"  Digital input/output     BooleanInput/BooleanOutput")
    lines.append(f"  Analog input/output      UShortInput/UShortOutput")
    lines.append(f"  Serial input/output      StringInput/StringOutput")
    lines.append(f"  Parameter                (compile-time config)")

    # List device signals with their S#Pro equivalents
    all_signals = list(device_info.get('signals', []))
    for slot in device_info.get('slots', []):
        all_signals.extend(slot.get('signals', []))

    if all_signals:
        lines.append(f"\nDevice Signals ({len(all_signals)}):")
        lines.append(f"  {'Signal':<30} {'SIMPL Type':<18} {'S#Pro Type'}")
        lines.append(f"  {'─' * 30} {'─' * 18} {'─' * 20}")
        for s in all_signals[:50]:  # cap at 50 for readability
            name = s.get('name') or s.get('signal_name', '?')
            st = s.get('type') or s.get('signal_type', '?')
            spro = _SIGNAL_TYPE_MAP.get(st, ('N/A', ''))[0]
            if len(name) > 28:
                name = name[:25] + '...'
            lines.append(f"  {name:<30} {st:<18} {spro}")
        if len(all_signals) > 50:
            lines.append(f"  ... and {len(all_signals) - 50} more signals")

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
def search(query: str, limit: int = 20, chm: str = 'spro') -> str:
    """Full-text keyword search across Crestron documentation.

    Use this to find types, methods, properties, events, devices, or any concept.
    Returns titles, namespaces, paths, and text snippets with matches highlighted.

    Args:
        query: Search keywords (e.g. "HttpClient", "lighting control", "relay")
        limit: Maximum number of results (default 20)
        chm: Which CHM to search - 'spro' for SIMPL# Pro, 'simpl' for SIMPL Windows
    """
    searcher = _get_searcher(chm)
    results = searcher.search(query, limit)
    return _format_search_results(results, query)


@mcp.tool()
def search_title(query: str, limit: int = 20, chm: str = 'spro') -> str:
    """Search only in document titles for precise type/member/device lookup.

    Faster and more targeted than full-text search. Best for finding a specific
    class, interface, enum, delegate, member, or device by name.

    Args:
        query: Type or member name to search for (e.g. "BasicTriList", "CLW-DIMFLVEX")
        limit: Maximum number of results (default 20)
        chm: Which CHM to search - 'spro' for SIMPL# Pro, 'simpl' for SIMPL Windows
    """
    searcher = _get_searcher(chm)
    results = searcher.search_title(query, limit)
    return _format_title_results(results, query)


@mcp.tool()
def inspect(type_name: str, chm: str = 'spro') -> str:
    """Detailed view of any SDK type/member or SIMPL Windows device.

    For SIMPL# Pro: shows signature, parameters, return type, enum values,
    properties, referenced types, and code examples.
    For SIMPL Windows: shows signal definitions (digital/analog/serial I/O)
    and programming slot structure.

    Args:
        type_name: Type/member/device name or document path to inspect
        chm: Which CHM to search - 'spro' for SIMPL# Pro, 'simpl' for SIMPL Windows
    """
    searcher = _get_searcher(chm)
    info = searcher.inspect(type_name)
    if not info:
        return f"Type not found: {type_name}"
    return _format_inspect(info)


@mcp.tool()
def get_class_info(class_name: str, chm: str = 'spro') -> str:
    """Get a class overview with all its members grouped by category.

    Lists constructors, properties, methods, events, fields, and operators.
    Use inspect on individual members for details.

    Args:
        class_name: Class name to look up (e.g. "BasicTriList", "ClwDimswex")
        chm: Which CHM to search - 'spro' for SIMPL# Pro, 'simpl' for SIMPL Windows
    """
    searcher = _get_searcher(chm)
    # Check if it's actually an enum
    enum_check = searcher.inspect(class_name)
    if enum_check and enum_check.get("category") == "enum" and enum_check.get("enum_members"):
        return _format_inspect(enum_check)

    info = searcher.get_class_info(class_name)
    if not info:
        return f"Class not found: {class_name}"
    return _format_class_info(info)


@mcp.tool()
def api_chain(class_name: str, member_name: str | None = None) -> str:
    """Follow an event/property/method chain through the SDK type system.

    Starting from a class, optionally focusing on a specific member, traces
    the chain: class -> event -> delegate -> eventargs -> properties.
    Essential for understanding Crestron event handler wiring.

    Args:
        class_name: Starting class name (e.g. "ClwDimswex")
        member_name: Optional member to focus on (e.g. "LoadStateChange")
    """
    searcher = _get_searcher('spro')
    chain = searcher.api_chain(class_name, member_name)
    return _format_api_chain(chain)


@mcp.tool()
def browse_namespace(namespace: str, limit: int = 50, chm: str = 'spro') -> str:
    """List all types within a specific namespace or category.

    For SIMPL# Pro: use dotted namespaces (e.g. "Crestron.SimplSharpPro.Lighting").
    For SIMPL Windows: use pipe-delimited categories (e.g. "Device Library|Lighting").

    Args:
        namespace: Namespace or category to browse
        limit: Maximum number of results (default 50)
        chm: Which CHM to search - 'spro' for SIMPL# Pro, 'simpl' for SIMPL Windows
    """
    searcher = _get_searcher(chm)
    results = searcher.browse_namespace(namespace, limit)
    return _format_browse(results, namespace)


@mcp.tool()
def list_namespaces(chm: str = 'spro') -> str:
    """List all available namespaces/categories in the documentation.

    For SIMPL# Pro: returns .NET namespaces.
    For SIMPL Windows: returns device category paths.

    Args:
        chm: Which CHM to list - 'spro' for SIMPL# Pro, 'simpl' for SIMPL Windows
    """
    searcher = _get_searcher(chm)
    results = searcher.list_namespaces()
    return _format_namespaces(results)


@mcp.tool()
def get_example(type_name: str) -> str:
    """Get the C# code example for a specific SDK type.

    Args:
        type_name: Type name or document path (e.g. "BasicTriList", "html/abc123.htm")
    """
    searcher = _get_searcher('spro')
    result = searcher.get_example(type_name)
    if not result:
        return f"No example found for: {type_name}"
    return _format_example(result)


@mcp.tool()
def show_document(path: str, chm: str = 'spro') -> str:
    """Read the full formatted text of any document by its path.

    Use paths from search results or inspect output. Returns the complete
    document content as formatted text.

    Args:
        path: Document path (e.g. "html/abc123.htm" or "Device_Library/Lighting/...")
        chm: Which CHM to read from - 'spro' for SIMPL# Pro, 'simpl' for SIMPL Windows
    """
    searcher = _get_searcher(chm)
    content = searcher.show(path)
    if not content:
        return f"Document not found: {path}"
    return content


# ---------------------------------------------------------------------------
# SIMPL Windows-specific tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_signals(query: str, signal_type: str | None = None, limit: int = 20) -> str:
    """Search SIMPL Windows signal definitions by name or description.

    Searches across all device signal tables for matching signal names or
    descriptions. Signals map to SIMPL# Pro types: Digital->Bool, Analog->UShort,
    Serial->String.

    Args:
        query: Signal name or description keywords (e.g. "Fan_Speed", "dimming level")
        signal_type: Optional filter - 'digital_input', 'digital_output', 'analog_input',
                     'analog_output', 'serial_input', 'serial_output', 'parameter'
        limit: Maximum results (default 20)
    """
    searcher = _get_searcher('simpl')
    results = searcher.search_signals(query, signal_type, limit)
    return _format_signal_search(results, query)


@mcp.tool()
def get_device_signals(device_name: str) -> str:
    """Get all signals (inputs, outputs, parameters) for a SIMPL Windows device.

    Returns signals grouped by type (digital/analog/serial inputs/outputs and
    parameters) with descriptions. For multi-slot devices, shows the slot
    structure with signals for each slot.

    Args:
        device_name: Device model name (e.g. "CLW-DIMFLVEX-P", "CEN-IO-RY-204",
                     "Fusion Lighting Load", "TSW-1060")
    """
    searcher = _get_searcher('simpl')
    info = searcher.get_device_signals(device_name)
    if not info:
        return f"Device not found: {device_name}"
    return _format_device_signals(info)


@mcp.tool()
def cross_reference(device_name: str) -> str:
    """Cross-reference a SIMPL Windows device with its SIMPL# Pro equivalent.

    Shows how SIMPL Windows signal types map to S# Pro property types:
    - Digital input/output -> BooleanInput/BooleanOutput (BoolInput/BoolOutput)
    - Analog input/output -> UShortInput/UShortOutput
    - Serial input/output -> StringInput/StringOutput
    - Parameter -> compile-time configuration (no S#Pro equivalent)

    Args:
        device_name: SIMPL Windows device name (e.g. "CLW-DIMFLVEX-P")
    """
    simpl = _get_searcher('simpl')
    device_info = simpl.get_device_signals(device_name)
    if not device_info:
        return f"Device not found in SIMPL Windows: {device_name}"

    # Try to find matching S#Pro class
    spro_class = None
    try:
        spro = _get_searcher('spro')
        # Build PascalCase class name from hyphenated device name
        # CLW-DIMFLVEX-P -> ClwDimflvexP, then also try title-cased segments
        candidates = _device_name_to_spro_candidates(device_name)
        for attempt in candidates:
            result = spro.find_type(attempt)
            if result:
                spro_class = result
                break
    except (RuntimeError, FileNotFoundError):
        pass  # S#Pro CHM not available

    return _format_cross_reference(device_info, spro_class)


@mcp.tool()
def cross_reference_member(class_name: str, member_name: str) -> str:
    """Traverse from an S#Pro class member to its SIMPL Windows signal equivalent.

    Given a class and property/method name, resolves the S#Pro member, finds the
    matching SIMPL Windows device and slot, and maps individual signals between
    the two systems. Handles naming differences like S#Pro 'LevelIn' matching
    SIMPL 'Level_In', and 'ParameterRemoteHoldTime' matching 'RemoteHoldTime'.

    Args:
        class_name: S#Pro class name (e.g. "ClwDimFlvExP")
        member_name: Property or method name (e.g. "DimmerRemoteButtonSettings",
                     "DimmingLoads", "LevelIn")
    """
    try:
        spro = _get_searcher('spro')
    except (RuntimeError, FileNotFoundError):
        return "SIMPL# Pro CHM not available"
    try:
        simpl = _get_searcher('simpl')
    except (RuntimeError, FileNotFoundError):
        return "SIMPL Windows CHM not available"

    lines = []

    # 1. Resolve the S#Pro class
    class_info = spro.inspect(class_name)
    if not class_info:
        return f"S#Pro class not found: {class_name}"

    lines.append(f"{'=' * 70}")
    lines.append(f"Cross-Reference Member: {class_info['title']}.{member_name}")
    lines.append(f"{'=' * 70}")

    # 2. Find the member - check properties and references
    member_doc = None
    member_type_class = None

    # Try direct property lookup
    search_name = f"{class_name}.{member_name}"
    member_doc = spro.inspect(search_name)

    # If not found, search by member name alone
    if not member_doc:
        results = spro.search_title(f"{class_name} {member_name}", 5)
        for r in results:
            if member_name.lower() in r['title'].lower():
                member_doc = spro.inspect(r['path'])
                break

    if member_doc:
        lines.append(f"\nS#Pro Member: {member_doc['title']}")
        lines.append(f"  Path: {member_doc['path']}")
        if member_doc.get('description'):
            lines.append(f"  Description: {member_doc['description']}")

        # If the member has a return/value type, resolve it
        if member_doc.get('return_type'):
            rt = member_doc['return_type']
            lines.append(f"  Type: {rt['name']}")
            if rt.get('path'):
                member_type_class = spro.inspect(rt['path'])
    else:
        lines.append(f"\nS#Pro member '{member_name}' not found on {class_name}")
        lines.append(f"Attempting fuzzy match...")

    # 3. Find the SIMPL Windows device
    device_candidates = _device_name_to_spro_candidates(class_name)
    # Reverse: try to go from S#Pro name back to device name
    # ClwDimFlvExP → insert hyphens at case boundaries → CLW-DIM-FLV-EX-P
    spaced = _re.sub(r'([a-z])([A-Z])', r'\1-\2', class_name)
    spaced = _re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', spaced)
    device_candidates.insert(0, spaced.upper())

    device_info = None
    for candidate in device_candidates:
        device_info = simpl.get_device_signals(candidate)
        if device_info:
            break

    if not device_info:
        lines.append(f"\nSIMPL Windows device not found for: {class_name}")
        return "\n".join(lines)

    lines.append(f"\nSIMPL Windows Device: {device_info['title']}")

    # 4. Collect all SIMPL signals (device-level + all slots)
    all_simpl_signals = list(device_info.get('signals', []))
    slot_signals: dict[str, list] = {}
    for slot in device_info.get('slots', []):
        sigs = slot.get('signals', [])
        slot_signals[slot['slot_name']] = sigs
        all_simpl_signals.extend(sigs)

    # 5. If we resolved a type class (e.g. DimmerRemoteButtonSettings), match its
    #    members to a specific SIMPL slot and compare signals
    if member_type_class and member_type_class.get('properties'):
        slot_hint = _slot_name_from_spro_class(
            member_type_class['title'], class_name
        )
        lines.append(f"\nS#Pro Settings Class: {member_type_class['title']}")
        lines.append(f"  Slot name hint: \"{slot_hint}\"")

        # Find matching SIMPL slot
        matched_slot = None
        norm_hint = _normalize_signal_name(slot_hint)
        for slot in device_info.get('slots', []):
            norm_slot = _normalize_signal_name(slot['slot_name'])
            if norm_hint in norm_slot or norm_slot in norm_hint:
                matched_slot = slot
                break

        if matched_slot:
            lines.append(f"  Matched SIMPL Slot: Slot {matched_slot['slot_number']:02d}: {matched_slot['slot_name']}")
            lines.append(f"\n  {'S#Pro Property':<45} {'SIMPL Signal':<35} {'Description'}")
            lines.append(f"  {'─' * 45} {'─' * 35} {'─' * 40}")

            slot_sigs = matched_slot.get('signals', [])
            spro_props = member_type_class.get('properties', [])

            for prop in spro_props:
                prop_name = prop['name'].split('.')[-1]  # Remove class prefix
                if prop_name.endswith(' Property') or prop_name.endswith(' Method'):
                    continue  # Skip the overview entries
                match = _match_spro_member_to_simpl_signal(prop_name, slot_sigs)
                if match:
                    sig_name = match.get('name') or match.get('signal_name', '?')
                    desc = match.get('description', '')
                    if len(desc) > 40:
                        desc = desc[:37] + '...'
                    lines.append(f"  {prop_name:<45} {sig_name:<35} {desc}")
                else:
                    lines.append(f"  {prop_name:<45} {'(no match)':<35}")
        else:
            lines.append(f"  No matching SIMPL slot found for \"{slot_hint}\"")

    # 6. If it's a direct signal property (like LevelIn), find it in SIMPL
    elif not member_type_class:
        lines.append(f"\n  Searching SIMPL signals for '{member_name}'...")
        match = _match_spro_member_to_simpl_signal(member_name, all_simpl_signals)
        if match:
            sig_name = match.get('name') or match.get('signal_name', '?')
            sig_type = match.get('type') or match.get('signal_type', '?')
            desc = match.get('description', '')
            spro_t = _SIGNAL_TYPE_MAP.get(sig_type, ('?', '?'))

            lines.append(f"\n  Match found:")
            lines.append(f"  S#Pro: {member_name}")
            lines.append(f"  SIMPL: {sig_name} ({sig_type})")
            lines.append(f"  S#Pro Type: {spro_t[0]}")
            if desc:
                lines.append(f"  Description: {desc}")
        else:
            lines.append(f"  No matching SIMPL signal found for '{member_name}'")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Warm cache in background so the MCP server starts immediately.
    # If a CHM is missing, the error surfaces through tool calls.
    def _warm_cache():
        for key in _CHM_CONFIGS:
            try:
                _get_searcher(key)
            except (FileNotFoundError, RuntimeError) as e:
                print(f"chm-docs: [{key}] {e}", file=sys.stderr)

    threading.Thread(target=_warm_cache, daemon=True).start()

    mcp.run(transport="stdio")
