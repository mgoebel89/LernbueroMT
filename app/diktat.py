"""Diktat: Sprache zu Text im Container (Konzept Abschnitt 10).

Der Browser nimmt im Lehrerbereich auf (Mikrofon nur ueber HTTPS) und schickt die Aufnahme nach "Stopp" hierher.
Whisper (faster-whisper, Modell "small", Deutsch) erkennt den Text in einem eigenen Prozess
(app/whisper_lauf.py mit dem Python aus /opt/lernbuero-whisper). Die Aufnahme wird danach sofort geloescht,
gespeichert wird nur der Text, den die Lehrkraft freigibt. Fachwoerter des Pakets (Aufgabentitel, Kann-Aussagen)
gehen als Vorgabe mit, damit "5/2-Wegeventil" oder "GRAFCET" besser erkannt werden.
Es laeuft immer nur ein Diktat zur Zeit (Arbeitsspeicher); weitere warten kurz.
"""
import json
import os
import secrets
import subprocess
import threading

UMGEBUNG = os.environ.get("LERNBUERO_WHISPER", "/opt/lernbuero-whisper")
LAUF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_lauf.py")
MAX_BYTES = 25 * 1024 * 1024       # gut 10 Minuten Opus
ZEITLIMIT_S = 300
WARTEN_S = 90
TYPEN = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/wav": ".wav",
         "audio/x-wav": ".wav", "video/webm": ".webm"}
_SPERRE = threading.Lock()


class DiktatFehler(Exception):
    pass


def _ordner(daten_dir):
    return os.path.join(daten_dir, "whisper")


def modell(daten_dir):
    try:
        with open(os.path.join(_ordner(daten_dir), "modell"), encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return None
    return name if os.path.exists(os.path.join(_ordner(daten_dir), "fertig-" + name)) else None


def stand(daten_dir):
    python = os.path.join(UMGEBUNG, "bin", "python")
    m = modell(daten_dir)
    return {"verfuegbar": bool(m and os.access(python, os.X_OK)), "modell": m}


def fachwoerter(con, paket_id):
    """Kurze Liste aus Aufgabentiteln und Kann-Aussagen des Pakets (Whisper nimmt nur gut 200 Woerter Vorgabe)."""
    if not paket_id:
        return ""
    woerter = [z[0] for z in con.execute("SELECT titel FROM aufgabe WHERE paket_id = ? AND aktiv = 1 ORDER BY pos", (paket_id,))]
    woerter += [z[0] for z in con.execute("SELECT text FROM kann_aussage WHERE paket_id = ? AND aktiv = 1 ORDER BY pos", (paket_id,))]
    text = ". ".join(w.strip() for w in woerter if w and w.strip())
    return text[:700]


def erkennen(daten_dir, inhalt, typ, vorgabe=""):
    """Aufnahme (bytes) -> {"text", "unsicher", "audio_s", "dauer_s"}. Die Datei ist danach geloescht."""
    st = stand(daten_dir)
    if not st["verfuegbar"]:
        raise DiktatFehler("Das Diktat ist im Container noch nicht eingerichtet (bash /opt/lernbuero/deploy/diktat.sh).")
    if not inhalt:
        raise DiktatFehler("Die Aufnahme ist leer.")
    if len(inhalt) > MAX_BYTES:
        raise DiktatFehler("Die Aufnahme ist zu lang. Bitte in mehreren Teilen diktieren.")
    endung = TYPEN.get((typ or "").split(";")[0].strip().lower())
    if endung is None:
        raise DiktatFehler("Dieses Aufnahmeformat kenne ich nicht.")
    if not _SPERRE.acquire(timeout=WARTEN_S):
        raise DiktatFehler("Gerade läuft ein anderes Diktat. Bitte gleich noch einmal versuchen.")
    tmp = os.path.join(daten_dir, "diktat-tmp")
    datei = os.path.join(tmp, secrets.token_hex(8) + endung)
    try:
        os.makedirs(tmp, mode=0o700, exist_ok=True)
        fd = os.open(datei, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(inhalt)
        umgebung = dict(os.environ, HF_HUB_OFFLINE="1", HF_HOME=os.path.join(_ordner(daten_dir), "hf"),
                        HOME=_ordner(daten_dir), OMP_NUM_THREADS=str(os.cpu_count() or 2))
        try:
            lauf = subprocess.run([os.path.join(UMGEBUNG, "bin", "python"), LAUF, datei, _ordner(daten_dir), st["modell"], vorgabe or ""],
                                  capture_output=True, text=True, timeout=ZEITLIMIT_S, env=umgebung)
        except subprocess.TimeoutExpired:
            raise DiktatFehler("Das Erkennen hat zu lange gedauert. Bitte kürzer diktieren.")
        if lauf.returncode != 0:
            letzte = (lauf.stderr or "").strip().splitlines()[-1:] or ["?"]
            print("FEHLER Diktat: %s" % letzte[0][:300], flush=True)
            raise DiktatFehler("Die Aufnahme ließ sich nicht erkennen.")
        try:
            return json.loads(lauf.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise DiktatFehler("Die Aufnahme ließ sich nicht erkennen.")
    finally:
        try:
            os.remove(datei)
        except OSError:
            pass
        _SPERRE.release()
