#!/usr/bin/env bash
# ==============================================================================
# Nook - Windows Executable (.exe) Build Script
# Uses Wine + Windows Python 3.11 + PyInstaller to compile a standalone,
# single-file Windows executable (Nook.exe) with icon.ico embedded.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_WIN="C:\\Python311\\python.exe"
PYINSTALLER_WIN="C:\\Python311\\Scripts\\pyinstaller.exe"
DIST_WIN="${SCRIPT_DIR}/dist_win"
BUILD_WIN="${SCRIPT_DIR}/build_win"

echo "=== [1/4] Verifying Windows Build Environment in Wine ==="
if [ ! -f "icon.ico" ]; then
    echo "Error: icon.ico not found in ${SCRIPT_DIR}"
    exit 1
fi

if ! command -v wine >/dev/null 2>&1; then
    echo "Error: wine is not installed."
    exit 1
fi

# Ensure icon.png is generated
if [ ! -f "icon.png" ]; then
    python3 -c "from PIL import Image; Image.open('icon.ico').save('icon.png')"
fi

echo "=== [2/4] Verifying Windows Python & PyInstaller ==="
WINEDEBUG=-all wine "$PYTHON_WIN" --version
WINEDEBUG=-all wine "$PYINSTALLER_WIN" --version

echo "=== [3/4] Compiling Standalone Windows Executable (Nook.exe) ==="
rm -rf "$DIST_WIN" "$BUILD_WIN"
mkdir -p "$DIST_WIN" "$BUILD_WIN"

WINEDEBUG=-all wine "$PYINSTALLER_WIN" \
    --name "Nook" \
    --onefile \
    --windowed \
    --icon "icon.ico" \
    --add-data "icon.ico;." \
    --add-data "icon.png;." \
    --distpath "Z:\\home\\meheni\\Music\\Nook\\dist_win" \
    --workpath "Z:\\home\\meheni\\Music\\Nook\\build_win" \
    --clean \
    -y \
    "Z:\\home\\meheni\\Music\\Nook\\main.py"

echo "=== [4/4] Verifying Output Executable ==="
if [ -f "${DIST_WIN}/Nook.exe" ]; then
    cp "${DIST_WIN}/Nook.exe" "${SCRIPT_DIR}/Nook.exe"
    echo "Successfully built Nook.exe!"
    ls -lh "${SCRIPT_DIR}/Nook.exe"
else
    echo "Error: Nook.exe was not generated."
    exit 1
fi
