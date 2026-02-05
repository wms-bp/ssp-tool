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
import subprocess
import sys
import tempfile
import json
from pathlib import Path
from html.parser import HTMLParser
from typing import Optional
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

    return info


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
            print(f"Extracting CHM file to cache... (this may take a moment)")
            self.extract_dir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ['extract_chmLib', str(self.chm_path), str(self.extract_dir)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to extract CHM: {result.stderr}")
            print("Extraction complete.")

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
            print("Using existing index. Use --rebuild to force rebuild.")
            return

        print("Building search index...")

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        # Create tables
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

        # Create FTS table
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title, namespace, keywords, content,
                content='documents',
                content_rowid='id'
            )
        ''')

        # Clear existing data
        cursor.execute('DELETE FROM documents')
        cursor.execute('DELETE FROM documents_fts')

        # Process HTML files
        html_dir = self.extract_dir / 'html'
        if not html_dir.exists():
            print("Warning: No html directory found in extracted CHM")
            conn.close()
            return

        htm_files = list(html_dir.glob('*.htm')) + list(html_dir.glob('*.html'))
        total = len(htm_files)

        for i, htm_file in enumerate(htm_files):
            if (i + 1) % 1000 == 0:
                print(f"  Indexed {i + 1}/{total} files...")

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
                print(f"Warning: Failed to index {htm_file.name}: {e}")

        # Populate FTS
        cursor.execute('''
            INSERT INTO documents_fts(rowid, title, namespace, keywords, content)
            SELECT id, title, namespace, keywords, content FROM documents
        ''')

        conn.commit()
        conn.close()
        print(f"Index built with {total} documents.")

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
        output.append(f"{'=' * 60}")
        output.append(f"Title: {title}")
        if meta.get('namespace'):
            output.append(f"Namespace: {meta['namespace']}")
        if meta.get('help_id'):
            output.append(f"API: {meta['help_id']}")
        output.append(f"{'=' * 60}")
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

            # Categorize by type
            title_lower = title.lower()
            if 'constructor' in title_lower:
                class_info['constructors'].append(entry)
            elif 'propert' in title_lower:
                class_info['properties'].append(entry)
            elif 'method' in title_lower or 'function' in title_lower:
                class_info['methods'].append(entry)
            elif 'event' in title_lower:
                class_info['events'].append(entry)
            elif 'field' in title_lower:
                class_info['fields'].append(entry)
            elif 'operator' in title_lower:
                class_info['operators'].append(entry)
            else:
                class_info['other'].append(entry)

        conn.close()
        return class_info


def main():
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

    args = parser.parse_args()

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

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
