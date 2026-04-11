#!/usr/bin/env python3
"""
CHM Documentation Search Tool

A CLI tool for searching and browsing CHM (Compiled HTML Help) documentation.
Designed for large SDK documentation files like SIMPL# Pro.
"""

import argparse
import html
import os
import re
import shutil
import sys
import tempfile
import json
from pathlib import Path
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import unquote
import sqlite3
import hashlib


class HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML content."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'head'}
        self.current_skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.skip_tags:
            self.current_skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.skip_tags and self.current_skip > 0:
            self.current_skip -= 1

    def handle_data(self, data):
        if self.current_skip == 0:
            text = data.strip()
            if text:
                self.text_parts.append(text)

    def get_text(self):
        return ' '.join(self.text_parts)


def html_to_text(html_content: str) -> str:
    """Convert HTML to plain text."""
    parser = HTMLTextExtractor()
    try:
        parser.feed(html_content)
        return parser.get_text()
    except:
        # Fallback: just strip tags
        return re.sub(r'<[^>]+>', ' ', html_content)


def extract_title(html_content: str) -> str:
    """Extract title from HTML content."""
    match = re.search(r'<title>([^<]+)</title>', html_content, re.IGNORECASE)
    if match:
        return html.unescape(match.group(1).strip())
    return "Untitled"


def extract_meta_info(html_content: str) -> dict:
    """Extract metadata from HTML content."""
    info = {}

    # Extract Help.Id
    match = re.search(r'name="Microsoft\.Help\.Id"\s+content="([^"]+)"', html_content)
    if match:
        info['help_id'] = match.group(1)

    # Extract container (namespace)
    match = re.search(r'name="container"\s+content="([^"]+)"', html_content)
    if match:
        info['namespace'] = match.group(1)

    # Extract keywords
    match = re.search(r'name="System\.Keywords"\s+content="([^"]+)"', html_content)
    if match:
        info['keywords'] = match.group(1)

    # Extract description
    match = re.search(r'name="Description"\s+content="([^"]+)"', html_content)
    if match:
        info['description'] = html.unescape(match.group(1))

    return info


def extract_links(html_content: str) -> list:
    """Extract internal documentation links from HTML content."""
    links = []
    # Match internal links like <a href="guid.htm">TypeName</a>
    # Exclude external links (https://, http://)
    pattern = r'<a\s+href="([a-f0-9\-]+\.htm)"[^>]*>([^<]+)</a>'

    for match in re.finditer(pattern, html_content, re.IGNORECASE):
        href = match.group(1)
        text = html.unescape(match.group(2).strip())
        # Clean up text (remove <wbr /> tags that might have been captured)
        text = re.sub(r'<[^>]+>', '', text)
        links.append({
            'path': f'html/{href}',
            'text': text
        })

    return links


def extract_code_signature(html_content: str) -> Optional[str]:
    """Extract the code signature from an HTML document."""
    # Look for the code block
    match = re.search(r'<pre[^>]*xml:space="preserve"[^>]*>(.*?)</pre>', html_content, re.DOTALL)
    if match:
        code = match.group(1)
        # Remove HTML tags but keep structure
        code = re.sub(r'<span[^>]*class="keyword"[^>]*>([^<]+)</span>', r'\1', code)
        code = re.sub(r'<span[^>]*class="identifier"[^>]*>([^<]+)</span>', r'\1', code)
        code = re.sub(r'<span[^>]*class="parameter"[^>]*>([^<]+)</span>', r'\1', code)
        code = re.sub(r'<[^>]+>', '', code)
        code = html.unescape(code).strip()
        return code
    return None


def extract_parameters(html_content: str) -> list:
    """Extract parameter information from delegate/method documentation."""
    params = []
    # Look for parameter definitions: <dt>paramName <a href="...">Type</a></dt><dd>description</dd>
    pattern = r'<dt[^>]*>.*?<span class="parameter">([^<]+)</span>\s*<a href="([^"]+)">([^<]+)</a>.*?</dt>\s*<dd>([^<]*)</dd>'

    for match in re.finditer(pattern, html_content, re.DOTALL | re.IGNORECASE):
        params.append({
            'name': match.group(1).strip(),
            'type_path': f'html/{match.group(2)}' if not match.group(2).startswith('http') else None,
            'type_name': html.unescape(match.group(3).strip()),
            'description': html.unescape(match.group(4).strip())
        })

    return params


def extract_return_type(html_content: str) -> Optional[dict]:
    """Extract return type information."""
    # Look for Value section (for events), Property Value, or Return Value section
    patterns = [
        r'<h4>Value</h4>\s*<a href="([^"]+)">([^<]+)</a>',
        r'<h4>Property Value</h4>\s*<a href="([^"]+)">([^<]+)</a>',
        r'<h4>Field Value</h4>\s*<a href="([^"]+)">([^<]+)</a>',
        r'<h4>Return Value</h4>.*?<a href="([^"]+)">([^<]+)</a>',
    ]

    for pattern in patterns:
        match = re.search(pattern, html_content, re.DOTALL)
        if match:
            href = match.group(1)
            return {
                'path': f'html/{href}' if not href.startswith('http') else None,
                'name': html.unescape(match.group(2).strip())
            }

    return None


def extract_properties_table(html_content: str) -> list:
    """Extract properties from a class documentation page."""
    props = []
    # Look for property table rows
    pattern = r'<tr><td>.*?</td><td><a href="([^"]+)">([^<]+)</a></td><td>\s*([^<]*)\s*</td></tr>'

    for match in re.finditer(pattern, html_content, re.DOTALL):
        props.append({
            'path': f'html/{match.group(1)}',
            'name': html.unescape(match.group(2).strip()),
            'description': html.unescape(match.group(3).strip())
        })

    return props


def extract_example(html_content: str) -> Optional[str]:
    """Extract code example from HTML content."""
    # Look for Example section followed by code block
    # Pattern: >Example</span>...followed by...<pre xml:space="preserve">CODE</pre>
    match = re.search(
        r'>Example</span>.*?<pre[^>]*xml:space="preserve"[^>]*>(.*?)</pre>',
        html_content,
        re.DOTALL | re.IGNORECASE
    )
    if match:
        code = match.group(1)
        # Remove HTML formatting tags but preserve structure
        code = re.sub(r'<span[^>]*class="highlight-comment"[^>]*>([^<]*)</span>', r'// \1', code)
        code = re.sub(r'<span[^>]*class="highlight-keyword"[^>]*>([^<]*)</span>', r'\1', code)
        code = re.sub(r'<span[^>]*class="highlight-literal"[^>]*>([^<]*)</span>', r'\1', code)
        code = re.sub(r'<span[^>]*class="highlight-number"[^>]*>([^<]*)</span>', r'\1', code)
        code = re.sub(r'<span[^>]*>([^<]*)</span>', r'\1', code)
        code = re.sub(r'<[^>]+>', '', code)
        code = html.unescape(code)
        return code.strip()
    return None


def has_example(html_content: str) -> bool:
    """Check if HTML content has an example section."""
    return '>Example</span>' in html_content


def extract_enum_members(html_content: str) -> list:
    """Extract enumeration member values from the enumMemberList table."""
    members = []
    # Look for the enum members table
    table_match = re.search(
        r'<table[^>]*id="enumMemberList"[^>]*>(.*?)</table>',
        html_content, re.DOTALL | re.IGNORECASE
    )
    if not table_match:
        return members

    table_html = table_match.group(1)

    # Extract rows (skip header row)
    rows = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL)
    for row in rows:
        cols = re.findall(r'<td>(.*?)</td>', row, re.DOTALL)
        if len(cols) >= 2:
            name = html_to_text(cols[0]).strip()
            value = html_to_text(cols[1]).strip()
            description = html_to_text(cols[2]).strip() if len(cols) >= 3 else ''
            if name and name != 'Member name':  # Skip header if captured
                members.append({
                    'name': name,
                    'value': value,
                    'description': description
                })

    return members


def get_type_category(help_id: str, title: str = '') -> str:
    """Determine the type category from help_id and/or title."""
    if not help_id and not title:
        return 'unknown'

    # Check title for explicit type suffix
    if title.endswith(' Enumeration'):
        return 'enum'

    if help_id.startswith('T:'):
        if 'Delegate' in help_id or 'Handler' in help_id or 'Callback' in help_id:
            return 'delegate'
        if 'EventArgs' in help_id:
            return 'eventargs'
        if 'Enum' in help_id:
            return 'enum'
        return 'class'
    elif help_id.startswith('E:'):
        return 'event'
    elif help_id.startswith('P:'):
        return 'property'
    elif help_id.startswith('M:'):
        return 'method'
    elif help_id.startswith('F:'):
        return 'field'
    return 'unknown'


