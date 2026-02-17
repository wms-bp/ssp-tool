"""
CHM extraction using vendored _chmlib C extension.

Replaces platform-specific external tools (extract_chmLib, 7z).
"""

import os
import _chmlib

# Enumeration flags (from chm_lib.h)
CHM_ENUMERATE_NORMAL = 1
CHM_ENUMERATE_FILES = 8
CHM_ENUMERATE_DIRS = 16
CHM_ENUMERATOR_CONTINUE = 1


def extract_chm(chm_path: str, output_dir: str) -> None:
    """Extract all files from a CHM archive to output_dir."""
    chm_path_bytes = os.fsencode(chm_path)
    handle = _chmlib.chm_open(chm_path_bytes)
    if handle is None:
        raise RuntimeError(f"Failed to open CHM file: {chm_path}")

    try:
        entries = []

        def collector(handle, ui, context):
            entries.append(ui)
            return CHM_ENUMERATOR_CONTINUE

        _chmlib.chm_enumerate(
            handle,
            CHM_ENUMERATE_NORMAL | CHM_ENUMERATE_FILES | CHM_ENUMERATE_DIRS,
            collector,
            None,
        )

        for start, length, space, flags, path_bytes in entries:
            path_str = path_bytes.decode("utf-8", errors="replace")

            # Skip empty paths and root
            if not path_str or path_str == "/":
                continue

            # Build output path — CHM paths use forward slashes
            rel_path = path_str.lstrip("/")
            out_path = os.path.join(output_dir, rel_path.replace("/", os.sep))

            # Directory entry (ends with /)
            if path_str.endswith("/"):
                os.makedirs(out_path, exist_ok=True)
                continue

            # File entry — resolve and retrieve content
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            if length == 0:
                # Empty file
                with open(out_path, "wb") as f:
                    pass
                continue

            data = _chmlib.chm_retrieve_object(
                handle, start, length, space, 0, length
            )
            if data is not None:
                with open(out_path, "wb") as f:
                    f.write(data)
    finally:
        _chmlib.chm_close(handle)
