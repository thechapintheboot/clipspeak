# ClipSpeak

ClipSpeak is a small Linux tray utility that reads the text you copied aloud with
natural voices: Google's **Gemini 3.8 Flash TTS**, through [OpenRouter](https://openrouter.ai).

- **30 voices**, female and male, switchable from the tray menu in two clicks
- **Automatic language detection**: copy Italian, English, Japanese… it just reads it
- **Speed, pitch and style** (calm, warm, narrator, news anchor, teacher, whisper…),
  plus free-text instructions such as *"with a British accent"*
- **Keyboard shortcut**: `clipspeak --speak` reads the clipboard; pressed again on the same text, it stops
- **Long texts** start in about 3 seconds: the text is synthesized in chunks while you listen
- **Repeat** a reading (instant and free when nothing changed, or with the voice you just picked)
  and **save** it as a WAV file
- Reads the **copied** text (Ctrl+C) or simply the **selected** text
- Italian or English interface
- No pip packages: Python standard library + the GTK bindings your distribution already ships

## Requirements

- An OpenRouter API key ([openrouter.ai/keys](https://openrouter.ai/keys)) with some credit.
  Reading costs about **$0.014 per minute of audio** with Gemini 3.8 Flash TTS
  (Flash Lite is cheaper and starts sooner).
- A Linux desktop with a system tray (XFCE, Cinnamon, MATE, KDE; GNOME needs the AppIndicator extension).

## Installation

### .deb package (Debian, Ubuntu, Linux Mint, LMDE)

Download `clipspeak_2.0_all.deb` from the [Releases page](https://github.com/thechapintheboot/clipspeak/releases), then:

```bash
sudo apt install ./clipspeak_2.0_all.deb
```

Start **ClipSpeak** from the applications menu.

### From source

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7 pulseaudio-utils
python3 clipspeak.py
```

To build the package yourself: `./build_deb.sh` (creates `build/clipspeak_<version>_all.deb`).

## API key

ClipSpeak looks for `OPENROUTER_API_KEY` in this order:

1. `~/.config/clipspeak/openrouter.env`, written by the **Settings** window (permissions 600)
2. the `OPENROUTER_API_KEY` environment variable
3. `~/.config/openrouter.env`, a file in `KEY=value` form

## Usage

- **Tray menu**: *Read clipboard*, *Stop*, *Repeat*, and submenus for voice, speed, pitch and style.
  A middle click on the icon also reads the clipboard.
- **Settings…**: everything in one window, with a **Try** button to hear each voice.
- **Keyboard shortcut**: in your desktop's keyboard settings, add a custom shortcut with the command

  ```
  clipspeak --speak
  ```

  (the Settings window shows the exact command when running from source). If ClipSpeak isn't running, the shortcut starts it.

Other commands: `clipspeak --stop`, `--repeat`, `--say "some text"`, `--settings`, `--quit`.

Settings are stored in `~/.config/clipspeak/config.json`.

## Troubleshooting

- **No sound**: ClipSpeak plays through `paplay`, `pw-play` or `aplay` (the first one found);
  install `pulseaudio-utils`, `pipewire-bin` or `alsa-utils`.
- **"Invalid OpenRouter API key" / "Not enough credit"**: check the key and the credit on openrouter.ai.
- **No tray icon on GNOME**: install the *AppIndicator and KStatusNotifierItem Support* extension.

## License

MIT
