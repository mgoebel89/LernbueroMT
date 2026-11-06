#!/bin/bash
# Spracherkennung fuer das Diktat einrichten (von install.sh aufgerufen, als root). Ein Fehler hier haelt die
# Installation nicht auf: ohne Whisper laeuft alles, nur der Knopf "Diktat" meldet dann "nicht eingerichtet".
#
#   /opt/lernbuero-whisper          eigene Python-Umgebung mit faster-whisper (CPU, int8), getrennt vom System-Python
#   /var/lib/lernbuero/whisper      das Modell (Vorgabe "small", Deutsch), einmal aus dem Internet geladen
#
# Danach laeuft alles ohne Internet: die Aufnahme geht nur an den Container und wird nach dem Erkennen geloescht.
# Anderes Modell:  LERNBUERO_DIKTAT_MODELL=medium bash /opt/lernbuero/deploy/diktat.sh
set -euo pipefail
UMGEBUNG=/opt/lernbuero-whisper
MODELLE=/var/lib/lernbuero/whisper
MODELL="${LERNBUERO_DIKTAT_MODELL:-$(cat "$MODELLE/modell" 2>/dev/null || echo small)}"
# passend zu faster-whisper 1.1.1: huggingface_hub 0.x (bringt requests mit), PyAV bis 13 (ab 14 fehlt metadata_errors)
PAKETE="faster-whisper==1.1.1 huggingface_hub<1.0 requests av<14"

if [ -x "$UMGEBUNG/bin/python" ] && "$UMGEBUNG/bin/python" -c 'import faster_whisper' 2>/dev/null \
    && [ "$(cat "$UMGEBUNG/pakete" 2>/dev/null)" = "$PAKETE" ] && [ -f "$MODELLE/fertig-$MODELL" ]; then
  echo "    Diktat: bereit (Modell $MODELL)"
  exit 0
fi

echo "    Diktat: richte Whisper ein (Modell $MODELL), beim ersten Mal einige Minuten ..."
if ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q >/dev/null
  apt-get install -y -q python3-venv >/dev/null
fi
[ -x "$UMGEBUNG/bin/python" ] || python3 -m venv "$UMGEBUNG"
"$UMGEBUNG/bin/pip" install -q --disable-pip-version-check --upgrade pip >/dev/null
"$UMGEBUNG/bin/pip" install -q --disable-pip-version-check $PAKETE
echo "$PAKETE" > "$UMGEBUNG/pakete"
chown -R root:root "$UMGEBUNG"
chmod -R go-w "$UMGEBUNG"

install -d -o lernbuero -g lernbuero -m 750 "$MODELLE"
HF_HOME="$MODELLE/hf" "$UMGEBUNG/bin/python" - "$MODELL" "$MODELLE" <<'LADEN'
import sys
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device="cpu", compute_type="int8", download_root=sys.argv[2])
LADEN
echo "$MODELL" > "$MODELLE/modell"
touch "$MODELLE/fertig-$MODELL"
chown -R lernbuero:lernbuero "$MODELLE"
echo "    Diktat: bereit (Modell $MODELL)"
