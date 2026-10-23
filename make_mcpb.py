#!/usr/bin/env python3
"""
Package PyInstaller builds of chm-docs as an MCP bundle (.mcpb).

An .mcpb file is a zip with manifest.json at the root. Claude Desktop installs
it as an extension, and a Claude Code plugin can point its mcpServers at it.

Usage:
    python make_mcpb.py --windows dist/chm-docs                 # Windows only
    python make_mcpb.py --macos dist/chm-docs                   # macOS only
    python make_mcpb.py --windows win/chm-docs --macos mac/chm-docs   # both
"""

import argparse
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# platform name in the manifest -> (folder in the bundle, executable name)
PLATFORMS = {
    'win32': ('windows', 'chm-docs.exe'),
    'darwin': ('macos', 'chm-docs'),
}


def build_manifest(platforms: list[str], version: str) -> dict:
    """Fill in the version and point the server at the included builds."""
    manifest = json.loads((SCRIPT_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest["compatibility"]["platforms"] = platforms

    # The first platform is the default command, the others are overrides
    mcp_config = manifest["server"]["mcp_config"]
    folder, exe = PLATFORMS[platforms[0]]
    manifest["server"]["entry_point"] = f"server/{folder}/{exe}"
    mcp_config["command"] = f"${{__dirname}}/server/{folder}/{exe}"
    mcp_config["platform_overrides"] = {}
    for platform in platforms[1:]:
        folder, exe = PLATFORMS[platform]
        mcp_config["platform_overrides"][platform] = {
            "command": f"${{__dirname}}/server/{folder}/{exe}"}
    if not mcp_config["platform_overrides"]:
        del mcp_config["platform_overrides"]
    return manifest


def add_build(zf: zipfile.ZipFile, build_dir: Path, platform: str):
    """Add a PyInstaller --onedir folder under server/<platform folder>/."""
    folder, exe = PLATFORMS[platform]
    if not (build_dir / exe).is_file():
        sys.exit(f"ERROR: {build_dir / exe} not found")
    # Symlinks (in macOS builds) are stored as copies, since not every
    # .mcpb extractor restores them
    paths = [Path(root) / name
             for root, _, names in os.walk(build_dir, followlinks=True) for name in names]
    for path in sorted(paths):
        arcname = f"server/{folder}/{path.relative_to(build_dir).as_posix()}"
        info = zipfile.ZipInfo.from_file(path, arcname)
        info.compress_type = zipfile.ZIP_DEFLATED
        if path.name == exe:
            # Keep the launcher executable on macOS, also when zipped on Windows
            info.external_attr = (stat.S_IFREG | 0o755) << 16
        with open(path, "rb") as f:
            zf.writestr(info, f.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--windows", type=Path, help="PyInstaller output folder for Windows")
    parser.add_argument("--macos", type=Path, help="PyInstaller output folder for macOS")
    parser.add_argument("-o", "--output", type=Path, help="Output .mcpb file")
    args = parser.parse_args()

    builds = {p: d for p, d in (('darwin', args.macos), ('win32', args.windows)) if d}
    if not builds:
        parser.error("give --windows and/or --macos")

    version = (SCRIPT_DIR / "VERSION").read_text().strip()
    if args.output:
        output = args.output
    elif len(builds) == 1:
        output = Path(f"chm-docs-{version}-{PLATFORMS[next(iter(builds))][0]}.mcpb")
    else:
        output = Path(f"chm-docs-{version}.mcpb")

    manifest = build_manifest(list(builds), version)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        zf.write(SCRIPT_DIR / "LICENSE", "LICENSE")
        for platform, build_dir in builds.items():
            add_build(zf, build_dir, platform)

    print(f"Created {output} ({output.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
