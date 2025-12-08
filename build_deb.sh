#!/bin/bash

# Configuration
APP_NAME="clipspeak"
VERSION="1.1"
ARCH="all"
MAINTAINER="Paolo <thechapintheboot@gmail.com>"
DESCRIPTION="Instant text-to-speech from your clipboard using Piper TTS (Voices Included)."
DEPENDENCIES="python3, python3-gi, python3-gi-cairo, gir1.2-appindicator3-0.1, espeak-ng, libportaudio2, alsa-utils, python3-langdetect"

# Directories
BUILD_DIR="build"
DEB_DIR="$BUILD_DIR/$APP_NAME-$VERSION"
DEBIAN_DIR="$DEB_DIR/DEBIAN"
USR_BIN="$DEB_DIR/usr/bin"
USR_SHARE="$DEB_DIR/usr/share/$APP_NAME"
VOICES_DIR="$USR_SHARE/voices"
APPS_DIR="$DEB_DIR/usr/share/applications"
ICONS_DIR="$DEB_DIR/usr/share/icons/hicolor/scalable/apps"

# Source of voices (Your local collection)
SOURCE_VOICES_DIR="$HOME/.local/share/piper-voices"

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$DEBIAN_DIR" "$USR_BIN" "$USR_SHARE" "$VOICES_DIR" "$APPS_DIR" "$ICONS_DIR"

# Create Control File
cat > "$DEBIAN_DIR/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: $MAINTAINER
Depends: $DEPENDENCIES
Description: $DESCRIPTION
 ClipSpeak sits in the system tray and speaks the clipboard content
 using high-quality Piper TTS voices.
 .
 This package includes the standard set of Piper voices (Medium quality)
 for EN, IT, FR, DE, ES, etc.
EOF

# Copy Files
cp clipspeak.py "$USR_SHARE/clipspeak.py"
cp clipspeak.svg "$ICONS_DIR/clipspeak.svg"
cp clipspeak.desktop "$APPS_DIR/clipspeak.desktop"
cp requirements.txt "$USR_SHARE/requirements.txt"

# Locate and Copy Piper Engine (Binary + Libs)
PIPER_SRC_DIR="bin"
PIPER_DEST_DIR="$USR_SHARE/piper_engine"

if [ -f "$PIPER_SRC_DIR/piper" ]; then
    echo "Found Piper engine in: $PIPER_SRC_DIR. Copying full engine to package..."
    mkdir -p "$PIPER_DEST_DIR"
    cp -r "$PIPER_SRC_DIR/"* "$PIPER_DEST_DIR/"
    chmod +x "$PIPER_DEST_DIR/piper"
else
    echo "ERROR: Piper executable NOT FOUND at expected path: $PIPER_SRC_DIR/piper."
    echo "The package WILL NOT contain the TTS engine. Please run the download command first."
    exit 1 
fi

# Copy Voices
echo "Copying voices from $SOURCE_VOICES_DIR to package..."
# Copy only ONNX and JSON files to keep it clean, but inclusive
# We verify if the directory exists first
if [ -d "$SOURCE_VOICES_DIR" ]; then
    cp "$SOURCE_VOICES_DIR"/*.onnx "$VOICES_DIR/"
    cp "$SOURCE_VOICES_DIR"/*.json "$VOICES_DIR/"
else
    echo "WARNING: Voice source directory not found! Package will be empty of voices."
fi

# Create Launcher Script
cat > "$USR_BIN/$APP_NAME" <<EOF
#!/bin/bash
exec python3 /usr/share/$APP_NAME/clipspeak.py "\$@"
EOF

chmod +x "$USR_BIN/$APP_NAME"
chmod +x "$USR_SHARE/clipspeak.py"

# Build Deb
echo "Building .deb package (this might take a moment due to file size)..."
dpkg-deb --build "$DEB_DIR"

echo "Build complete: $BUILD_DIR/$APP_NAME-$VERSION.deb"