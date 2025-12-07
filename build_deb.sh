#!/bin/bash

# Configuration
APP_NAME="clipspeak"
VERSION="1.1"
ARCH="all"
MAINTAINER="Paolo <tuo_email@example.com>"
DESCRIPTION="Instant text-to-speech from your clipboard using Piper TTS."
DEPENDENCIES="python3, python3-gi, python3-gi-cairo, gir1.2-appindicator3-0.1, espeak-ng, libportaudio2, alsa-utils"

# Directories
BUILD_DIR="build"
DEB_DIR="$BUILD_DIR/$APP_NAME-$VERSION"
DEBIAN_DIR="$DEB_DIR/DEBIAN"
USR_BIN="$DEB_DIR/usr/bin"
USR_SHARE="$DEB_DIR/usr/share/$APP_NAME"
APPS_DIR="$DEB_DIR/usr/share/applications"
ICONS_DIR="$DEB_DIR/usr/share/icons/hicolor/scalable/apps"

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$DEBIAN_DIR" "$USR_BIN" "$USR_SHARE" "$APPS_DIR" "$ICONS_DIR"

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
EOF

# Copy Files
cp clipspeak.py "$USR_SHARE/clipspeak.py"
cp clipspeak.svg "$ICONS_DIR/clipspeak.svg"
cp clipspeak.desktop "$APPS_DIR/clipspeak.desktop"
cp requirements.txt "$USR_SHARE/requirements.txt"

# Create Launcher Script
cat > "$USR_BIN/$APP_NAME" <<EOF
#!/bin/bash
# Install python deps if needed (user level) - Optional/Auto-check logic could go here
# For now, we assume the user might need to run pip install manually or we use system packages.
# Let's just run the script.
exec python3 /usr/share/$APP_NAME/clipspeak.py "\$@"
EOF

chmod +x "$USR_BIN/$APP_NAME"
chmod +x "$USR_SHARE/clipspeak.py"

# Build Deb
dpkg-deb --build "$DEB_DIR"

echo "Build complete: $BUILD_DIR/$APP_NAME-$VERSION.deb"
