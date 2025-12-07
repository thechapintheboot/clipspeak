# ClipSpeak

ClipSpeak is a lightweight Linux utility that speaks the text currently in your clipboard using high-quality local TTS (Text-to-Speech). It sits in your system tray and can be triggered via a menu or a custom keyboard shortcut.

## Features

- **Clipboard Reading:** Instantly reads text copied to your clipboard.
- **Auto-Language Detection:** Automatically detects the language of the text (supports EN, IT, FR, DE, ES, ZH, AR, RU, PT).
- **High-Quality Voices:** Uses [Piper TTS](https://github.com/rhasspy/piper) for natural-sounding offline synthesis.
- **Speed Control:** Adjustable playback speed via the tray menu.
- **System Integration:** Works with any desktop environment (GNOME, XFCE, KDE, etc.) via system tray and notifications.
- **CLI/Shortcut Mode:** Trigger speech without touching the mouse using `clipspeak --speak`.

## Installation

### Prerequisites

Ensure you have Python 3 and the necessary system libraries:

```bash
sudo apt update
sudo apt install python3-pip python3-gi python3-gi-cairo gir1.2-appindicator3-0.1 espeak-ng libportaudio2 alsa-utils
```

### Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Install Piper TTS Voices

ClipSpeak requires Piper TTS voices to be installed in `~/.local/share/piper-voices`.
You can download ONNX models and their JSON config files from the [Piper releases](https://github.com/rhasspy/piper/releases) or [Hugging Face](https://huggingface.co/rhasspy/piper-voices/tree/main).

Common default models expected by ClipSpeak:
- `en_US-amy-medium.onnx`
- `it_IT-paola-medium.onnx`
- `fr_FR-siwis-medium.onnx`
- `de_DE-thorsten-medium.onnx`
- `es_ES-davefx-medium.onnx`
- ... (see `models.json` in `~/.config/clipspeak` after first run)

## Usage

1.  **Start the Application:**
    Run the script:
    ```bash
    python3 clipspeak.py
    ```
    An icon will appear in your system tray.

2.  **Speak Clipboard:**
    -   **Tray Menu:** Click the icon and select "Pronounce (Clipboard)".
    -   **Shortcut (Recommended):** Setup a global hotkey (see below).

3.  **Change Speed:**
    Use the "Change Speed" menu to adjust the speech rate (0.5x to 1.5x).

### Setting up a Keyboard Shortcut

To speak the clipboard content instantly without clicking the icon:

1.  Open your operating system's **Keyboard Settings**.
2.  Navigate to **Shortcuts** > **Custom Shortcuts**.
3.  Add a new shortcut:
    -   **Name:** ClipSpeak
    -   **Command:** `/path/to/python3 /path/to/clipspeak.py --speak`
        *(Tip: Use `pwd` to find the full path where you installed it, or if installed globally, just `clipspeak --speak`)*
4.  Assign your preferred key combination (e.g., `Super+Space` or `Ctrl+Alt+S`).

## Troubleshooting

-   **No Sound:** Ensure `aplay` is installed (`sudo apt install alsa-utils`) and your speakers are unmuted.
-   **Missing Voice:** Check the notification for the missing file name and download it to `~/.local/share/piper-voices`.
-   **Dependencies:** If you see errors about `gi`, ensure you installed the system packages (`python3-gi`, etc.) via `apt`, not just `pip`.

## License

Open Source. Feel free to modify and distribute.