# ---------------------------------------------------------------------------
# SIMPL Windows extraction helpers
# ---------------------------------------------------------------------------

def detect_chm_type(extract_dir: Path) -> str:
    """Detect whether an extracted CHM is SIMPLSharpPro or SIMPL_Windows."""
    if (extract_dir / 'html').is_dir():
        return 'simplsharp_pro'
    if (extract_dir / 'Device_Library').is_dir():
        return 'simpl_windows'
    return 'unknown'


def extract_toc_path(html_content: str) -> str:
    """Extract MadCap:tocPath from the <html> tag."""
    match = re.search(r'MadCap:tocPath="([^"]*)"', html_content)
    if match:
        return html.unescape(match.group(1))
    return ''


def extract_signals_from_table(html_content: str) -> list:
    """Extract signal definitions from SIMPL Windows signal tables.

    Parses two-column tables whose header contains 'signal' (case-insensitive).
    Returns a list of dicts with keys: name, signal_type, description.
    """
    signals = []

    # Split into tables
    table_blocks = re.findall(r'<table[^>]*>(.*?)</table>', html_content, re.DOTALL | re.IGNORECASE)
    for table_html in table_blocks:
        # Check if this table has a signal header (tolerating newlines/whitespace)
        header_text = ''
        first_row = re.search(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
        if first_row:
            header_text = html_to_text(first_row.group(1)).lower()
        if 'signal' not in header_text:
            continue

        # Extract data rows (skip the header row)
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
        for row in rows[1:]:  # skip header
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
            if len(cells) < 2:
                continue

            sig_cell_html = cells[0]
            desc_cell_html = cells[1]

            sig_cell_text = html_to_text(sig_cell_html).strip()
            description = html_to_text(desc_cell_html).strip()

            parsed = _parse_signal_cell(sig_cell_text, sig_cell_html)
            for sig in parsed:
                sig['description'] = description
                signals.append(sig)

    return signals


# Regex for matching signal type/direction prefix
_SIG_TYPE_RE = re.compile(
    r'(Digital|Analog|Serial)\s+(input|output)s?\s*:', re.IGNORECASE
)
_PARAM_TYPE_RE = re.compile(r'Parameters?\s*:', re.IGNORECASE)


def _parse_signal_cell(text: str, html_content: str) -> list:
    """Parse a single signal-name-and-type table cell.

    Returns a list of signal dicts (one cell can list multiple signals).
    Each dict has keys: name, signal_type (no description yet).
    """
    results = []

    # Determine signal type from the text prefix
    sig_match = _SIG_TYPE_RE.search(text)
    param_match = _PARAM_TYPE_RE.search(text)

    if sig_match:
        data_type = sig_match.group(1).lower()       # digital/analog/serial
        direction = sig_match.group(2).lower()        # input/output
        signal_type = f'{data_type}_{direction}'
    elif param_match:
        signal_type = 'parameter'
    else:
        return results

    # Extract signal names from angle-bracket delimited regions in HTML.
    # The HTML uses literal &lt; &gt; or < > around signal names.
    # Within those brackets, the name may be split across multiple bold spans
    # e.g. <span bold>Level</span> <span bold>_Out</span> — we merge them.
    names = []

    # Strategy: find angle-bracket regions, strip inner HTML tags, get clean name
    # Match &lt;...&gt; or literal < > regions that contain bold text
    bracket_pattern = re.compile(
        r'(?:&lt;|<(?!/?(?:span|b|p|td|tr|table|a|img|br)\b))\s*(.*?)\s*(?:&gt;|>(?!\s*</(?:span|b)))',
        re.DOTALL | re.IGNORECASE
    )
    # Simpler approach: extract text between &lt; and &gt; from HTML
    angle_regions = re.findall(r'&lt;\s*(.*?)\s*&gt;', html_content, re.DOTALL | re.IGNORECASE)
    for region in angle_regions:
        # Strip HTML tags from within the region to merge split spans
        clean = re.sub(r'<[^>]+>', '', region).strip()
        # Collapse whitespace
        clean = re.sub(r'\s+', '', clean)
        if clean and clean.lower() not in ('signal name and type', 'signal', 'description', ''):
            names.append(clean)

    # Fallback: try bold spans directly
    if not names:
        bold_pattern = re.compile(
            r'<(?:span|b)[^>]*font-weight:\s*bold[^>]*>([^<]+)</(?:span|b)>'
            r'|<b[^>]*>([^<]+)</b>'
            r'|<b\s+class="[^"]*join[^"]*">([^<]+)</b>',
            re.IGNORECASE
        )
        for m in bold_pattern.finditer(html_content):
            name = (m.group(1) or m.group(2) or m.group(3) or '').strip()
            if name and name.lower() not in ('signal name and type', 'signal', 'description'):
                names.append(name)

    # Fallback: extract from plain text angle brackets  <Name>
    if not names:
        for m in re.finditer(r'<([A-Za-z0-9_$#\-\s]+)>', text):
            n = m.group(1).strip()
            if n and n.lower() not in ('signal name and type', 'signal', 'description'):
                names.append(n)

    # Handle "through" ranges: keep both endpoints as a single entry
    if not names:
        results.append({'name': text.strip(), 'signal_type': signal_type})
    else:
        # Check for range pattern in text
        if 'through' in text.lower() and len(names) >= 2:
            # Group into range pairs
            range_match = re.search(
                r'<[^>]*?([A-Za-z_]+[\-_]?\d+)[^>]*>.*?through.*?<[^>]*?([A-Za-z_]+[\-_]?\d+)[^>]*>',
                text, re.IGNORECASE
            )
            if range_match and len(names) == 2:
                results.append({
                    'name': f'{names[0]} through {names[1]}',
                    'signal_type': signal_type
                })
            else:
                for name in names:
                    results.append({'name': name, 'signal_type': signal_type})
        else:
            for name in names:
                results.append({'name': name, 'signal_type': signal_type})

    return results


def extract_slot_links(html_content: str) -> list:
    """Extract slot references from device overview pages.

    Matches patterns like:
      Slot 01: <a href="...">Dimmer Controls</a>
      Slot-01: <a href="...">Dimmer Controls</a>
    """
    slots = []
    # Match "Slot XX:" or "Slot-XX:" followed by a link (possibly with URL-encoded spaces)
    pattern = re.compile(
        r'Slot[\s\-_]+(\d+)\s*:\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>',
        re.IGNORECASE
    )
    for m in pattern.finditer(html_content):
        name = html.unescape(m.group(3).strip())
        # Clean up whitespace/newlines in names
        name = re.sub(r'\s+', ' ', name).strip()
        slots.append({
            'slot_number': int(m.group(1)),
            'href': html.unescape(m.group(2)),
            'name': name
        })
    return slots


class CHMSearch:
    """Main CHM search functionality."""

    def __init__(self, chm_path: str, cache_dir: Optional[str] = None):
        self.chm_path = Path(chm_path).resolve()
        if not self.chm_path.exists():
            raise FileNotFoundError(f"CHM file not found: {chm_path}")

        # Set up cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / '.cache' / 'chm-search'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Create a hash-based directory for this specific CHM
        chm_hash = hashlib.md5(str(self.chm_path).encode()).hexdigest()[:12]
        self.extract_dir = self.cache_dir / f"chm_{chm_hash}"

        self.db_path = self.extract_dir / "index.db"
        self.toc = []
        self.keywords = {}

    def ensure_extracted(self):
        """Ensure CHM content is extracted."""
        if not self.extract_dir.exists():
            print("Extracting CHM file to cache... (this may take a moment)", file=sys.stderr)
            self.extract_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._extract_chm()
            except Exception:
                # Clean up partial extraction on failure
                shutil.rmtree(self.extract_dir, ignore_errors=True)
                raise
            print("Extraction complete.", file=sys.stderr)

    def _extract_chm(self):
        """Extract CHM using vendored chmlib C extension."""
        from chmextract import extract_chm
        extract_chm(str(self.chm_path), str(self.extract_dir))

    def get_file_content(self, relative_path: str) -> Optional[str]:
        """Get content of a file from the extracted CHM."""
        self.ensure_extracted()
        file_path = self.extract_dir / relative_path.lstrip('/')
        if file_path.exists():
            try:
                return file_path.read_text(encoding='utf-8', errors='replace')
            except:
                return file_path.read_bytes().decode('utf-8', errors='replace')
        return None

    def build_index(self, force: bool = False):
        """Build the search index from CHM content."""
        self.ensure_extracted()

        if self.db_path.exists() and not force:
            try:
                conn = sqlite3.connect(str(self.db_path))
                count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                conn.close()
                if count > 0:
                    print("Using existing index. Use --rebuild to force rebuild.", file=sys.stderr)
                    return
            except Exception:
                pass

        print("Building search index...", file=sys.stderr)

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        # --- common schema ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                title TEXT,
                namespace TEXT,
                help_id TEXT,
                keywords TEXT,
                content TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON documents(title)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_namespace ON documents(namespace)')

        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title, namespace, keywords, content,
                content='documents',
                content_rowid='id'
            )
        ''')

        # --- SIMPL Windows signal / slot tables (empty for S#Pro) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY,
                document_id INTEGER REFERENCES documents(id),
                signal_name TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                description TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_name ON signals(signal_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_doc ON signals(document_id)')

        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS signals_fts USING fts5(
                signal_name, description,
                content='signals',
                content_rowid='id'
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_slots (
                id INTEGER PRIMARY KEY,
                parent_document_id INTEGER REFERENCES documents(id),
                slot_number INTEGER,
                slot_name TEXT,
                slot_path TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_slots_parent ON device_slots(parent_document_id)')

        # Clear existing data
        cursor.execute('DELETE FROM documents')
        cursor.execute('DELETE FROM documents_fts')
        cursor.execute('DELETE FROM signals')
        cursor.execute('DELETE FROM signals_fts')
        cursor.execute('DELETE FROM device_slots')

        # Dispatch by CHM type
        chm_type = detect_chm_type(self.extract_dir)
        self.chm_type = chm_type

        if chm_type == 'simpl_windows':
            total = self._build_index_simpl_windows(cursor)
        else:
            total = self._build_index_spro(cursor)

        # Populate document FTS
        cursor.execute('''
            INSERT INTO documents_fts(rowid, title, namespace, keywords, content)
            SELECT id, title, namespace, keywords, content FROM documents
        ''')

        # Populate signal FTS (may be empty for S#Pro)
        cursor.execute('''
            INSERT INTO signals_fts(rowid, signal_name, description)
            SELECT id, signal_name, description FROM signals
        ''')

        conn.commit()
        conn.close()
        print(f"Index built with {total} documents.", file=sys.stderr)

    def _build_index_spro(self, cursor) -> int:
        """Index SIMPLSharpPro CHM (flat html/ directory with GUID files)."""
        html_dir = self.extract_dir / 'html'
        if not html_dir.exists():
            print("Warning: No html directory found in extracted CHM", file=sys.stderr)
            return 0

        htm_files = list(html_dir.glob('*.htm')) + list(html_dir.glob('*.html'))
        total = len(htm_files)

        for i, htm_file in enumerate(htm_files):
            if (i + 1) % 1000 == 0:
                print(f"  Indexed {i + 1}/{total} files...", file=sys.stderr)

            try:
                content = htm_file.read_text(encoding='utf-8', errors='replace')
                title = extract_title(content)
                meta = extract_meta_info(content)
                text = html_to_text(content)

                cursor.execute('''
                    INSERT INTO documents (path, title, namespace, help_id, keywords, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    f"html/{htm_file.name}",
                    title,
                    meta.get('namespace', ''),
                    meta.get('help_id', ''),
                    meta.get('keywords', ''),
                    text
                ))

            except Exception as e:
                print(f"Warning: Failed to index {htm_file.name}: {e}", file=sys.stderr)

        return total

    # Directories containing device documentation in SIMPL_Windows.chm
    _SIMPL_WINDOWS_DIRS = ('Device_Library', 'Cards', 'ACards_DM')

    def _build_index_simpl_windows(self, cursor) -> int:
        """Index SIMPL_Windows CHM (nested device directories with signal tables)."""
        htm_files = []
        for subdir in self._SIMPL_WINDOWS_DIRS:
            d = self.extract_dir / subdir
            if d.is_dir():
                htm_files.extend(d.rglob('*.htm'))
                htm_files.extend(d.rglob('*.html'))

        total = len(htm_files)
        signal_count = 0
        slot_count = 0

        for i, htm_file in enumerate(htm_files):
            if (i + 1) % 500 == 0:
                print(f"  Indexed {i + 1}/{total} files...", file=sys.stderr)

            try:
                content = htm_file.read_text(encoding='utf-8', errors='replace')
                title = extract_title(content)
                toc_path = extract_toc_path(content)
                text = html_to_text(content)

                # Build relative path from extract_dir
                rel_path = str(htm_file.relative_to(self.extract_dir))

                # Extract signals for keyword generation
                signals = extract_signals_from_table(content)
                sig_names = ' '.join(s['name'] for s in signals)

                cursor.execute('''
                    INSERT INTO documents (path, title, namespace, help_id, keywords, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    rel_path,
                    title,
                    toc_path,
                    '',  # no help_id for SIMPL Windows
                    sig_names,
                    text
                ))
                doc_id = cursor.lastrowid

                # Insert signals
                for sig in signals:
                    cursor.execute('''
                        INSERT INTO signals (document_id, signal_name, signal_type, description)
                        VALUES (?, ?, ?, ?)
                    ''', (doc_id, sig['name'], sig['signal_type'], sig.get('description', '')))
                    signal_count += 1

                # Insert slot links
                slots = extract_slot_links(content)
                for slot in slots:
                    # Resolve slot href relative to the current file
                    # URL-decode the href first (e.g. %20 -> space)
                    decoded_href = unquote(slot['href'])
                    slot_path = str((htm_file.parent / decoded_href).resolve().relative_to(self.extract_dir))
                    cursor.execute('''
                        INSERT INTO device_slots (parent_document_id, slot_number, slot_name, slot_path)
                        VALUES (?, ?, ?, ?)
                    ''', (doc_id, slot['slot_number'], slot['name'], slot_path))
                    slot_count += 1

            except Exception as e:
                print(f"Warning: Failed to index {htm_file}: {e}", file=sys.stderr)

        print(f"  {signal_count} signals, {slot_count} slot links extracted.", file=sys.stderr)
        return total

    def parse_toc(self) -> list:
        """Parse the table of contents (HHC file)."""
        self.ensure_extracted()

        # Find HHC file
        hhc_files = list(self.extract_dir.glob('*.hhc'))
        if not hhc_files:
            return []

        content = hhc_files[0].read_text(encoding='utf-8', errors='replace')

        # Parse the HHC structure
        toc = []
        current_depth = 0
        stack = [toc]

        # Find all OBJECT entries with Name and Local params
        pattern = r'<OBJECT[^>]*>.*?<param\s+name="Name"\s+value="([^"]+)"[^>]*>.*?(?:<param\s+name="Local"\s+value="([^"]+)"[^>]*>)?.*?</OBJECT>'

        for match in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
            name = html.unescape(match.group(1))
            local = match.group(2) if match.group(2) else None

            entry = {'name': name, 'path': local, 'children': []}
            toc.append(entry)

        return toc

    def search(self, query: str, limit: int = 20) -> list:
        """Search the documentation."""
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Use FTS5 search
        results = []
        try:
            # Escape special FTS characters and handle the query
            safe_query = query.replace('"', '""')

            cursor.execute('''
                SELECT d.path, d.title, d.namespace, snippet(documents_fts, 3, '>>>', '<<<', '...', 50) as snippet
                FROM documents_fts
                JOIN documents d ON documents_fts.rowid = d.id
                WHERE documents_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            ''', (f'"{safe_query}"', limit))

            for row in cursor.fetchall():
                results.append({
                    'path': row[0],
                    'title': row[1],
                    'namespace': row[2],
                    'snippet': row[3]
                })
        except sqlite3.OperationalError:
            # Try simpler LIKE search as fallback
            cursor.execute('''
                SELECT path, title, namespace, substr(content, 1, 200) as snippet
                FROM documents
                WHERE title LIKE ? OR content LIKE ? OR namespace LIKE ?
                LIMIT ?
            ''', (f'%{query}%', f'%{query}%', f'%{query}%', limit))

            for row in cursor.fetchall():
                results.append({
                    'path': row[0],
                    'title': row[1],
                    'namespace': row[2],
                    'snippet': row[3]
                })

        conn.close()
        return results

    def search_title(self, query: str, limit: int = 20) -> list:
        """Search only in titles."""
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute('''
            SELECT path, title, namespace
            FROM documents
            WHERE title LIKE ?
            ORDER BY
                CASE WHEN title LIKE ? THEN 0 ELSE 1 END,
                length(title)
            LIMIT ?
        ''', (f'%{query}%', f'{query}%', limit))

        results = [{'path': row[0], 'title': row[1], 'namespace': row[2]} for row in cursor.fetchall()]
        conn.close()
        return results

    def list_namespaces(self) -> list:
        """List all namespaces in the documentation."""
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute('''
            SELECT DISTINCT namespace, COUNT(*) as count
            FROM documents
            WHERE namespace != ''
            GROUP BY namespace
            ORDER BY namespace
        ''')

        results = [{'namespace': row[0], 'count': row[1]} for row in cursor.fetchall()]
        conn.close()
        return results

    def browse_namespace(self, namespace: str, limit: int = 50) -> list:
        """Browse contents of a namespace."""
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute('''
            SELECT path, title
            FROM documents
            WHERE namespace LIKE ?
            ORDER BY title
            LIMIT ?
        ''', (f'%{namespace}%', limit))

        results = [{'path': row[0], 'title': row[1]} for row in cursor.fetchall()]
        conn.close()
        return results

    # ------------------------------------------------------------------
    # SIMPL Windows query methods
    # ------------------------------------------------------------------

    def search_signals(self, query: str, signal_type: Optional[str] = None,
                       limit: int = 20) -> list:
        """Search SIMPL Windows signal definitions by name or description."""
        self.ensure_extracted()
        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check if signals table has any data
        try:
            cnt = cursor.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        except Exception:
            conn.close()
            return []
        if cnt == 0:
            conn.close()
            return []

        safe_query = query.replace('"', '""')

        if signal_type:
            cursor.execute('''
                SELECT s.signal_name, s.signal_type, s.description,
                       d.title, d.path, d.namespace
                FROM signals_fts
                JOIN signals s ON signals_fts.rowid = s.id
                JOIN documents d ON s.document_id = d.id
                WHERE signals_fts MATCH ? AND s.signal_type = ?
                ORDER BY rank
                LIMIT ?
            ''', (f'"{safe_query}"', signal_type, limit))
        else:
            cursor.execute('''
                SELECT s.signal_name, s.signal_type, s.description,
                       d.title, d.path, d.namespace
                FROM signals_fts
                JOIN signals s ON signals_fts.rowid = s.id
                JOIN documents d ON s.document_id = d.id
                WHERE signals_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            ''', (f'"{safe_query}"', limit))

        results = []
        for row in cursor.fetchall():
            results.append({
                'signal_name': row[0],
                'signal_type': row[1],
                'description': row[2],
                'document_title': row[3],
                'path': row[4],
                'namespace': row[5],
            })

        conn.close()
        return results

    def get_device_signals(self, device_name: str) -> Optional[dict]:
        """Get all signals for a SIMPL Windows device, grouped by slot."""
        self.ensure_extracted()
        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Find the device document by title (prefer overview pages)
        cursor.execute('''
            SELECT id, path, title, namespace, content
            FROM documents
            WHERE title LIKE ?
            ORDER BY
                CASE
                    WHEN title = ? THEN 0
                    WHEN title LIKE ? || ',%' OR title LIKE ? || ' &%' THEN 1
                    WHEN title LIKE ? THEN 2
                    ELSE 3
                END,
                length(title)
            LIMIT 1
        ''', (f'%{device_name}%', device_name,
              device_name, device_name, f'{device_name}%'))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        doc_id, doc_path, doc_title, namespace, doc_content = row

        result = {
            'title': doc_title,
            'path': doc_path,
            'namespace': namespace,
            'description': '',
            'signals': [],
            'slots': [],
        }

        # Get device description (first paragraph of plain text)
        content = self.get_file_content(doc_path)
        if content:
            text = html_to_text(content)
            # Take first few sentences as description
            sentences = text.split('.')
            result['description'] = '.'.join(sentences[:3]).strip() + '.' if sentences else ''

        # Get signals directly on this document
        cursor.execute('''
            SELECT signal_name, signal_type, description
            FROM signals WHERE document_id = ?
            ORDER BY
                CASE signal_type
                    WHEN 'digital_input' THEN 1
                    WHEN 'digital_output' THEN 2
                    WHEN 'analog_input' THEN 3
                    WHEN 'analog_output' THEN 4
                    WHEN 'serial_input' THEN 5
                    WHEN 'serial_output' THEN 6
                    WHEN 'parameter' THEN 7
                END
        ''', (doc_id,))
        for srow in cursor.fetchall():
            result['signals'].append({
                'name': srow[0], 'type': srow[1], 'description': srow[2]
            })

        # Get slots
        cursor.execute('''
            SELECT slot_number, slot_name, slot_path
            FROM device_slots WHERE parent_document_id = ?
            ORDER BY slot_number
        ''', (doc_id,))
        for srow in cursor.fetchall():
            slot = {
                'slot_number': srow[0],
                'slot_name': srow[1],
                'slot_path': srow[2],
                'signals': []
            }
            # Get signals for this slot's document
            cursor.execute('''
                SELECT s.signal_name, s.signal_type, s.description
                FROM signals s
                JOIN documents d ON s.document_id = d.id
                WHERE d.path = ?
                ORDER BY
                    CASE s.signal_type
                        WHEN 'digital_input' THEN 1
                        WHEN 'digital_output' THEN 2
                        WHEN 'analog_input' THEN 3
                        WHEN 'analog_output' THEN 4
                        WHEN 'serial_input' THEN 5
                        WHEN 'serial_output' THEN 6
                        WHEN 'parameter' THEN 7
                    END
            ''', (srow[2],))
            for sig in cursor.fetchall():
                slot['signals'].append({
                    'name': sig[0], 'type': sig[1], 'description': sig[2]
                })
            result['slots'].append(slot)

        conn.close()
        return result

    def show(self, path: str, raw: bool = False) -> Optional[str]:
        """Show the content of a specific document."""
        content = self.get_file_content(path)
        if not content:
            return None

        if raw:
            return content

        # Extract useful information
        title = extract_title(content)
        meta = extract_meta_info(content)
        text = html_to_text(content)

        output = []
        output.append(f"Title: {title}")
        if meta.get('namespace'):
            output.append(f"Namespace: {meta['namespace']}")
        if meta.get('help_id'):
            output.append(f"API: {meta['help_id']}")
        output.append("")
        output.append(text)

        return '\n'.join(output)

    def get_class_info(self, class_name: str) -> dict:
        """Get comprehensive information about a class including all its members."""
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Find the main class documentation
        cursor.execute('''
            SELECT path, title, namespace, help_id
            FROM documents
            WHERE title LIKE ? AND title NOT LIKE '%.%'
            ORDER BY
                CASE WHEN title = ? THEN 0
                     WHEN title = ? || ' Class' THEN 1
                     ELSE 2 END,
                length(title)
            LIMIT 1
        ''', (f'%{class_name}%', class_name, class_name))

        main_doc = cursor.fetchone()
        if not main_doc:
            # Try searching for exact class name in help_id
            cursor.execute('''
                SELECT path, title, namespace, help_id
                FROM documents
                WHERE help_id LIKE ?
                ORDER BY length(title)
                LIMIT 1
            ''', (f'T:%{class_name}',))
            main_doc = cursor.fetchone()

        if not main_doc:
            conn.close()
            return None

        class_info = {
            'main': {'path': main_doc[0], 'title': main_doc[1], 'namespace': main_doc[2], 'help_id': main_doc[3]},
            'constructors': [],
            'properties': [],
            'methods': [],
            'events': [],
            'fields': [],
            'operators': [],
            'other': []
        }

        # Get the base name for searching related docs
        base_name = main_doc[1].replace(' Class', '').strip()

        # Find related documentation
        cursor.execute('''
            SELECT path, title, help_id
            FROM documents
            WHERE (title LIKE ? OR title LIKE ?)
            AND title != ?
            ORDER BY title
        ''', (f'{base_name}.%', f'{base_name} %', main_doc[1]))

        for row in cursor.fetchall():
            path, title, help_id = row
            entry = {'path': path, 'title': title}

            # Categorize by type - check specific suffixes to avoid false matches
            # (e.g., "LoadEventIds" contains "event" but isn't an event)
            if title.endswith(' Constructor') or ' Constructor ' in title:
                class_info['constructors'].append(entry)
            elif title.endswith(' Property') or title.endswith(' Properties'):
                class_info['properties'].append(entry)
            elif title.endswith(' Method') or title.endswith(' Methods'):
                class_info['methods'].append(entry)
            elif title.endswith(' Event') or title.endswith(' Events'):
                class_info['events'].append(entry)
            elif title.endswith(' Field') or title.endswith(' Fields'):
                class_info['fields'].append(entry)
            elif title.endswith(' Operator') or title.endswith(' Operators'):
                class_info['operators'].append(entry)
            else:
                class_info['other'].append(entry)

        conn.close()
        return class_info

    def get_doc_by_path(self, path: str) -> Optional[dict]:
        """Get document info by path."""
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute('''
            SELECT path, title, namespace, help_id
            FROM documents
            WHERE path = ?
        ''', (path,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'path': row[0],
                'title': row[1],
                'namespace': row[2],
                'help_id': row[3]
            }
        return None

    def find_type(self, type_name: str) -> Optional[dict]:
        """Find a type by name and return its document info."""
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Try exact match first (with common suffixes)
        cursor.execute('''
            SELECT path, title, namespace, help_id
            FROM documents
            WHERE title = ? OR title = ? || ' Class' OR title = ? || ' Delegate'
                  OR title = ? || ' Interface' OR title = ? || ' Enumeration'
                  OR title = ? || ' Field' OR title = ? || ' Property'
                  OR title = ? || ' Event' OR title = ? || ' Method'
            ORDER BY length(title)
            LIMIT 1
        ''', (type_name, type_name, type_name, type_name, type_name,
              type_name, type_name, type_name, type_name))

        row = cursor.fetchone()
        if not row:
            # Try partial match with all member types (S#Pro style)
            cursor.execute('''
                SELECT path, title, namespace, help_id
                FROM documents
                WHERE (title LIKE ? OR help_id LIKE ?)
                AND (title LIKE '% Class' OR title LIKE '% Delegate'
                     OR title LIKE '% Interface' OR title LIKE '% Enumeration'
                     OR title LIKE '% Event' OR title LIKE '% Property'
                     OR title LIKE '% Method' OR title LIKE '% Field'
                     OR title LIKE '% Constructor')
                ORDER BY length(title)
                LIMIT 1
            ''', (f'%{type_name}%', f'%{type_name}%'))
            row = cursor.fetchone()

        if not row:
            # Try SIMPL Windows device name match (no suffix required).
            # Prefer: exact title → overview pages (title with commas/&) → starts-with
            cursor.execute('''
                SELECT path, title, namespace, help_id
                FROM documents
                WHERE title LIKE ?
                ORDER BY
                    CASE
                        WHEN title = ? THEN 0
                        WHEN title LIKE ? || ',%' OR title LIKE ? || ' &%' THEN 1
                        WHEN title LIKE ? THEN 2
                        ELSE 3
                    END,
                    length(title)
                LIMIT 1
            ''', (f'%{type_name}%', type_name,
                  type_name, type_name, f'{type_name}%'))
            row = cursor.fetchone()

        conn.close()

        if row:
            return {
                'path': row[0],
                'title': row[1],
                'namespace': row[2],
                'help_id': row[3]
            }
        return None

    def inspect(self, path_or_name: str) -> Optional[dict]:
        """
        Inspect a type/member and return detailed information including all references.
        This is the core method for understanding API relationships.
        For SIMPL Windows documents, returns signal definitions instead of code signatures.
        """
        self.ensure_extracted()

        # First, resolve the path
        if path_or_name.endswith('.htm'):
            # Determine if this is a SIMPL Windows path (not under html/)
            if path_or_name.startswith('html/'):
                path = path_or_name
            elif any(path_or_name.startswith(d) for d in ('Device_Library/', 'Cards/', 'ACards_DM/')):
                path = path_or_name
            else:
                path = f'html/{path_or_name}'
            doc_info = self.get_doc_by_path(path)
        else:
            doc_info = self.find_type(path_or_name)
            path = doc_info['path'] if doc_info else None

        if not doc_info:
            return None

        content = self.get_file_content(path)
        if not content:
            return None

        # Check if this is a SIMPL Windows document (has signals or is in device dirs)
        is_simpl_windows = any(
            path.startswith(d) for d in ('Device_Library/', 'Cards/', 'ACards_DM/')
        ) if path else False

        if is_simpl_windows:
            return self._inspect_simpl_windows(doc_info, content, path)

        # Standard S#Pro inspection
        result = {
            'title': doc_info['title'],
            'path': path,
            'namespace': doc_info.get('namespace', ''),
            'help_id': doc_info.get('help_id', ''),
            'category': get_type_category(doc_info.get('help_id', ''), doc_info.get('title', '')),
            'description': extract_meta_info(content).get('description', ''),
            'signature': extract_code_signature(content),
            'parameters': extract_parameters(content),
            'return_type': extract_return_type(content),
            'properties': extract_properties_table(content),
            'enum_members': extract_enum_members(content),
            'example': extract_example(content),
            'has_example': has_example(content),
            'references': [],
            'all_links': extract_links(content)
        }

        # Identify key referenced types
        seen_paths = set()
        for link in result['all_links']:
            if link['path'] not in seen_paths:
                seen_paths.add(link['path'])
                link_doc = self.get_doc_by_path(link['path'])
                if link_doc:
                    result['references'].append({
                        'path': link['path'],
                        'title': link_doc['title'],
                        'text': link['text'],
                        'category': get_type_category(link_doc.get('help_id', ''), link_doc.get('title', ''))
                    })

        return result

    def _inspect_simpl_windows(self, doc_info: dict, content: str, path: str) -> dict:
        """Build inspection result for a SIMPL Windows document."""
        signals = extract_signals_from_table(content)
        slots = extract_slot_links(content)
        toc_path = extract_toc_path(content)

        # Build description from first paragraph
        text = html_to_text(content)
        sentences = text.split('.')
        description = '.'.join(sentences[:3]).strip() + '.' if sentences else ''

        result = {
            'title': doc_info['title'],
            'path': path,
            'namespace': toc_path or doc_info.get('namespace', ''),
            'help_id': '',
            'category': 'device',
            'description': description,
            'signals': signals,
            'slots': [{'slot_number': s['slot_number'], 'name': s['name'],
                        'href': s['href']} for s in slots],
            # Keep empty S#Pro fields for compatibility
            'signature': None,
            'parameters': [],
            'return_type': None,
            'properties': [],
            'enum_members': [],
            'example': None,
            'has_example': False,
            'references': [],
            'all_links': [],
        }
        return result

    def traverse(self, start: str, depth: int = 2, follow_types: Optional[list] = None) -> dict:
        """
        Traverse the API documentation tree starting from a type.

        Args:
            start: Starting type name or path
            depth: How many levels to traverse (default 2)
            follow_types: List of categories to follow (e.g., ['delegate', 'eventargs', 'class'])
                         If None, follows all types

        Returns:
            A tree structure with the traversed types
        """
        if follow_types is None:
            follow_types = ['delegate', 'eventargs', 'class', 'interface', 'event', 'property', 'enum']

        visited = set()

        def traverse_node(path_or_name: str, current_depth: int) -> Optional[dict]:
            if current_depth <= 0:
                return None

            info = self.inspect(path_or_name)
            if not info:
                return None

            if info['path'] in visited:
                return {'_circular_ref': info['path'], 'title': info['title']}

            visited.add(info['path'])

            node = {
                'title': info['title'],
                'path': info['path'],
                'category': info['category'],
                'namespace': info['namespace'],
                'description': info['description'],
                'signature': info['signature'],
            }

            # Add parameters if present
            if info['parameters']:
                node['parameters'] = []
                for param in info['parameters']:
                    param_node = {
                        'name': param['name'],
                        'type': param['type_name'],
                        'description': param['description']
                    }
                    # Traverse parameter types
                    if param['type_path'] and current_depth > 1:
                        param_type_info = self.inspect(param['type_path'])
                        if param_type_info and param_type_info['category'] in follow_types:
                            param_node['type_details'] = traverse_node(param['type_path'], current_depth - 1)
                    node['parameters'].append(param_node)

            # Add return/value type if present
            if info['return_type'] and info['return_type']['path']:
                ret_info = self.inspect(info['return_type']['path'])
                if ret_info and ret_info['category'] in follow_types:
                    node['return_type'] = {
                        'name': info['return_type']['name'],
                        'details': traverse_node(info['return_type']['path'], current_depth - 1)
                    }
                else:
                    node['return_type'] = {'name': info['return_type']['name']}

            # Add enum members if this is an enum
            if info.get('enum_members') and info['category'] == 'enum':
                node['enum_members'] = info['enum_members']

            # Add properties if this is a class/eventargs with properties
            if info['properties'] and info['category'] in ('class', 'eventargs'):
                node['properties'] = []
                for prop in info['properties'][:10]:  # Limit to first 10
                    node['properties'].append({
                        'name': prop['name'],
                        'description': prop['description'],
                        'path': prop['path']
                    })

            return node

        return traverse_node(start, depth)

    def list_examples(self, namespace: Optional[str] = None, limit: int = 100) -> list:
        """
        List all documents that have code examples.

        Args:
            namespace: Optional namespace to filter by
            limit: Maximum number of results

        Returns:
            List of documents with examples
        """
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        # We need to check actual HTML files for examples since we don't index that
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        if namespace:
            cursor.execute('''
                SELECT path, title, namespace
                FROM documents
                WHERE namespace LIKE ?
                ORDER BY namespace, title
            ''', (f'%{namespace}%',))
        else:
            cursor.execute('''
                SELECT path, title, namespace
                FROM documents
                WHERE namespace != ''
                ORDER BY namespace, title
            ''')

        results = []
        for row in cursor.fetchall():
            if len(results) >= limit:
                break
            path, title, ns = row
            content = self.get_file_content(path)
            if content and has_example(content):
                results.append({
                    'path': path,
                    'title': title,
                    'namespace': ns
                })

        conn.close()
        return results

    def get_example(self, path_or_name: str) -> Optional[dict]:
        """
        Get the code example from a document.

        Args:
            path_or_name: Document path or type name

        Returns:
            Dict with title, path, and example code
        """
        self.ensure_extracted()

        # Resolve path
        if path_or_name.endswith('.htm'):
            path = path_or_name if path_or_name.startswith('html/') else f'html/{path_or_name}'
            doc_info = self.get_doc_by_path(path)
        else:
            doc_info = self.find_type(path_or_name)
            path = doc_info['path'] if doc_info else None

        if not doc_info:
            return None

        content = self.get_file_content(path)
        if not content:
            return None

        example_code = extract_example(content)
        if not example_code:
            return None

        return {
            'title': doc_info['title'],
            'path': path,
            'namespace': doc_info.get('namespace', ''),
            'example': example_code
        }

    def examples_by_namespace(self) -> dict:
        """
        Get a summary of examples grouped by namespace.

        Returns:
            Dict mapping namespace to count of examples
        """
        self.ensure_extracted()

        if not self.db_path.exists():
            self.build_index()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute('''
            SELECT DISTINCT namespace
            FROM documents
            WHERE namespace != ''
            ORDER BY namespace
        ''')

        namespaces = [row[0] for row in cursor.fetchall()]
        conn.close()

        results = {}
        for ns in namespaces:
            examples = self.list_examples(namespace=ns, limit=1000)
            if examples:
                results[ns] = len(examples)

        return results

    def api_chain(self, start: str, member_name: Optional[str] = None) -> dict:
        """
        Follow an API chain starting from a class, optionally focusing on a specific member.
        This is useful for understanding event handler flows.

        Example: api_chain("ClwDimswex", "LoadStateChange")
        Will show: ClwDimswex.LoadStateChange -> LoadEventHandler -> (LightingBase, LoadEventArgs) -> LoadEventArgs properties
        """
        result = {
            'start_class': start,
            'member': member_name,
            'chain': []
        }

        # Get the starting class
        class_info = self.inspect(start)
        if not class_info:
            return {'error': f'Class not found: {start}'}

        result['chain'].append({
            'level': 0,
            'type': 'class',
            'title': class_info['title'],
            'path': class_info['path'],
            'namespace': class_info['namespace']
        })

        # If a member is specified, find it
        if member_name:
            # Search for the member - try direct match first, then inherited
            self.ensure_extracted()
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            base_name = class_info['title'].replace(' Class', '').replace(' Interface', '').strip()

            # Try direct class member first
            cursor.execute('''
                SELECT path, title, help_id
                FROM documents
                WHERE title LIKE ?
                LIMIT 1
            ''', (f'{base_name}.{member_name}%',))

            row = cursor.fetchone()

            # If not found, try searching for any class with this member
            if not row:
                cursor.execute('''
                    SELECT path, title, help_id
                    FROM documents
                    WHERE title LIKE ?
                    ORDER BY length(title)
                    LIMIT 1
                ''', (f'%.{member_name} Event',))
                row = cursor.fetchone()

            if not row:
                cursor.execute('''
                    SELECT path, title, help_id
                    FROM documents
                    WHERE title LIKE ?
                    ORDER BY length(title)
                    LIMIT 1
                ''', (f'%.{member_name} Property',))
                row = cursor.fetchone()

            if not row:
                cursor.execute('''
                    SELECT path, title, help_id
                    FROM documents
                    WHERE title LIKE ?
                    ORDER BY length(title)
                    LIMIT 1
                ''', (f'%.{member_name} Method',))
                row = cursor.fetchone()

            if not row:
                cursor.execute('''
                    SELECT path, title, help_id
                    FROM documents
                    WHERE title LIKE ?
                    ORDER BY length(title)
                    LIMIT 1
                ''', (f'%.{member_name} Field',))
                row = cursor.fetchone()

            conn.close()

            if row:
                member_info = self.inspect(row[0])
                if member_info:
                    result['chain'].append({
                        'level': 1,
                        'type': member_info['category'],
                        'title': member_info['title'],
                        'path': member_info['path'],
                        'signature': member_info['signature'],
                        'description': member_info['description']
                    })

                    # Follow return/value type for events, properties, methods
                    if member_info['return_type'] and member_info['return_type']['path']:
                        handler_info = self.inspect(member_info['return_type']['path'])
                        if handler_info:
                            result['chain'].append({
                                'level': 2,
                                'type': handler_info['category'],
                                'title': handler_info['title'],
                                'path': handler_info['path'],
                                'signature': handler_info['signature'],
                                'description': handler_info['description']
                            })

                            # If it's a delegate, follow the parameters
                            if handler_info['category'] == 'delegate':
                                for param in handler_info['parameters']:
                                    if param['type_path']:
                                        param_info = self.inspect(param['type_path'])
                                        if param_info:
                                            param_entry = {
                                                'level': 3,
                                                'type': param_info['category'],
                                                'title': param_info['title'],
                                                'path': param_info['path'],
                                                'param_name': param['name'],
                                                'description': param_info['description']
                                            }

                                            # If it's an EventArgs class, include its properties
                                            if 'EventArgs' in param_info['title']:
                                                props = param_info.get('properties', [])
                                                if props:
                                                    param_entry['properties'] = props

                                            result['chain'].append(param_entry)

                            # If it's an enum, include enum members
                            elif handler_info['category'] == 'enum':
                                if handler_info.get('enum_members'):
                                    result['chain'][-1]['enum_members'] = handler_info['enum_members']

                            # If it's a class (return type of property/method), show its key info
                            elif handler_info['category'] in ('class', 'eventargs'):
                                if handler_info.get('properties'):
                                    result['chain'][-1]['properties'] = handler_info['properties'][:10]

        return result


def _print_signals(signals: list):
    """Print signals grouped by type (for CLI output)."""
    type_labels = {
        'digital_input': 'Digital Inputs',
        'digital_output': 'Digital Outputs',
        'analog_input': 'Analog Inputs',
        'analog_output': 'Analog Outputs',
        'serial_input': 'Serial Inputs',
        'serial_output': 'Serial Outputs',
        'parameter': 'Parameters',
    }
    grouped: dict = {}
    for s in signals:
        st = s.get('signal_type') or s.get('type', 'unknown')
        grouped.setdefault(st, []).append(s)

    for st in ('digital_input', 'digital_output', 'analog_input', 'analog_output',
               'serial_input', 'serial_output', 'parameter'):
        sigs = grouped.get(st, [])
        if not sigs:
            continue
        print(f"\n  {type_labels.get(st, st)}:")
        for s in sigs:
            name = s.get('name') or s.get('signal_name', '?')
            desc = s.get('description', '')
            print(f"    {name}: {desc}" if desc else f"    {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Search and browse CHM documentation files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s search "HttpClient"
  %(prog)s search "Connect" --limit 50
  %(prog)s title "Button"
  %(prog)s namespaces
  %(prog)s browse "Crestron.SimplSharp.Net"
  %(prog)s show html/abc123.htm
  %(prog)s rebuild
        '''
    )

    parser.add_argument('--chm', '-c', default='./SIMPLSharpPro.chm',
                        help='Path to CHM file (default: ./SIMPLSharpPro.chm)')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Search command
    search_parser = subparsers.add_parser('search', aliases=['s'], help='Full-text search')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('--limit', '-l', type=int, default=20, help='Max results')
    search_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Title search command
    title_parser = subparsers.add_parser('title', aliases=['t'], help='Search titles only')
    title_parser.add_argument('query', help='Search query')
    title_parser.add_argument('--limit', '-l', type=int, default=20, help='Max results')
    title_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Namespaces command
    ns_parser = subparsers.add_parser('namespaces', aliases=['ns'], help='List all namespaces')
    ns_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Browse namespace command
    browse_parser = subparsers.add_parser('browse', aliases=['b'], help='Browse namespace contents')
    browse_parser.add_argument('namespace', help='Namespace to browse')
    browse_parser.add_argument('--limit', '-l', type=int, default=50, help='Max results')
    browse_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Show document command
    show_parser = subparsers.add_parser('show', aliases=['read', 'r'], help='Show document content')
    show_parser.add_argument('path', help='Document path (e.g., html/abc123.htm)')
    show_parser.add_argument('--raw', action='store_true', help='Show raw HTML')

    # Rebuild index command
    rebuild_parser = subparsers.add_parser('rebuild', help='Rebuild the search index')

    # TOC command
    toc_parser = subparsers.add_parser('toc', help='Show table of contents')
    toc_parser.add_argument('--limit', '-l', type=int, default=50, help='Max entries')

    # Class command
    class_parser = subparsers.add_parser('class', aliases=['c'], help='Show class documentation with all members')
    class_parser.add_argument('class_name', help='Class name to look up')
    class_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Enum command - show enum values (shortcut for inspect on enums)
    enum_parser = subparsers.add_parser('enum', aliases=['e'], help='Show enumeration values')
    enum_parser.add_argument('type_name', help='Enum type name')
    enum_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Inspect command - detailed view of a single type with all references
    inspect_parser = subparsers.add_parser('inspect', aliases=['i'], help='Inspect a type/member with all references')
    inspect_parser.add_argument('type_name', help='Type name or document path to inspect')
    inspect_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Traverse command - follow the type tree
    traverse_parser = subparsers.add_parser('traverse', aliases=['tr'], help='Traverse the API tree from a starting type')
    traverse_parser.add_argument('start', help='Starting type name or path')
    traverse_parser.add_argument('--depth', '-d', type=int, default=2, help='Traversal depth (default: 2)')
    traverse_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # API chain command - follow an event/property chain
    api_parser = subparsers.add_parser('api', aliases=['a'], help='Follow an API chain (e.g., event handler flow)')
    api_parser.add_argument('class_name', help='Starting class name')
    api_parser.add_argument('member', nargs='?', help='Optional member name to focus on')
    api_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Examples command - list documents with code examples
    examples_parser = subparsers.add_parser('examples', aliases=['ex'], help='List documents with code examples')
    examples_parser.add_argument('namespace', nargs='?', help='Optional namespace to filter by')
    examples_parser.add_argument('--limit', '-l', type=int, default=50, help='Max results (default: 50)')
    examples_parser.add_argument('--verbose', '-v', action='store_true', help='Show file paths')
    examples_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Example command - get a specific code example
    example_parser = subparsers.add_parser('example', aliases=['eg'], help='Get code example from a document')
    example_parser.add_argument('type_name', help='Type name or document path')
    example_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    # Examples summary command - show examples count by namespace
    examples_summary_parser = subparsers.add_parser('examples-summary', aliases=['exs'],
                                                     help='Show count of examples by namespace')
    examples_summary_parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        chm = CHMSearch(args.chm)

        if args.command in ('search', 's'):
            results = chm.search(args.query, args.limit)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(results, indent=2))
            else:
                if not results:
                    print(f"No results found for '{args.query}'")
                else:
                    print(f"Found {len(results)} results for '{args.query}':\n")
                    for i, r in enumerate(results, 1):
                        print(f"{i}. {r['title']}")
                        if r.get('namespace'):
                            print(f"   Namespace: {r['namespace']}")
                        print(f"   Path: {r['path']}")
                        if r.get('snippet'):
                            snippet = r['snippet'].replace('>>>', '\033[1m').replace('<<<', '\033[0m')
                            print(f"   ...{snippet}...")
                        print()

        elif args.command in ('title', 't'):
            results = chm.search_title(args.query, args.limit)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(results, indent=2))
            else:
                if not results:
                    print(f"No titles found matching '{args.query}'")
                else:
                    print(f"Found {len(results)} titles matching '{args.query}':\n")
                    for i, r in enumerate(results, 1):
                        print(f"{i}. {r['title']}")
                        if r.get('namespace'):
                            print(f"   Namespace: {r['namespace']}")
                        print(f"   Path: {r['path']}")
                        print()

        elif args.command in ('namespaces', 'ns'):
            results = chm.list_namespaces()
            if hasattr(args, 'json') and args.json:
                print(json.dumps(results, indent=2))
            else:
                print(f"Found {len(results)} namespaces:\n")
                for r in results:
                    print(f"  {r['namespace']} ({r['count']} items)")

        elif args.command in ('browse', 'b'):
            results = chm.browse_namespace(args.namespace, args.limit)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(results, indent=2))
            else:
                if not results:
                    print(f"No items found in namespace '{args.namespace}'")
                else:
                    print(f"Found {len(results)} items in '{args.namespace}':\n")
                    for r in results:
                        print(f"  {r['title']}")
                        print(f"    Path: {r['path']}")

        elif args.command in ('show', 'read', 'r'):
            content = chm.show(args.path, args.raw)
            if content:
                print(content)
            else:
                print(f"Document not found: {args.path}")
                sys.exit(1)

        elif args.command == 'rebuild':
            chm.build_index(force=True)

        elif args.command == 'toc':
            toc = chm.parse_toc()
            for i, entry in enumerate(toc[:args.limit]):
                print(f"  {entry['name']}")
                if entry.get('path'):
                    print(f"    -> {entry['path']}")

        elif args.command in ('class', 'c'):
            # Check if it's an enum first - if so, redirect to enum display
            enum_check = chm.inspect(args.class_name)
            if enum_check and enum_check.get('category') == 'enum' and enum_check.get('enum_members'):
                if hasattr(args, 'json') and args.json:
                    print(json.dumps(enum_check, indent=2))
                else:
                    print(f"\n{'=' * 70}")
                    print(f"Enum: {enum_check['title']}")
                    print(f"Namespace: {enum_check['namespace']}")
                    if enum_check.get('description'):
                        print(f"Description: {enum_check['description']}")
                    print(f"{'=' * 70}")
                    if enum_check.get('signature'):
                        print(f"\nSignature: {enum_check['signature']}")
                    print(f"\nValues:")
                    max_name = max(len(m['name']) for m in enum_check['enum_members'])
                    max_val = max(len(m['value']) for m in enum_check['enum_members'])
                    for m in enum_check['enum_members']:
                        desc = f"  {m['description']}" if m.get('description') else ''
                        print(f"  {m['name']:<{max_name}}  = {m['value']:>{max_val}}{desc}")
                    print()
                sys.exit(0)

            info = chm.get_class_info(args.class_name)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(info, indent=2))
            else:
                if not info:
                    print(f"Class not found: {args.class_name}")
                    sys.exit(1)

                print(f"\n{'=' * 60}")
                print(f"Class: {info['main']['title']}")
                if info['main'].get('namespace'):
                    print(f"Namespace: {info['main']['namespace']}")
                print(f"Path: {info['main']['path']}")
                print(f"{'=' * 60}\n")

                sections = [
                    ('Constructors', info['constructors']),
                    ('Properties', info['properties']),
                    ('Methods', info['methods']),
                    ('Events', info['events']),
                    ('Fields', info['fields']),
                    ('Operators', info['operators']),
                    ('Other', info['other']),
                ]

                for section_name, items in sections:
                    if items:
                        print(f"\n{section_name}:")
                        print("-" * 40)
                        for item in items:
                            # Extract just the member name from the title
                            member_name = item['title'].replace(info['main']['title'].replace(' Class', ''), '').strip()
                            if member_name.startswith('.'):
                                member_name = member_name[1:]
                            print(f"  {item['title']}")
                            print(f"    Path: {item['path']}")

        elif args.command in ('enum', 'e'):
            info = chm.inspect(args.type_name)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(info, indent=2))
            else:
                if not info:
                    print(f"Enum not found: {args.type_name}")
                    sys.exit(1)

                print(f"\n{'=' * 70}")
                print(f"Enum: {info['title']}")
                print(f"Namespace: {info['namespace']}")
                if info.get('description'):
                    print(f"Description: {info['description']}")
                print(f"{'=' * 70}")

                if info.get('signature'):
                    print(f"\nSignature: {info['signature']}")

                if info.get('enum_members'):
                    print(f"\nValues:")
                    # Calculate column widths for alignment
                    max_name = max(len(m['name']) for m in info['enum_members'])
                    max_val = max(len(m['value']) for m in info['enum_members'])
                    for m in info['enum_members']:
                        desc = f"  {m['description']}" if m.get('description') else ''
                        print(f"  {m['name']:<{max_name}}  = {m['value']:>{max_val}}{desc}")
                else:
                    print("\nNo enum members found.")
                print()

        elif args.command in ('inspect', 'i'):
            info = chm.inspect(args.type_name)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(info, indent=2))
            else:
                if not info:
                    print(f"Type not found: {args.type_name}")
                    sys.exit(1)

                print(f"\n{'=' * 70}")
                print(f"Title: {info['title']}")
                print(f"Category: {info['category']}")
                print(f"Namespace: {info['namespace']}")
                print(f"Path: {info['path']}")
                if info.get('description'):
                    print(f"Description: {info['description']}")
                print(f"{'=' * 70}")

                if info.get('signature'):
                    print(f"\nSignature:")
                    print(f"  {info['signature']}")

                if info.get('parameters'):
                    print(f"\nParameters:")
                    for p in info['parameters']:
                        print(f"  {p['name']}: {p['type_name']}")
                        if p['type_path']:
                            print(f"    -> {p['type_path']}")
                        if p.get('description'):
                            print(f"    {p['description']}")

                if info.get('return_type'):
                    print(f"\nReturn/Value Type:")
                    print(f"  {info['return_type']['name']}")
                    if info['return_type'].get('path'):
                        print(f"  -> {info['return_type']['path']}")

                if info.get('enum_members'):
                    print(f"\nEnum Members:")
                    for m in info['enum_members']:
                        desc = f"  - {m.get('description', '')}" if m.get('description') else ''
                        print(f"  {m['name']} = {m['value']}{desc}")

                if info.get('properties'):
                    print(f"\nProperties:")
                    for p in info['properties'][:15]:
                        print(f"  {p['name']}: {p.get('description', '')[:60]}")
                        print(f"    -> {p['path']}")

                if info.get('references'):
                    print(f"\nReferenced Types ({len(info['references'])}):")
                    seen = set()
                    for r in info['references']:
                        if r['title'] not in seen:
                            seen.add(r['title'])
                            print(f"  [{r['category']}] {r['title']}")
                            print(f"    -> {r['path']}")

                # SIMPL Windows signal/slot data
                if info.get('signals'):
                    print(f"\nSignals:")
                    print("-" * 40)
                    _print_signals(info['signals'])

                if info.get('slots'):
                    print(f"\nProgramming Slots:")
                    for s in info['slots']:
                        print(f"  Slot {s['slot_number']:02d}: {s['name']}")
                        if s.get('href'):
                            print(f"    -> {s['href']}")

                if info.get('has_example'):
                    print(f"\n*** This document has a CODE EXAMPLE ***")
                    print(f"    Use: ./chm example \"{info['title']}\"")

        elif args.command in ('traverse', 'tr'):
            tree = chm.traverse(args.start, args.depth)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(tree, indent=2))
            else:
                if not tree:
                    print(f"Type not found: {args.start}")
                    sys.exit(1)

                def print_tree(node, indent=0):
                    prefix = "  " * indent
                    if node.get('_circular_ref'):
                        print(f"{prefix}[circular] -> {node['title']}")
                        return

                    cat = f"[{node.get('category', '?')}]"
                    print(f"{prefix}{cat} {node['title']}")
                    if node.get('signature'):
                        sig = node['signature'][:80] + "..." if len(node.get('signature', '')) > 80 else node.get('signature', '')
                        print(f"{prefix}  Sig: {sig}")

                    if node.get('parameters'):
                        print(f"{prefix}  Parameters:")
                        for p in node['parameters']:
                            print(f"{prefix}    - {p['name']}: {p['type']}")
                            if p.get('type_details'):
                                print_tree(p['type_details'], indent + 3)

                    if node.get('return_type'):
                        print(f"{prefix}  Returns: {node['return_type']['name']}")
                        if node['return_type'].get('details'):
                            print_tree(node['return_type']['details'], indent + 2)

                    if node.get('enum_members'):
                        print(f"{prefix}  Values:")
                        for m in node['enum_members']:
                            print(f"{prefix}    {m['name']} = {m['value']}")

                    if node.get('properties'):
                        print(f"{prefix}  Properties:")
                        for p in node['properties'][:5]:
                            print(f"{prefix}    - {p['name']}")

                print_tree(tree)

        elif args.command in ('api', 'a'):
            chain = chm.api_chain(args.class_name, args.member if hasattr(args, 'member') else None)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(chain, indent=2))
            else:
                if chain.get('error'):
                    print(f"Error: {chain['error']}")
                    sys.exit(1)

                print(f"\n{'=' * 70}")
                print(f"API Chain: {chain['start_class']}")
                if chain.get('member'):
                    print(f"Member: {chain['member']}")
                print(f"{'=' * 70}\n")

                for item in chain['chain']:
                    indent = "  " * item['level']
                    arrow = "└─>" if item['level'] > 0 else ""
                    print(f"{indent}{arrow} [{item['type']}] {item['title']}")
                    print(f"{indent}    Path: {item['path']}")

                    if item.get('signature'):
                        sig = item['signature']
                        if len(sig) > 70:
                            sig = sig[:70] + "..."
                        print(f"{indent}    Signature: {sig}")

                    if item.get('description'):
                        desc = item['description'][:100]
                        print(f"{indent}    Description: {desc}")

                    if item.get('param_name'):
                        print(f"{indent}    (Parameter: {item['param_name']})")

                    if item.get('enum_members'):
                        print(f"{indent}    Values:")
                        for m in item['enum_members']:
                            desc = f"  - {m.get('description', '')}" if m.get('description') else ''
                            print(f"{indent}      {m['name']} = {m['value']}{desc}")

                    if item.get('properties'):
                        print(f"{indent}    Properties:")
                        for p in item['properties'][:8]:
                            print(f"{indent}      - {p['name']}: {p.get('description', '')[:50]}")

                    print()

        elif args.command in ('examples', 'ex'):
            ns = args.namespace if hasattr(args, 'namespace') else None
            results = chm.list_examples(namespace=ns, limit=args.limit)
            verbose = hasattr(args, 'verbose') and args.verbose
            if hasattr(args, 'json') and args.json:
                print(json.dumps(results, indent=2))
            else:
                if not results:
                    if ns:
                        print(f"No examples found in namespace '{ns}'")
                    else:
                        print("No examples found")
                else:
                    if ns:
                        print(f"\nFound {len(results)} documents with examples in '{ns}':\n")
                    else:
                        print(f"\nFound {len(results)} documents with examples:\n")
                    print("Use: ./chm example \"<Title>\" to view example code\n")

                    current_ns = None
                    for r in results:
                        if r['namespace'] != current_ns:
                            current_ns = r['namespace']
                            print(f"\n  [{current_ns}]")
                        print(f"    {r['title']}")
                        if verbose:
                            print(f"      Path: {r['path']}")

        elif args.command in ('example', 'eg'):
            result = chm.get_example(args.type_name)
            if hasattr(args, 'json') and args.json:
                print(json.dumps(result, indent=2))
            else:
                if not result:
                    print(f"No example found for: {args.type_name}")
                    sys.exit(1)

                print(f"\n{'=' * 70}")
                print(f"Example: {result['title']}")
                print(f"Namespace: {result['namespace']}")
                print(f"Path: {result['path']}")
                print(f"{'=' * 70}\n")
                print(result['example'])
                print()

        elif args.command in ('examples-summary', 'exs'):
            results = chm.examples_by_namespace()
            if hasattr(args, 'json') and args.json:
                print(json.dumps(results, indent=2))
            else:
                print(f"\nNamespaces with code examples:\n")
                total = 0
                for ns, count in sorted(results.items()):
                    print(f"  {ns}: {count} examples")
                    total += count
                print(f"\nTotal: {total} examples across {len(results)} namespaces")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
