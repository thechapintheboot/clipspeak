#!/usr/bin/env python3
import os, subprocess, threading, langdetect, json, sys, socket, struct
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
gi.require_version('Notify', '0.7')
from gi.repository import Gtk, AppIndicator3, GLib, Notify, Gdk

# ---------- Configurazione Percorsi ----------
# NOTA: Per renderlo portabile, cerchiamo piper nel PATH o in una cartella locale relativa
def find_executable(name):
    # Cerca nel PATH di sistema
    path = os.environ.get("PATH", os.defpath)
    for d in path.split(os.pathsep):
        exe_file = os.path.join(d, name)
        if os.access(exe_file, os.X_OK):
            return exe_file
    return None

PIPER_EXE = find_executable("piper")
# Fallback se non è nel path, magari è nella stessa cartella dello script (per versioni portable)
if not PIPER_EXE:
    local_piper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper")
    if os.access(local_piper, os.X_OK):
        PIPER_EXE = local_piper

VOICE_DIR         = os.path.expanduser("~/.local/share/piper-voices")
APP_CONFIG_DIR    = os.path.expanduser("~/.config/clipspeak")
SPEED_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "speed.conf")
MODELS_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "models.json")
SOCKET_FILE       = os.path.join(os.getenv('XDG_RUNTIME_DIR', '/tmp'), 'clipspeak.sock')

speaking_lock = threading.Lock()

# ---------- Notifiche ----------
Notify.init("ClipSpeak-TTS")
def show_error(summary, body=""):
    Notify.Notification.new(summary, body, "dialog-error").show()

# ---------- Comunicazione IPC (Per Hotkey) ----------
def handle_client_command(command):
    if command == "speak":
        print("Received speak command from external instance")
        GLib.idle_add(on_click, None)

def start_socket_server():
    # Rimuovi il socket se esiste (pulizia da crash precedenti)
    if os.path.exists(SOCKET_FILE):
        try:
            os.unlink(SOCKET_FILE)
        except OSError:
            pass
            
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(SOCKET_FILE)
        server.listen(1)
        
        def listener():
            while True:
                try:
                    conn, _ = server.accept()
                    data = conn.recv(1024)
                    if data:
                        command = data.decode('utf-8').strip()
                        handle_client_command(command)
                    conn.close()
                except Exception as e:
                    print(f"Socket error: {e}")

        t = threading.Thread(target=listener, daemon=True)
        t.start()
    except Exception as e:
        print(f"Unable to start socket server: {e}")

def send_command_to_running_instance(cmd):
    if not os.path.exists(SOCKET_FILE):
        print("ClipSpeak is not running.")
        return False
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(SOCKET_FILE)
        client.sendall(cmd.encode('utf-8'))
        client.close()
        print(f"Command '{cmd}' sent.")
        return True
    except ConnectionRefusedError:
        print("Could not connect. Socket might be stale.")
        return False

