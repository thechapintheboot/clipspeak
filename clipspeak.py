#!/usr/bin/env python3
"""ClipSpeak 2 - reads the clipboard aloud with Gemini 3.8 Flash TTS (via OpenRouter).

Only the Python standard library plus PyGObject (GTK 3, Ayatana AppIndicator,
libnotify) from the distribution's packages. Audio is played with paplay,
pw-play or aplay, whichever is installed.
"""

import argparse
import fcntl
import json
import os
import queue
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from collections import OrderedDict, namedtuple

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import Gdk, GLib, Gtk, Notify

VERSION = "2.0"
API_URL = "https://openrouter.ai/api/v1/audio/speech"
MODELS = ("google/gemini-3.8-flash-tts", "google/gemini-3.8-flash-lite-tts")
# Characters per synthesis request: a short first chunk starts the audio quickly,
# the following ones are generated while the previous one is playing.
CHUNK_LIMITS = (180, 400, 900, 1800)
CACHE_SIZE = 12  # finished readings kept in memory: "Repeat" on them is instant and free

_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONFIG_DIR = os.path.join(_CONFIG_HOME, "clipspeak")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
KEY_FILE = os.path.join(CONFIG_DIR, "openrouter.env")
SHARED_KEY_FILE = os.path.join(_CONFIG_HOME, "openrouter.env")
AUTOSTART_FILE = os.path.join(_CONFIG_HOME, "autostart", "clipspeak.desktop")
_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/clipspeak-{os.getuid()}"
SOCKET_PATH = os.path.join(_RUNTIME_DIR, "clipspeak.sock")

ICON_IDLE = "audio-speakers-symbolic"
ICON_LOADING = "content-loading-symbolic"
ICON_PLAYING = "audio-volume-high-symbolic"


def _ui_is_italian():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.startswith("it")
    return False


IT = _ui_is_italian()


def set_ui_language(choice):
    """choice: "auto" (follow the system locale), "it" or "en"."""
    global IT
    IT = _ui_is_italian() if choice == "auto" else choice == "it"


def tr(italian, english):
    return italian if IT else english


# The 30 Gemini TTS voices: (name, female, trait in Italian, trait in English).
VOICES = (
    ("Achernar", True, "morbida", "soft"),
    ("Aoede", True, "ariosa", "breezy"),
    ("Autonoe", True, "luminosa", "bright"),
    ("Callirrhoe", True, "rilassata", "easy-going"),
    ("Despina", True, "vellutata", "smooth"),
    ("Erinome", True, "nitida", "clear"),
    ("Gacrux", True, "matura", "mature"),
    ("Kore", True, "decisa", "firm"),
    ("Laomedeia", True, "vivace", "upbeat"),
    ("Leda", True, "giovanile", "youthful"),
    ("Pulcherrima", True, "diretta", "forward"),
    ("Sulafat", True, "calda", "warm"),
    ("Vindemiatrix", True, "gentile", "gentle"),
    ("Zephyr", True, "luminosa", "bright"),
    ("Achird", False, "amichevole", "friendly"),
    ("Algenib", False, "roca", "gravelly"),
    ("Algieba", False, "vellutata", "smooth"),
    ("Alnilam", False, "decisa", "firm"),
    ("Charon", False, "informativa", "informative"),
    ("Enceladus", False, "soffiata", "breathy"),
    ("Fenrir", False, "energica", "excitable"),
    ("Iapetus", False, "nitida", "clear"),
    ("Orus", False, "decisa", "firm"),
    ("Puck", False, "vivace", "upbeat"),
    ("Rasalgethi", False, "informativa", "informative"),
    ("Sadachbia", False, "brillante", "lively"),
    ("Sadaltager", False, "autorevole", "knowledgeable"),
    ("Schedar", False, "equilibrata", "even"),
    ("Umbriel", False, "rilassata", "easy-going"),
    ("Zubenelgenubi", False, "informale", "casual"),
)
VOICE_NAMES = {v[0] for v in VOICES}

