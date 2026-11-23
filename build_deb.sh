#!/bin/bash
# Builds a small, architecture-independent .deb package of ClipSpeak.
# Usage: ./build_deb.sh   ->   build/clipspeak_<version>_all.deb
set -euo pipefail
cd "$(dirname "$0")"

APP=clipspeak
VERSION=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' clipspeak.py)
MAINTAINER="thechapintheboot <226202320+thechapintheboot@users.noreply.github.com>"
DEPENDS="python3 (>= 3.9), python3-gi, gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1 | gir1.2-appindicator3-0.1, gir1.2-notify-0.7, pulseaudio-utils | pipewire-bin | alsa-utils"

ROOT="build/$APP-$VERSION"
rm -rf build
install -d "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/share/$APP" \
    "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$ROOT/usr/share/doc/$APP"

install -m 755 clipspeak.py "$ROOT/usr/share/$APP/clipspeak.py"
install -m 644 clipspeak.desktop "$ROOT/usr/share/applications/clipspeak.desktop"
install -m 644 clipspeak.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/clipspeak.svg"
install -m 644 LICENSE "$ROOT/usr/share/doc/$APP/copyright"

cat > "$ROOT/usr/bin/$APP" <<'EOF'
#!/bin/sh
exec python3 /usr/share/clipspeak/clipspeak.py "$@"
EOF
chmod 755 "$ROOT/usr/bin/$APP"

cat > "$ROOT/DEBIAN/control" <<EOF
Package: $APP
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: $MAINTAINER
Depends: $DEPENDS
Installed-Size: $(du -sk "$ROOT/usr" | cut -f1)
Homepage: https://github.com/thechapintheboot/clipspeak
Description: Reads the clipboard aloud with natural AI voices
 ClipSpeak sits in the system tray and reads the copied (or selected) text
 aloud with Google's Gemini 3.8 Flash TTS through OpenRouter: 30 voices,
 automatic language detection, adjustable speed, pitch and style.
 An OpenRouter API key is required.
EOF

dpkg-deb --root-owner-group --build "$ROOT" "build/${APP}_${VERSION}_all.deb"
echo "Built: build/${APP}_${VERSION}_all.deb"