# ---------- Configurazione Modelli Vocali ----------
def load_or_create_models_config():
    default_models = {
        'it': ('it_IT-paola-medium.onnx', 'it_IT-paola-medium.onnx.json'),
        'en': ('en_US-amy-medium.onnx', 'en_US-amy-medium.onnx.json'),
        'fr': ('fr_FR-siwis-medium.onnx', 'fr_FR-siwis-medium.onnx.json'),
        'de': ('de_DE-thorsten-medium.onnx', 'de_DE-thorsten-medium.onnx.json'),
        'es': ('es_ES-davefx-medium.onnx', 'es_ES-davefx-medium.onnx.json'),
        'zh': ('zh_CN-huayan-medium.onnx', 'zh_CN-huayan-medium.onnx.json'),
        'ar': ('ar_JO-kareem-medium.onnx', 'ar_JO-kareem-medium.onnx.json'),
        'ru': ('ru_RU-irina-medium.onnx', 'ru_RU-irina-medium.onnx.json'),
        'pt': ('pt_PT-caito-medium.onnx', 'pt_PT-caito-medium.onnx.json'),
    }
    try:
        os.makedirs(APP_CONFIG_DIR, exist_ok=True)
        if not os.path.exists(MODELS_CONFIG_FILE):
            with open(MODELS_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_models, f, indent=4, ensure_ascii=False)
            return default_models
        else:
            with open(MODELS_CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded_models = json.load(f)
                return {lang: tuple(files) for lang, files in loaded_models.items()}
    except Exception as e:
        show_error("Could not load models.json", f"Falling back to default. Error: {str(e)}")
        return default_models

MODELS = load_or_create_models_config()

SPEEDS = {
    "0.50x": 2.0, "0.75x": 1.33, "1.0x (Normal)": 1.0,
    "1.25x": 0.8, "1.5x": 0.66
}

def load_speed():
    try:
        with open(SPEED_CONFIG_FILE) as f:
            return float(f.read().strip())
    except Exception:
        return 1.0

LENGTH_SCALE = load_speed()

def set_indicator_icon(icon_name):
    if 'ind' in globals():
        ind.set_icon_full(icon_name, "speaking")

def speak(text):
    if not speaking_lock.acquire(blocking=False):
        return
    try:
        if not PIPER_EXE:
            GLib.idle_add(show_error, "Piper TTS not found", "Install piper and ensure it is in your PATH.")
            return

        GLib.idle_add(set_indicator_icon, "audio-volume-high-symbolic")
        try:
            lang = langdetect.detect(text)[:2]
            if lang not in MODELS:
                lang = 'en'
        except langdetect.lang_detect_exception.LangDetectException:
            lang = 'en'

        model, config = MODELS[lang]
        model_path = os.path.join(VOICE_DIR, model)
        config_path = os.path.join(VOICE_DIR, config)

        if not os.path.exists(model_path):
            GLib.idle_add(show_error, f"Missing model: {lang}", f"File not found in {VOICE_DIR}")
            return

        proc = subprocess.run(
            [PIPER_EXE, "--model", model_path, "--config", config_path,
             "--length-scale", str(LENGTH_SCALE), "--output-raw"],
            input=text.encode(), capture_output=True, check=True
        )
        subprocess.run(["aplay", "-q", "-r", "22050", "-f", "S16_LE", "-t", "raw"], input=proc.stdout, check=True)

    except FileNotFoundError as e:
        GLib.idle_add(show_error, "Dependency Error", f"Missing command: {e.filename}. Install 'aplay' (alsa-utils).")
    except subprocess.CalledProcessError as e:
        GLib.idle_add(show_error, "Synthesis Error", e.stderr.decode('utf-8', errors='ignore'))
    except Exception as e:
        GLib.idle_add(show_error, "Unexpected Error", str(e))
    finally:
        GLib.idle_add(set_indicator_icon, "audio-speakers-symbolic")
        speaking_lock.release()

def open_about_dialog(_):
    about_dialog = Gtk.AboutDialog()
    about_dialog.set_program_name("ClipSpeak-TTS")
    about_dialog.set_version("1.1")
    about_dialog.set_copyright("Open Source Community")
    about_dialog.set_comments(
        "Instant text-to-speech from your clipboard.\n\n"
        "To use a custom keyboard shortcut:\n"
        "1. Go to your system's Keyboard Settings > Shortcuts.\n"
        "2. Add a new custom shortcut.\n"
        "3. Set the command to: clipspeak --speak\n"
        "4. Assign your preferred key combination."
    )
    about_dialog.set_logo_icon_name("audio-speakers-symbolic")
    about_dialog.run()
    about_dialog.destroy()

current_speed_item = None

def update_speed_display():
    if current_speed_item:
        display_label = "Custom"
        for label, scale_value in SPEEDS.items():
            if abs(LENGTH_SCALE - scale_value) < 0.01:
                display_label = label.replace(" (Normal)", "")
                break
        current_speed_item.set_label(f"Speed: {display_label}")

def build_menu():
    menu = Gtk.Menu()
    speak_item = Gtk.MenuItem(label="Pronounce (Clipboard)")
    speak_item.connect("activate", on_click)
    menu.append(speak_item)
    
    global current_speed_item
    current_speed_item = Gtk.MenuItem(label="")
    current_speed_item.set_sensitive(False)
    menu.append(current_speed_item)
    update_speed_display()
    menu.append(Gtk.SeparatorMenuItem())
    
    speed_menu = Gtk.Menu()
    speed_item = Gtk.MenuItem(label="Change Speed")
    speed_item.set_submenu(speed_menu)
    group = []
    for label, scale_value in SPEEDS.items():
        is_active = abs(LENGTH_SCALE - scale_value) < 0.01
        item = Gtk.RadioMenuItem.new_with_label(group, label)
        item.set_active(is_active)
        group = item.get_group()
        speed_menu.append(item)
        item.connect("activate", on_speed_change, scale_value)

    menu.append(speed_item)
    menu.append(Gtk.SeparatorMenuItem())
    
    about_item = Gtk.MenuItem(label="About")
    about_item.connect("activate", open_about_dialog)
    menu.append(about_item)
    
    quit_item = Gtk.MenuItem(label="Exit")
    quit_item.connect("activate", lambda _: Gtk.main_quit())
    menu.append(quit_item)
    menu.show_all()
    return menu

def on_speed_change(widget, new_scale_value):
    if widget.get_active():
        global LENGTH_SCALE
        LENGTH_SCALE = new_scale_value
        try:
            with open(SPEED_CONFIG_FILE, "w") as f:
                f.write(str(LENGTH_SCALE))
        except Exception:
            pass
        update_speed_display()

def on_click(_):
    clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
    text = clipboard.wait_for_text()
    if text:
        text = text.strip()
        if text:
            threading.Thread(target=speak, args=(text,), daemon=True).start()

# ---------- MAIN ----------
if __name__ == "__main__":
    # Controlla se l'utente vuole solo attivare la pronuncia
    if len(sys.argv) > 1 and sys.argv[1] == "--speak":
        success = send_command_to_running_instance("speak")
        if not success:
            # Se l'app non è aperta, potremmo decidere di aprirla o dare errore.
            # Per ora notifichiamo l'utente
            subprocess.run(["notify-send", "ClipSpeak", "The application is not running!"])
        sys.exit(0)

    # Avvia il server per ascoltare i comandi futuri
    start_socket_server()

    ind = AppIndicator3.Indicator.new(
        "ClipSpeak-TTS", "audio-speakers-symbolic",
        AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
    ind.set_title("ClipSpeak")
    ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
    ind.set_menu(build_menu())
    
    # Gestione chiusura pulita per rimuovere il socket
    def on_quit():
        if os.path.exists(SOCKET_FILE):
            os.remove(SOCKET_FILE)
        Gtk.main_quit()
        
    try:
        Gtk.main()
    except KeyboardInterrupt:
        on_quit()