# The model has no numeric speed or pitch: both are steered with natural-language
# instructions. (value, Italian label, English label, instruction for the model)
SPEEDS = (
    ("xslow", "Molto lenta", "Very slow", "Speak very slowly, with clear pauses between phrases."),
    ("slow", "Lenta", "Slow", "Speak slowly, at a relaxed pace."),
    ("normal", "Normale", "Normal", ""),
    ("fast", "Veloce", "Fast", "Speak fast, at a brisk pace."),
    ("xfast", "Molto veloce", "Very fast", "Speak very fast, at a rapid pace."),
)
PITCHES = (
    ("xlow", "Molto grave", "Very low", "Speak with a much lower, deeper pitch than usual."),
    ("low", "Grave", "Low", "Speak with a slightly lower pitch than usual."),
    ("normal", "Normale", "Normal", ""),
    ("high", "Acuto", "High", "Speak with a slightly higher pitch than usual."),
    ("xhigh", "Molto acuto", "Very high", "Speak with a much higher pitch than usual."),
)
STYLES = (
    ("natural", "Naturale", "Natural", ""),
    ("calm", "Calmo", "Calm", "Use a calm, relaxed tone."),
    ("warm", "Caldo", "Warm", "Use a warm, friendly tone."),
    ("cheerful", "Allegro", "Cheerful", "Use a cheerful, upbeat tone."),
    ("serious", "Serio", "Serious", "Use a serious, professional tone."),
    ("narrator", "Narratore", "Narrator", "Read like an audiobook narrator: expressive and engaging."),
    ("news", "Giornalista", "News anchor", "Read like a news anchor: clear, neutral and authoritative."),
    ("teacher", "Insegnante (scandito)", "Teacher (articulated)",
     "Articulate every word very clearly, like a language teacher."),
    ("whisper", "Sussurrato", "Whisper", "Whisper softly."),
)
OPTIONS = {"speed": SPEEDS, "pitch": PITCHES, "style": STYLES}

DEFAULTS = {
    "voice": "Kore",
    "speed": "normal",
    "pitch": "normal",
    "style": "natural",
    "custom": "",
    "model": MODELS[0],
    "source": "clipboard",  # or "primary": the selected text, no Ctrl+C needed
    "ui_lang": "auto",      # menu language: "auto", "it" or "en"
}


# ---------------------------------------------------------------- settings

def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS and isinstance(v, str)})
    except (OSError, ValueError):
        pass
    if cfg["voice"] not in VOICE_NAMES:
        cfg["voice"] = DEFAULTS["voice"]
    for key, table in OPTIONS.items():
        if cfg[key] not in {row[0] for row in table}:
            cfg[key] = DEFAULTS[key]
    if cfg["source"] not in ("clipboard", "primary"):
        cfg["source"] = DEFAULTS["source"]
    if cfg["ui_lang"] not in ("auto", "it", "en"):
        cfg["ui_lang"] = DEFAULTS["ui_lang"]
    if not cfg["model"].strip():
        cfg["model"] = DEFAULTS["model"]
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_FILE)


def build_instructions(cfg):
    parts = [row[3] for key, table in OPTIONS.items() for row in table if row[0] == cfg[key] and row[3]]
    if cfg["custom"].strip():
        parts.append(cfg["custom"].strip())
    return " ".join(parts)


def _read_env_value(path, name):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].lstrip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def find_api_key():
    """Return (key, where it came from). Order: ClipSpeak's own file, environment, shared file."""
    key = _read_env_value(KEY_FILE, "OPENROUTER_API_KEY")
    if key:
        return key, KEY_FILE
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key, "$OPENROUTER_API_KEY"
    key = _read_env_value(SHARED_KEY_FILE, "OPENROUTER_API_KEY")
    if key:
        return key, SHARED_KEY_FILE
    return "", ""


def save_api_key(key):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"OPENROUTER_API_KEY={key}\n")
    os.chmod(KEY_FILE, 0o600)


def launch_command():
    """The command that starts this very copy of ClipSpeak (installed or run from source)."""
    here = os.path.realpath(__file__)
    if here.startswith("/usr/share/clipspeak/") and shutil.which("clipspeak"):
        return "clipspeak"
    return f"{shlex.quote(sys.executable)} {shlex.quote(here)}"


def autostart_enabled():
    return os.path.exists(AUTOSTART_FILE)


def set_autostart(enabled):
    if not enabled:
        if os.path.exists(AUTOSTART_FILE):
            os.remove(AUTOSTART_FILE)
        return
    os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
    with open(AUTOSTART_FILE, "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=ClipSpeak\n"
                f"Exec={launch_command()}\nIcon=clipspeak\nTerminal=false\n"
                "X-GNOME-Autostart-enabled=true\n")


# ---------------------------------------------------------------- text

_SENTENCE_END = ".!?…。！？"


