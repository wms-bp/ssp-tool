#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VERSION=$(tr -d '[:space:]' < VERSION)
CHM_FILE="SIMPLSharpPro.chm"
PKG_ID="com.crestron-tools.chm-docs"
PKG_NAME="chm-docs-${VERSION}.pkg"

echo "=== Building chm-docs v${VERSION} ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Check prerequisites and set up venv
# ---------------------------------------------------------------------------
echo "--- Checking prerequisites ---"

if ! command -v python3.13 &>/dev/null; then
    echo "ERROR: python3.13 not found. Install Python 3.13 first."
    exit 1
fi

if [ ! -f "$CHM_FILE" ]; then
    echo "NOTE: ${CHM_FILE} not found in ${SCRIPT_DIR} (not required for build)."
    echo "After installing, copy it to /usr/local/share/chm-docs/"
fi

# Create/reuse venv for build dependencies
VENV="${SCRIPT_DIR}/.venv"
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3.13 -m venv "$VENV"
fi
source "${VENV}/bin/activate"

if ! python -c "import mcp" &>/dev/null || ! python -c "import PyInstaller" &>/dev/null; then
    echo "Installing build dependencies..."
    pip install --quiet mcp pyinstaller setuptools
fi

echo "All prerequisites met."
echo ""

# ---------------------------------------------------------------------------
# 2. Build _chmlib C extension (vendored CHMLib)
# ---------------------------------------------------------------------------
echo "--- Building _chmlib C extension ---"

python setup.py build_ext --inplace
echo "C extension built."
echo ""

# ---------------------------------------------------------------------------
# 3. PyInstaller build (--onedir)
# ---------------------------------------------------------------------------
echo "--- Running PyInstaller ---"

python -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --name chm-docs \
    --add-data "chm_search.py:." \
    --add-data "chmextract.py:." \
    --add-data "VERSION:." \
    --hidden-import mcp \
    --hidden-import mcp.server \
    --hidden-import mcp.server.fastmcp \
    --hidden-import mcp.server.stdio \
    --hidden-import anyio \
    --hidden-import anyio._backends \
    --hidden-import anyio._backends._asyncio \
    --hidden-import httpx \
    --hidden-import httpx._transports \
    --hidden-import pydantic \
    --hidden-import pydantic.deprecated \
    --hidden-import pydantic.deprecated.decorator \
    --hidden-import starlette \
    --hidden-import sse_starlette \
    --hidden-import uvicorn \
    chm_mcp_server.py

echo "PyInstaller build complete."
echo ""

# ---------------------------------------------------------------------------
# 4. Stage payload for .pkg
# ---------------------------------------------------------------------------
echo "--- Staging payload ---"

PAYLOAD="${SCRIPT_DIR}/pkg-payload"
rm -rf "$PAYLOAD"

# /usr/local/lib/chm-docs/ - PyInstaller bundle
mkdir -p "${PAYLOAD}/usr/local/lib/chm-docs"
cp -R dist/chm-docs/* "${PAYLOAD}/usr/local/lib/chm-docs/"

# /usr/local/share/chm-docs/ - directory for user to place CHM file
mkdir -p "${PAYLOAD}/usr/local/share/chm-docs"

# /usr/local/bin/chm-docs - wrapper script
mkdir -p "${PAYLOAD}/usr/local/bin"
cat > "${PAYLOAD}/usr/local/bin/chm-docs" << 'WRAPPER'
#!/usr/bin/env bash
exec /usr/local/lib/chm-docs/chm-docs "$@"
WRAPPER
chmod +x "${PAYLOAD}/usr/local/bin/chm-docs"

echo "Payload staged at ${PAYLOAD}"
echo ""

# ---------------------------------------------------------------------------
# 5. Stage postinstall script (configures Claude Code MCP)
# ---------------------------------------------------------------------------
SCRIPTS="${SCRIPT_DIR}/pkg-scripts"
rm -rf "$SCRIPTS"
mkdir -p "$SCRIPTS"
cp "${SCRIPT_DIR}/postinstall" "${SCRIPTS}/postinstall"
chmod +x "${SCRIPTS}/postinstall"

# ---------------------------------------------------------------------------
# 6. Build .pkg
# ---------------------------------------------------------------------------
echo "--- Building ${PKG_NAME} ---"

pkgbuild \
    --root "$PAYLOAD" \
    --scripts "$SCRIPTS" \
    --identifier "$PKG_ID" \
    --version "$VERSION" \
    --install-location / \
    "$PKG_NAME"

echo ""
echo "=== Build complete ==="
echo "Package: ${PKG_NAME}"
echo ""
echo "To install:"
echo "  sudo installer -pkg ${PKG_NAME} -target /"
echo ""
echo "To verify:"
echo "  /usr/local/bin/chm-docs"
