#!/usr/bin/env bash
# ==============================================================================
# Nook - AppImage Build Script
# Packages Nook and all dependencies (Python, PyQt6, Qt6 plugins, etc.)
# into a self-contained, portable Linux .AppImage.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="Nook"
APP_LOWER="nook"
OUTPUT_APPIMAGE="${APP_NAME}-x86_64.AppImage"
TOOLS_DIR="${SCRIPT_DIR}/tools"
APPDIR="${SCRIPT_DIR}/build/AppDir"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"

echo "=== [1/6] Validating Environment & Tools ==="
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment not found at ${SCRIPT_DIR}/.venv"
    exit 1
fi

if [ ! -f "icon.ico" ]; then
    echo "Error: icon.ico not found in ${SCRIPT_DIR}"
    exit 1
fi

mkdir -p "$TOOLS_DIR"
APPIMAGETOOL="${TOOLS_DIR}/appimagetool"
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "Downloading appimagetool..."
    curl -L -o "$APPIMAGETOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

echo "=== [2/6] Extracting icon.png from icon.ico ==="
"$VENV_PYTHON" -c "
from PIL import Image
im = Image.open('icon.ico')
im.save('icon.png', format='PNG')
print('Extracted icon.png from icon.ico (size: %sx%s)' % im.size)
"

echo "=== [3/6] Compiling Self-Contained Binary with PyInstaller ==="
# Ensure PyInstaller is available in virtualenv
"$SCRIPT_DIR/.venv/bin/pip" install --quiet pyinstaller

# Build onedir package containing python runtime, PyQt6, and all dependencies
"$SCRIPT_DIR/.venv/bin/pyinstaller" \
    --name "$APP_LOWER" \
    --onedir \
    --windowed \
    --add-data "icon.ico:." \
    --add-data "icon.png:." \
    --clean \
    -y \
    main.py

echo "=== [4/6] Assembling AppDir Structure ==="
rm -rf "$APPDIR"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/lib/nook"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

# Copy compiled application & bundled libraries
cp -r dist/nook/* "${APPDIR}/usr/lib/nook/"

# Create launcher in /usr/bin
cat << 'EOF' > "${APPDIR}/usr/bin/nook"
#!/bin/sh
SELF="$(readlink -f "$0")"
BINDIR="$(dirname "$SELF")"
APPDIR="$(dirname "$(dirname "$BINDIR")")"
exec "${APPDIR}/usr/lib/nook/nook" "$@"
EOF
chmod +x "${APPDIR}/usr/bin/nook"

# Create root AppRun script
cat << 'EOF' > "${APPDIR}/AppRun"
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
exec "${HERE}/usr/lib/nook/nook" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

# Desktop entry
cat << EOF > "${APPDIR}/nook.desktop"
[Desktop Entry]
Type=Application
Name=Nook
GenericName=Video Library Manager
Comment=Cozy Cross-Platform Local Video Library Manager
Exec=nook %F
Icon=nook
Terminal=false
Categories=AudioVideo;Video;Player;
StartupWMClass=nook
MimeType=video/mp4;video/x-matroska;video/webm;video/x-msvideo;video/quicktime;
Keywords=video;movie;series;anime;player;library;nook;
EOF
cp "${APPDIR}/nook.desktop" "${APPDIR}/usr/share/applications/nook.desktop"

# Icons
cp icon.png "${APPDIR}/nook.png"
cp icon.png "${APPDIR}/.DirIcon"
cp icon.png "${APPDIR}/usr/share/icons/hicolor/256x256/apps/nook.png"
cp icon.ico "${APPDIR}/icon.ico"
cp icon.ico "${APPDIR}/usr/lib/nook/icon.ico"
cp icon.png "${APPDIR}/usr/lib/nook/icon.png"

echo "=== [5/6] Building AppImage with appimagetool ==="
export ARCH="x86_64"
"$APPIMAGETOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUTPUT_APPIMAGE"

chmod +x "$OUTPUT_APPIMAGE"

echo "=== [6/6] Build Successful! ==="
ls -lh "$OUTPUT_APPIMAGE"
echo "Output: ${SCRIPT_DIR}/${OUTPUT_APPIMAGE}"