def clean_text(text):
    """Tidy copied text: join lines broken mid-sentence (PDFs, e-mails), squeeze blanks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ").replace(" ", " ")
    text = re.sub(r" *\n *", "\n", text)
    # "paro-\nla" -> "parola"
    text = re.sub(r"(?<=[^\W\d_])-\n(?=[^\W\d_])",
                  lambda m: "" if m.string[m.end()].islower() else "-", text)
    # a single line break inside a sentence becomes a space
    text = re.sub(r"(?<=\S)\n(?=\S)",
                  lambda m: " " if m.string[m.start() - 1] not in _SENTENCE_END + ":;"
                  and m.string[m.end()].islower() else "\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _cut(text, limit):
    """Split an over-long piece at the last comma (or space) before the limit."""
    window = text[:limit]
    for pattern in (r"[,;:，、；：]\s*", r"\s+"):
        found = list(re.finditer(pattern, window))
        if found and found[-1].end() > limit // 3:
            i = found[-1].end()
            return text[:i].strip(), text[i:].strip()
    return text[:limit], text[limit:].strip()


def split_text(text):
    """Split text into synthesis chunks at sentence ends; the first chunks are the shortest."""
    pieces, sep = [], " "
    for i, token in enumerate(re.split(r"((?<=[.!?…。！？])\s+|\n+)", text)):
        if i % 2:
            sep = "\n" if "\n" in token else " "
        elif token.strip():
            pieces.append((sep, token.strip()))
    chunks, current = [], ""
    for sep, piece in pieces:
        while piece:
            limit = CHUNK_LIMITS[min(len(chunks), len(CHUNK_LIMITS) - 1)]
            if not current:
                if len(piece) <= limit:
                    current, piece = piece, ""
                else:
                    head, piece = _cut(piece, limit)
                    chunks.append(head)
            elif len(current) + len(sep) + len(piece) <= limit:
                current, piece = current + sep + piece, ""
            else:
                chunks.append(current)
                current = ""
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------- synthesis

class TTSError(Exception):
    pass


def _http_error_message(err):
    detail = ""
    try:
        payload = json.loads(err.read().decode("utf-8", "replace"))
        detail = str(payload.get("error", {}).get("message", "")).strip()
    except Exception:
        pass
    known = {
        400: tr("Richiesta rifiutata dal modello.", "Request rejected by the model."),
        401: tr("Chiave API OpenRouter non valida.", "Invalid OpenRouter API key."),
        402: tr("Credito OpenRouter insufficiente.", "Not enough OpenRouter credit."),
        404: tr("Modello non trovato su OpenRouter.", "Model not found on OpenRouter."),
        429: tr("Troppe richieste: riprova tra poco.", "Too many requests: try again shortly."),
    }
    message = known.get(err.code, tr(f"Errore del servizio (HTTP {err.code}).",
                                     f"Service error (HTTP {err.code})."))
    return f"{message}\n{detail}" if detail else message


def synthesize(api_key, model, voice, instructions, text, timeout=180):
    """One request to OpenRouter. Returns (pcm, rate, channels): signed 16-bit little-endian."""
    body = {"model": model, "input": text, "voice": voice, "response_format": "pcm"}
    if instructions:
        body["instructions"] = instructions
    request = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            pcm = response.read()
    except urllib.error.HTTPError as err:
        raise TTSError(_http_error_message(err)) from None
    except (urllib.error.URLError, OSError) as err:
        reason = getattr(err, "reason", err)
        raise TTSError(tr("OpenRouter non raggiungibile: ", "Cannot reach OpenRouter: ") + str(reason)) from None
    if not content_type.startswith("audio/"):
        raise TTSError(tr("Risposta inattesa dal servizio: ", "Unexpected answer from the service: ")
                       + content_type)
    rate = re.search(r"rate=(\d+)", content_type)
    channels = re.search(r"channels=(\d+)", content_type)
    return (pcm[: len(pcm) // 2 * 2],
            int(rate.group(1)) if rate else 24000,
            int(channels.group(1)) if channels else 1)


def player_command(rate, channels):
    custom = os.environ.get("CLIPSPEAK_PLAYER")  # e.g. for tests: "dd of=out.pcm status=none"
    if custom:
        return shlex.split(custom.format(rate=rate, channels=channels))
    if shutil.which("paplay"):
        return ["paplay", "--raw", f"--rate={rate}", f"--channels={channels}", "--format=s16le",
                "--client-name=ClipSpeak", "--stream-name=ClipSpeak"]
    if shutil.which("pw-play"):
        return ["pw-play", "--raw", "--rate", str(rate), "--channels", str(channels),
                "--format", "s16", "-"]
    if shutil.which("aplay"):
        return ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", str(channels)]
    return None


def write_wav(path, pcm, rate, channels):
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


Request = namedtuple("Request", "text model voice instructions")


class _Session:
    def __init__(self, request, api_key):
        self.request = request
        self.api_key = api_key
        self.stopped = threading.Event()
        self.player = None

    def cancel(self):
        self.stopped.set()
        self.kill_player()

    def kill_player(self):
        player = self.player
        if player and player.poll() is None:
            player.kill()


def _put(q, item, stopped):
    while not stopped.is_set():
        try:
            q.put(item, timeout=0.2)
            return True
        except queue.Full:
            pass
    return False


def _get(q, stopped):
    while not stopped.is_set():
        try:
            return q.get(timeout=0.2)
        except queue.Empty:
            pass
    return None


class Speaker:
    """Reads one text at a time: chunks are synthesized ahead and played without gaps.

    Public methods are called from the GTK thread; callbacks come back on it too.
    """

    def __init__(self, on_state, on_error):
        self._on_state = on_state  # "idle" | "loading" | "playing"
        self._on_error = on_error
        self._session = None
        self._cache = OrderedDict()  # Request -> (pcm, rate, channels)
        self._lock = threading.Lock()
        self.last = None

    @property
    def busy(self):
        return self._session is not None

    @property
    def current_text(self):
        return self._session.request.text if self._session else None

    def speak(self, request, api_key):
        self.stop()
        session = _Session(request, api_key)
        self._session = session
        self.last = request
        self._on_state("loading")
        threading.Thread(target=self._play, args=(session,), daemon=True).start()

    def stop(self):
        session, self._session = self._session, None
        if session:
            session.cancel()
            self._on_state("idle")

    def cached(self, request):
        with self._lock:
            return self._cache.get(request)

    def _store(self, request, item):
        with self._lock:
            self._cache[request] = item
            self._cache.move_to_end(request)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)

    def _fetch(self, s, q):
        try:
            for chunk in split_text(s.request.text):
                if s.stopped.is_set():
                    return
                item = synthesize(s.api_key, s.request.model, s.request.voice,
                                  s.request.instructions, chunk)
                if not _put(q, item, s.stopped):
                    return
            _put(q, None, s.stopped)
        except Exception as err:  # delivered to the player thread, shown as a notification
            _put(q, err, s.stopped)

    def _play(self, s):
        q = queue.Queue(maxsize=2)
        hit = self.cached(s.request)
        if hit:
            q.put(hit)
            q.put(None)
        else:
            threading.Thread(target=self._fetch, args=(s, q), daemon=True).start()
        parts, fmt, complete, error = [], None, False, None
        try:
            while not s.stopped.is_set():
                item = _get(q, s.stopped)
                if s.stopped.is_set():
                    break
                if item is None:
                    complete = True
                    break
                if isinstance(item, Exception):
                    error = item
                    break
                pcm, rate, channels = item
                if s.player is None:
                    cmd = player_command(rate, channels)
                    if not cmd:
                        error = TTSError(tr("Nessun lettore audio: installa pulseaudio-utils, "
                                            "pipewire-bin o alsa-utils.",
                                            "No audio player: install pulseaudio-utils, "
                                            "pipewire-bin or alsa-utils."))
                        break
                    fmt = (rate, channels)
                    s.player = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    if s.stopped.is_set():
                        s.kill_player()
                        break
                    GLib.idle_add(self._state_from_thread, s, "playing")
                s.player.stdin.write(pcm)  # blocks while the player catches up
                s.player.stdin.flush()
                parts.append(pcm)
            if complete and fmt and not hit:
                self._store(s.request, (b"".join(parts), *fmt))
            if s.player and not s.stopped.is_set():
                s.player.stdin.close()
                stderr = s.player.stderr.read().decode("utf-8", "replace").strip()
                if s.player.wait() != 0 and not s.stopped.is_set():
                    error = TTSError(tr("Errore del lettore audio: ", "Audio player error: ") + stderr)
        except OSError as err:  # BrokenPipe when stopped, or the player could not start
            if not s.stopped.is_set():
                error = TTSError(tr("Errore del lettore audio: ", "Audio player error: ") + str(err))
        finally:
            if s.player and s.player.poll() is None and s.stopped.is_set():
                s.kill_player()
        GLib.idle_add(self._finished, s, error)

    def _state_from_thread(self, s, state):
        if s is self._session:
            self._on_state(state)
        return False

    def _finished(self, s, error):
        if error and not s.stopped.is_set():
            self._on_error(error)
        if s is self._session:
            self._session = None
            self._on_state("idle")
        return False


# ---------------------------------------------------------------- IPC

COMMANDS = ("speak", "stop", "repeat", "settings", "say", "quit")


def send_command(command, payload=""):
    """Hand a command to the running instance. False if none is running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(SOCKET_PATH)
            client.sendall(f"{command}\n{payload}".encode("utf-8"))
        return True
    except OSError:
        return False


