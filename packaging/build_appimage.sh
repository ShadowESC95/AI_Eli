#!/usr/bin/env bash
# Packs dist/AI_Eli (the PyInstaller build) into dist/AI_Eli-<version>-x86_64.AppImage.
# usage: packaging/build_appimage.sh <version>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:?usage: $0 <version>}"
APPDIR="$ROOT/build/AI_Eli.AppDir"
[ -x "$ROOT/dist/AI_Eli/AI_Eli" ] || { echo "dist/AI_Eli is missing: run pyinstaller packaging/ai_eli.spec first" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
cp -a "$ROOT/dist/AI_Eli" "$APPDIR/usr/app"
cp "$ROOT/LICENSE" "$APPDIR/LICENSE"
cp "$ROOT/packaging/eli.png" "$APPDIR/ai_eli.png"
ln -s ai_eli.png "$APPDIR/.DirIcon"

cat > "$APPDIR/ai_eli.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=AI_Eli
Comment=Local voice assistant
Exec=AI_Eli
Icon=ai_eli
Categories=Utility;
Terminal=false
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/app/AI_Eli" "$@"
EOF
chmod +x "$APPDIR/AppRun"

TOOL="$ROOT/build/appimagetool"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$ROOT/dist/AI_Eli-$VERSION-x86_64.AppImage"
