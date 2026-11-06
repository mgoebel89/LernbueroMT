#!/bin/bash
# Lernbüro MT im Container installieren oder aktualisieren (Ubuntu 24.04 / Debian 12). Als root aus dem Repo-Ordner:
#
#   git clone https://github.com/mgoebel89/LernbueroMT /opt/lernbuero && bash /opt/lernbuero/deploy/install.sh
#
# Legt den Systembenutzer lernbuero an, Daten in /var/lib/lernbuero (Datenbank, Zertifikate, Sicherungen).
# Dienste: lernbuero (Webseite 80/443), lernbuero-tls.timer (Zertifikat), lernbuero-firewall (nur 22/80/443),
# lernbuero-update-pruefen.timer/.path und lernbuero-update-ausfuehren.path (Update aus dem Lehrerbereich).
# Befehle danach: lernbuero (Konsole, z.B. lernbuero einrichtungscode), lernbuero-update.
# Spracherkennung fuer das Diktat: deploy/diktat.sh (faster-whisper in /opt/lernbuero-whisper, Modell in /var/lib/lernbuero/whisper).
set -euo pipefail
ZIEL=/opt/lernbuero
DATEN=/var/lib/lernbuero

cd "$(dirname "$(readlink -f "$0")")/.."
[ "$(pwd)" = "$ZIEL" ] || { echo "Bitte aus $ZIEL aufrufen (git clone ... $ZIEL)."; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren."; exit 1; }

echo "==> Pakete"
fehlt=""
for befehl in python3 openssl nft git; do command -v "$befehl" >/dev/null || fehlt=1; done
[ -e /usr/share/zoneinfo/Europe/Berlin ] || fehlt=1
python3 -c 'import icalendar, recurring_ical_events' 2>/dev/null || fehlt=1   # Schulkalender-Abo (ICS)
if [ -n "$fehlt" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q >/dev/null
  apt-get install -y -q python3 openssl nftables git ca-certificates tzdata python3-icalendar \
    python3-recurring-ical-events >/dev/null
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Lernbüro MT braucht Python 3.11 oder neuer."; exit 1; }

echo "==> Benutzer und Ordner"
id lernbuero >/dev/null 2>&1 || useradd --system --home-dir "$DATEN" --shell /usr/sbin/nologin lernbuero
install -d -o lernbuero -g lernbuero -m 750 "$DATEN" "$DATEN/update" "$DATEN/sicherungen"
install -d -o root -g root -m 755 /var/lib/lernbuero-update   # Update-Ergebnisse, fuer den Webdienst nur lesbar
find "$DATEN" -maxdepth 1 -name 'lernbuero.sqlite*' -exec chmod 640 {} +
install -d -o root -g root -m 755 /etc/lernbuero
# der Code gehoert root: der Webdienst kann ihn nicht veraendern
chown -R root:root "$ZIEL"
chmod -R go-w "$ZIEL"

echo "==> Diktat (Whisper)"
if [ "${LERNBUERO_OHNE_DIKTAT:-}" = 1 ]; then
  echo "    Diktat: uebersprungen (LERNBUERO_OHNE_DIKTAT=1)"
else
  bash deploy/diktat.sh || echo "    Diktat: Einrichtung fehlgeschlagen, alles andere laeuft. Spaeter erneut: bash $ZIEL/deploy/diktat.sh"
fi

echo "==> Befehle, Dienste, Firewall"
install -o root -g root -m 755 deploy/tls.sh /usr/local/sbin/lernbuero-tls
install -o root -g root -m 755 deploy/update.sh /usr/local/sbin/lernbuero-update
install -o root -g root -m 755 deploy/selbstupdate.sh /usr/local/sbin/lernbuero-selbstupdate
install -o root -g root -m 755 deploy/lernbuero-cli.sh /usr/local/bin/lernbuero
install -o root -g root -m 644 deploy/firewall.nft /etc/lernbuero/firewall.nft
UPDATE_EINHEITEN="lernbuero-update-pruefen.path lernbuero-update-pruefen.timer lernbuero-update-ausfuehren.path"
for einheit in lernbuero.service lernbuero-tls.service lernbuero-tls.timer lernbuero-firewall.service \
    lernbuero-update-pruefen.service lernbuero-update-ausfuehren.service $UPDATE_EINHEITEN; do
  install -o root -g root -m 644 "deploy/$einheit" "/etc/systemd/system/$einheit"
done
systemctl daemon-reload
/usr/local/sbin/lernbuero-tls
systemctl enable -q lernbuero-firewall.service lernbuero-tls.timer lernbuero.service $UPDATE_EINHEITEN
systemctl restart lernbuero-firewall.service   # Regeln neu laden (auch nach einem Update)
systemctl start lernbuero-tls.timer $UPDATE_EINHEITEN
systemctl restart lernbuero.service

for _ in $(seq 1 20); do
  systemctl is-active --quiet lernbuero.service && python3 - 2>/dev/null <<'PRUEFEN' && break
import ssl, urllib.request
kontext = ssl.create_default_context(cafile="/var/lib/lernbuero/tls/ca.crt")
kontext.check_hostname = False
urllib.request.urlopen("https://127.0.0.1/api/status", context=kontext, timeout=3).read()
PRUEFEN
  sleep 1
done
if ! systemctl is-active --quiet lernbuero.service; then
  journalctl -u lernbuero.service -n 30 --no-pager
  echo "Der Dienst lernbuero laeuft nicht (siehe oben)."
  exit 1
fi

# einmal nach einer neueren Version suchen (im Hintergrund, damit die Einstellungen gleich den Stand zeigen)
systemctl start --no-block lernbuero-update-pruefen.service

ip=$(hostname -I | awk '{print $1}')
code=$(/usr/local/bin/lernbuero einrichtungscode 2>/dev/null || true)
echo
echo "Lernbüro MT laeuft: https://$ip (Lehrerbereich), http://$ip (Schüler)"
echo "  Stammzertifikat fuer die Lehrer-Geraete: http://$ip/ca.crt"
if [ -n "$code" ] && [ "${code#Die Einrichtung}" = "$code" ]; then
  echo "  Erstes Admin-Konto anlegen: https://$ip/einrichtung   Einrichtungscode: $code"
fi