def start_command_server(handler):
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    server.listen(4)

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                data = b""
                try:
                    while len(data) < 2_000_000:
                        block = conn.recv(65536)
                        if not block:
                            break
                        data += block
                except OSError:
                    continue
            command, _, payload = data.decode("utf-8", "replace").partition("\n")
            GLib.idle_add(handler, command.strip(), payload)

    threading.Thread(target=serve, daemon=True).start()
    return server


def acquire_instance_lock():
    os.makedirs(_RUNTIME_DIR, mode=0o700, exist_ok=True)
    fd = os.open(SOCKET_PATH + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


# ---------------------------------------------------------------- GUI

def notify(summary, body="", icon=ICON_IDLE):
    try:
        Notify.Notification.new(summary, body, icon).show()
    except GLib.Error:
        print(f"{summary}: {body}", file=sys.stderr)


def app_icon():
    return "clipspeak" if Gtk.IconTheme.get_default().has_icon("clipspeak") else "audio-speakers"


def _label(table, value):
    for row in table:
        if row[0] == value:
            return tr(row[1], row[2])
    return value


class App:
    def __init__(self):
        self.cfg = load_config()
        set_ui_language(self.cfg["ui_lang"])
        self.speaker = Speaker(self._on_state, self._on_error)
        self.last_text = None
        self.settings_win = None
        self.state = "idle"

        def hide_deprecation_notice(domain, level, message, _data):
            # Debian 13 ships no libayatana-appindicator-glib: nothing to act upon.
            if "deprecated" not in (message or ""):
                GLib.log_default_handler(domain, level, message, None)

        GLib.log_set_handler("libayatana-appindicator", GLib.LogLevelFlags.LEVEL_WARNING,
                             hide_deprecation_notice, None)
        self.indicator = AppIndicator.Indicator.new(
            "clipspeak", ICON_IDLE, AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_title("ClipSpeak")
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.rebuild_menu()

    # --- tray menu

    def rebuild_menu(self):
        menu = Gtk.Menu()
        read_label = (tr("Leggi selezione", "Read selection") if self.cfg["source"] == "primary"
                      else tr("Leggi appunti", "Read clipboard"))
        self.read_item = self._item(menu, "▶  " + read_label, lambda *_: self.read_source())
        self.stop_item = self._item(menu, "■  " + tr("Ferma", "Stop"), lambda *_: self.speaker.stop())
        self.repeat_item = self._item(menu, "↻  " + tr("Ripeti con la voce attuale",
                                                       "Repeat with current voice"),
                                      lambda *_: self.repeat())
        menu.append(Gtk.SeparatorMenuItem())

        voice_menu = Gtk.Menu()
        for female, title in ((True, tr("Femminili", "Female")), (False, tr("Maschili", "Male"))):
            group = Gtk.Menu()
            self._choices(group, [(v[0], f"{v[0]} — {tr(v[2], v[3])}") for v in VOICES if v[1] == female],
                          self.cfg["voice"], "voice")
            self._submenu(voice_menu, title, group)
        self._submenu(menu, f"{tr('Voce', 'Voice')}: {self.cfg['voice']}", voice_menu)

        for key, title, table in (("speed", tr("Velocità", "Speed"), SPEEDS),
                                  ("pitch", tr("Tono", "Pitch"), PITCHES),
                                  ("style", tr("Stile", "Style"), STYLES)):
            sub = Gtk.Menu()
            self._choices(sub, [(row[0], tr(row[1], row[2])) for row in table], self.cfg[key], key)
            self._submenu(menu, f"{title}: {_label(table, self.cfg[key])}", sub)

        menu.append(Gtk.SeparatorMenuItem())
        self.save_item = self._item(menu, tr("Salva l'ultima lettura (WAV)…", "Save last reading (WAV)…"),
                                    lambda *_: self.save_last())
        self._item(menu, tr("Impostazioni…", "Settings…"), lambda *_: self.open_settings())
        self._item(menu, tr("Informazioni", "About"), lambda *_: self.about())
        self._item(menu, tr("Esci", "Quit"), lambda *_: self.quit())
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_secondary_activate_target(self.read_item)  # middle click = read
        self._refresh_items()
        return False

    @staticmethod
    def _item(menu, label, callback):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", callback)
        menu.append(item)
        return item

    @staticmethod
    def _submenu(menu, label, submenu):
        item = Gtk.MenuItem(label=label)
        item.set_submenu(submenu)
        menu.append(item)

    def _choices(self, menu, entries, current, key):
        for value, label in entries:
            item = Gtk.CheckMenuItem(label=label)
            item.set_draw_as_radio(True)
            item.set_active(value == current)
            item.connect("activate", lambda _w, v=value: self.set_option(key, v))
            menu.append(item)

    def _refresh_items(self):
        busy = self.state != "idle"
        self.stop_item.set_sensitive(busy)
        self.repeat_item.set_sensitive(self.last_text is not None)
        last = self.speaker.last
        self.save_item.set_sensitive(bool(last and self.speaker.cached(last)))

    # --- state

    def set_option(self, key, value, from_settings=False):
        self.cfg[key] = value
        try:
            save_config(self.cfg)
        except OSError as err:
            notify(tr("Impossibile salvare le impostazioni", "Could not save settings"), str(err),
                   "dialog-error")
        if key not in ("custom", "model"):
            GLib.idle_add(self.rebuild_menu)  # not inside the menu's own signal handler
        if key == "ui_lang":
            set_ui_language(value)
            if self.settings_win:
                GLib.idle_add(self._reopen_settings)
        elif self.settings_win and not from_settings:
            self.settings_win.sync()

    def _on_state(self, state):
        self.state = state
        self.indicator.set_icon_full({"idle": ICON_IDLE, "loading": ICON_LOADING,
                                      "playing": ICON_PLAYING}[state], "ClipSpeak")
        self._refresh_items()

    def _on_error(self, error):
        notify(tr("ClipSpeak: errore", "ClipSpeak: error"), str(error), "dialog-error")

    # --- actions

    def read_source(self, toggle=False):
        selection = Gdk.SELECTION_PRIMARY if self.cfg["source"] == "primary" else Gdk.SELECTION_CLIPBOARD

        def got_text(_clipboard, text):
            text = clean_text(text or "")
            if toggle and self.speaker.busy and (not text or text == self.speaker.current_text):
                self.speaker.stop()  # same shortcut again = stop
            else:
                self.say(text)

        Gtk.Clipboard.get(selection).request_text(got_text)

    def say(self, text, remember=True):
        text = clean_text(text or "")
        if not text:
            notify("ClipSpeak", tr("Non c'è testo da leggere: copia prima qualcosa.",
                                   "Nothing to read: copy some text first."))
            return
        api_key, _ = find_api_key()
        if not api_key:
            notify("ClipSpeak", tr("Manca la chiave API di OpenRouter: inseriscila nelle impostazioni.",
                                   "The OpenRouter API key is missing: add it in the settings."),
                   "dialog-warning")
            self.open_settings()
            return
        if remember:
            self.last_text = text
        request = Request(text, self.cfg["model"].strip(), self.cfg["voice"], build_instructions(self.cfg))
        self.speaker.speak(request, api_key)

    def repeat(self):
        if self.last_text:
            self.say(self.last_text)  # current settings: from cache when unchanged

    def try_voice(self):
        self.say(tr(f"Ciao, sono {self.cfg['voice']}. Ecco come suona la mia voce.",
                    f"Hi, I'm {self.cfg['voice']}. This is how my voice sounds."), remember=False)

    def save_last(self):
        item = self.speaker.cached(self.speaker.last) if self.speaker.last else None
        if not item:
            return
        dialog = Gtk.FileChooserDialog(title=tr("Salva l'ultima lettura", "Save last reading"),
                                       action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(tr("Annulla", "Cancel"), Gtk.ResponseType.CANCEL,
                           tr("Salva", "Save"), Gtk.ResponseType.ACCEPT)
        dialog.set_do_overwrite_confirmation(True)
        folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC) or os.path.expanduser("~")
        dialog.set_current_folder(folder)
        dialog.set_current_name(time.strftime("clipspeak-%Y%m%d-%H%M%S.wav"))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            try:
                write_wav(dialog.get_filename(), *item)
            except OSError as err:
                notify(tr("Salvataggio non riuscito", "Saving failed"), str(err), "dialog-error")
        dialog.destroy()

    def save_key(self, key):
        key = key.strip()
        if not key:
            return
        try:
            save_api_key(key)
        except OSError as err:
            notify(tr("Impossibile salvare la chiave", "Could not save the key"), str(err), "dialog-error")
        if self.settings_win:
            self.settings_win.sync()

    def open_settings(self):
        if self.settings_win is None:
            self.settings_win = SettingsWindow(self)
        self.settings_win.present()
        return False

    def _reopen_settings(self):
        if self.settings_win:
            self.settings_win.destroy()
        return self.open_settings()

    def about(self):
        dialog = Gtk.AboutDialog(program_name="ClipSpeak", version=VERSION, logo_icon_name=app_icon(),
                                 website="https://github.com/thechapintheboot/clipspeak",
                                 license_type=Gtk.License.MIT_X11)
        dialog.set_comments(tr(
            "Legge ad alta voce il testo copiato, con le voci di Gemini 3.8 Flash TTS "
            "(via OpenRouter). La lingua viene riconosciuta da sola.\n\n"
            f"Scorciatoia da tastiera:\n{launch_command()} --speak\n"
            "(premila di nuovo per fermare la lettura)",
            "Reads the copied text aloud with the Gemini 3.8 Flash TTS voices "
            "(via OpenRouter). The language is detected automatically.\n\n"
            f"Keyboard shortcut:\n{launch_command()} --speak\n"
            "(press it again to stop reading)"))
        dialog.run()
        dialog.destroy()

    def handle(self, command, payload=""):
        if command == "speak":
            self.read_source(toggle=True)
        elif command == "stop":
            self.speaker.stop()
        elif command == "repeat":
            self.repeat()
        elif command == "settings":
            self.open_settings()
        elif command == "say":
            self.say(payload)
        elif command == "quit":
            self.quit()
        return False

    def quit(self, *_):
        self.speaker.stop()
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass
        Gtk.main_quit()
        return False


class SettingsWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title=tr("ClipSpeak — Impostazioni", "ClipSpeak — Settings"))
        self.app = app
        self._syncing = False
        self._row = 0
        self.set_border_width(18)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name(app_icon())
        self.connect("destroy", self._on_destroy)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.add(grid)

        self._section(grid, tr("Voce", "Voice"))
        self.voice = Gtk.ComboBoxText()
        for name, female, it, en in VOICES:
            gender = tr("donna", "female") if female else tr("uomo", "male")
            self.voice.append(name, f"{name} — {gender}, {tr(it, en)}")
        self.voice.connect("changed", lambda w: self._set("voice", w.get_active_id()))
        try_button = Gtk.Button(label="▶  " + tr("Prova", "Try"))
        try_button.connect("clicked", lambda *_: app.try_voice())
        box = Gtk.Box(spacing=6)
        box.pack_start(self.voice, True, True, 0)
        box.pack_start(try_button, False, False, 0)
        self._add(grid, tr("Voce", "Voice"), box)

        self.combos = {}
        for key, title, table in (("speed", tr("Velocità", "Speed"), SPEEDS),
                                  ("pitch", tr("Tono", "Pitch"), PITCHES),
                                  ("style", tr("Stile", "Style"), STYLES)):
            combo = Gtk.ComboBoxText()
            for row in table:
                combo.append(row[0], tr(row[1], row[2]))
            combo.connect("changed", lambda w, k=key: self._set(k, w.get_active_id()))
            self.combos[key] = combo
            self._add(grid, title, combo)

        self.custom = Gtk.Entry(width_chars=44, placeholder_text=tr(
            "es. con accento britannico; come un nonno che racconta una fiaba",
            "e.g. with a British accent; like a grandpa telling a fairy tale"))
        self.custom.connect("changed", lambda w: self._set("custom", w.get_text()))
        self._add(grid, tr("Istruzioni extra", "Extra instructions"), self.custom)
        self._hint(grid, tr("A parole tue: si aggiungono a velocità, tono e stile. "
                            "La lingua del testo viene riconosciuta da sola.",
                            "In your own words: added to speed, pitch and style. "
                            "The language of the text is detected automatically."))

        self._section(grid, tr("Lettura", "Reading"))
        self.src_clipboard = Gtk.RadioButton.new_with_label_from_widget(
            None, tr("Testo copiato (Ctrl+C)", "Copied text (Ctrl+C)"))
        self.src_primary = Gtk.RadioButton.new_with_label_from_widget(
            self.src_clipboard, tr("Testo selezionato, senza copiarlo", "Selected text, no need to copy"))
        for button, value in ((self.src_clipboard, "clipboard"), (self.src_primary, "primary")):
            button.connect("toggled", lambda w, v=value: w.get_active() and self._set("source", v))
        src_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        src_box.pack_start(self.src_clipboard, False, False, 0)
        src_box.pack_start(self.src_primary, False, False, 0)
        self._add(grid, tr("Leggi", "Read"), src_box)

        shortcut = Gtk.Label(xalign=0, selectable=True)
        shortcut.set_markup(f"<tt>{GLib.markup_escape_text(launch_command())} --speak</tt>")
        self._add(grid, tr("Scorciatoia", "Shortcut"), shortcut)
        self._hint(grid, tr("Assegna un tasto a questo comando nelle scorciatoie del sistema. "
                            "Premuto di nuovo sullo stesso testo, ferma la lettura.",
                            "Bind a key to this command in your system's keyboard shortcuts. "
                            "Pressed again on the same text, it stops reading."))
        self.autostart = Gtk.CheckButton(label=tr("Avvia ClipSpeak all'accesso", "Start ClipSpeak at login"))
        self.autostart.connect("toggled", self._on_autostart)
        self._add(grid, "", self.autostart)
        self.ui_lang = Gtk.ComboBoxText()
        for value, label in (("auto", tr("Automatica (come il sistema)", "Automatic (system)")),
                             ("it", "Italiano"), ("en", "English")):
            self.ui_lang.append(value, label)
        self.ui_lang.connect("changed", lambda w: self._set("ui_lang", w.get_active_id()))
        self._add(grid, tr("Lingua del menu", "Menu language"), self.ui_lang)

        self._section(grid, "OpenRouter")
        self.model = Gtk.ComboBoxText.new_with_entry()
        for model in MODELS:
            self.model.append_text(model)
        self.model.get_child().connect("changed", self._on_model)
        self._add(grid, tr("Modello", "Model"), self.model)
        self._hint(grid, tr("Flash: qualità migliore. Flash Lite: parte prima e costa meno.",
                            "Flash: best quality. Flash Lite: starts sooner and costs less."))
        self.key_status = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        self._add(grid, tr("Chiave API", "API key"), self.key_status)
        self.key_entry = Gtk.Entry(visibility=False, width_chars=34, placeholder_text="sk-or-v1-…")
        save_key = Gtk.Button(label=tr("Salva", "Save"))
        save_key.connect("clicked", self._on_save_key)
        self.key_entry.connect("activate", self._on_save_key)
        key_box = Gtk.Box(spacing=6)
        key_box.pack_start(self.key_entry, True, True, 0)
        key_box.pack_start(save_key, False, False, 0)
        self._add(grid, "", key_box)

        close = Gtk.Button(label=tr("Chiudi", "Close"))
        close.connect("clicked", lambda *_: self.destroy())
        close.set_halign(Gtk.Align.END)
        close.set_margin_top(12)
        grid.attach(close, 1, self._row, 1, 1)

        self.sync()
        self.show_all()

    def _section(self, grid, title):
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        if self._row:
            label.set_margin_top(12)
        grid.attach(label, 0, self._row, 2, 1)
        self._row += 1

    def _add(self, grid, title, widget):
        grid.attach(Gtk.Label(label=title, xalign=1), 0, self._row, 1, 1)
        grid.attach(widget, 1, self._row, 1, 1)
        self._row += 1

    def _hint(self, grid, text):
        label = Gtk.Label(xalign=0, wrap=True, max_width_chars=52)
        label.set_markup(f"<small>{GLib.markup_escape_text(text)}</small>")
        label.get_style_context().add_class("dim-label")
        grid.attach(label, 1, self._row, 1, 1)
        self._row += 1

    def sync(self):
        """Show the current settings (also after a change from the tray menu)."""
        self._syncing = True
        try:
            cfg = self.app.cfg
            self.voice.set_active_id(cfg["voice"])
            for key, combo in self.combos.items():
                combo.set_active_id(cfg[key])
            if self.custom.get_text() != cfg["custom"]:
                self.custom.set_text(cfg["custom"])
            (self.src_primary if cfg["source"] == "primary" else self.src_clipboard).set_active(True)
            if self.model.get_child().get_text() != cfg["model"]:
                self.model.get_child().set_text(cfg["model"])
            self.autostart.set_active(autostart_enabled())
            self.ui_lang.set_active_id(cfg["ui_lang"])
            key, where = find_api_key()
            if not key:
                self.key_status.set_markup(tr(
                    "✗ Nessuna chiave: creala su <a href=\"https://openrouter.ai/keys\">openrouter.ai/keys</a> "
                    "e incollala qui sotto.",
                    "✗ No key: create one at <a href=\"https://openrouter.ai/keys\">openrouter.ai/keys</a> "
                    "and paste it below."))
            else:
                shown = where.replace(os.path.expanduser("~"), "~", 1)
                self.key_status.set_markup(GLib.markup_escape_text(
                    tr(f"✓ In uso: {shown}", f"✓ In use: {shown}")))
        finally:
            self._syncing = False

    def _set(self, key, value):
        if not self._syncing and value is not None:
            self.app.set_option(key, value, from_settings=True)

    def _on_model(self, entry):
        model = entry.get_text().strip()
        if model:
            self._set("model", model)

    def _on_autostart(self, button):
        if self._syncing:
            return
        try:
            set_autostart(button.get_active())
        except OSError as err:
            notify(tr("Avvio automatico non modificato", "Autostart unchanged"), str(err), "dialog-error")

    def _on_save_key(self, *_):
        self.app.save_key(self.key_entry.get_text())
        self.key_entry.set_text("")

    def _on_destroy(self, *_):
        self.app.settings_win = None


# ---------------------------------------------------------------- main

def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="clipspeak",
        description=tr("Legge ad alta voce gli appunti con Gemini 3.8 Flash TTS.",
                       "Reads the clipboard aloud with Gemini 3.8 Flash TTS."))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--speak", action="store_true",
                       help=tr("leggi gli appunti (di nuovo: ferma)", "read the clipboard (again: stop)"))
    group.add_argument("--stop", action="store_true", help=tr("ferma la lettura", "stop reading"))
    group.add_argument("--repeat", action="store_true", help=tr("ripeti l'ultimo testo", "repeat the last text"))
    group.add_argument("--settings", action="store_true", help=tr("apri le impostazioni", "open the settings"))
    group.add_argument("--say", metavar=tr("TESTO", "TEXT"), help=tr("leggi questo testo", "read this text"))
    group.add_argument("--quit", action="store_true", help=tr("chiudi ClipSpeak", "quit ClipSpeak"))
    parser.add_argument("--version", action="version", version=f"ClipSpeak {VERSION}")
    return parser.parse_args(argv)


def main(argv=None):
    set_ui_language(load_config()["ui_lang"])
    args = parse_args(sys.argv[1:] if argv is None else argv)
    command, payload = "", ""
    for name in ("speak", "stop", "repeat", "settings", "quit"):
        if getattr(args, name):
            command = name
    if args.say is not None:
        command, payload = "say", args.say

    # Already running? Hand the command over (no command: show the settings).
    if send_command(command or "settings", payload):
        return 0
    lock = acquire_instance_lock()
    if lock is None:  # another instance is just starting: give it a moment
        for _ in range(30):
            time.sleep(0.1)
            if send_command(command or "settings", payload):
                return 0
        print("ClipSpeak: " + tr("un'altra istanza non risponde.", "another instance is not answering."),
              file=sys.stderr)
        return 1
    if command in ("stop", "quit"):
        return 0

    Notify.init("ClipSpeak")
    first_run = not os.path.exists(CONFIG_FILE)
    app = App()
    start_command_server(app.handle)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, app.quit)
    if first_run:
        save_config(app.cfg)
        notify("ClipSpeak", tr("È nell'area di notifica: copia un testo e scegli «Leggi appunti».",
                               "It's in the system tray: copy some text and choose “Read clipboard”."))
    if not find_api_key()[0]:
        GLib.idle_add(app.open_settings)
    if command:
        GLib.idle_add(app.handle, command, payload)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
