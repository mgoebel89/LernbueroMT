#!/usr/bin/env bash
# Lernbüro MT fuer Proxmox VE: Container anlegen und installieren, oder vorhandenen aktualisieren.
# Auf dem Proxmox-Host (Shell des Knotens) als root ausfuehren:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/mgoebel89/LernbueroMT/main/proxmox/lernbuero.sh)"
#
# Legt einen unprivilegierten LXC mit Ubuntu 24.04 an (Start beim Booten), klont das Repo nach /opt/lernbuero und
# ruft deploy/install.sh auf. Danach geht es im Browser weiter (https://<container>/einrichtung mit dem
# Einrichtungscode vom Ende dieses Skripts). Richtwerte: 4 Kerne, 6 GB RAM, 16 GB Platte (die Spracherkennung ab Stufe D braucht das).
# Voraussetzung: das Repo ist oeffentlich (sonst laesst sich das Skript nicht so laden).
set -euo pipefail

ZWEIG="${ZWEIG:-main}"
REPO="https://github.com/mgoebel89/LernbueroMT.git"
TITEL="Lernbüro MT"

command -v pct >/dev/null || { echo "Dieses Skript laeuft nur auf einem Proxmox-VE-Host."; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren."; exit 1; }

frage() {   # frage <Text> <Vorgabe> -> Eingabe (Abbruch beendet das Skript)
  whiptail --title "$TITEL" --inputbox "$1" 10 72 "$2" 3>&1 1>&2 2>&3 || exit 0
}

aktion=$(whiptail --title "$TITEL" --menu "Was soll passieren?" 13 72 2 \
  neu "Neuen Container anlegen und installieren" \
  update "Vorhandenen Container aktualisieren" 3>&1 1>&2 2>&3) || exit 0

if [ "$aktion" = update ]; then
  ctid=$(frage "Nummer (CT-ID) des Containers mit Lernbüro MT:" "")
  pct status "$ctid" >/dev/null 2>&1 || { echo "Container $ctid gibt es nicht."; exit 1; }
  pct exec "$ctid" -- lernbuero-update
  exit 0
fi

# --- neuer Container ---
ctid=$(frage "Nummer (CT-ID) des neuen Containers:" "$(pvesh get /cluster/nextid)")
name=$(frage "Hostname:" "lernbuero")
kerne=$(frage "CPU-Kerne:" "4")
ram=$(frage "Arbeitsspeicher in MB:" "6144")
platte=$(frage "Festplatte in GB:" "16")

speicher=$(pvesm status -content rootdir | awk 'NR>1 {print $1}' | head -1)
speicher=$(frage "Speicher fuer die Container-Festplatte (vorhanden: $(pvesm status -content rootdir | awk 'NR>1 {print $1}' | xargs)):" "$speicher")
vorlagen=$(pvesm status -content vztmpl | awk 'NR>1 {print $1}' | head -1)
vorlagen=$(frage "Speicher fuer die Ubuntu-Vorlage (vorhanden: $(pvesm status -content vztmpl | awk 'NR>1 {print $1}' | xargs)):" "$vorlagen")
bruecke=$(frage "Netzwerk-Bruecke:" "vmbr0")
ip=$(frage "IP-Adresse mit Netzmaske (z.B. 192.168.7.2/16) oder dhcp:" "dhcp")
netz="name=eth0,bridge=$bruecke,ip=$ip"
dns=""
if [ "$ip" != dhcp ]; then
  gw=$(frage "Gateway:" "")
  [ -n "$gw" ] && netz="$netz,gw=$gw"
  dns=$(frage "DNS-Server (leer = wie der Proxmox-Host):" "$gw")
fi
pw=$(whiptail --title "$TITEL" --passwordbox "Root-Passwort fuer den Container (Konsole):" 10 72 3>&1 1>&2 2>&3) || exit 0
[ -n "$pw" ] || { echo "Ohne Passwort geht es nicht."; exit 1; }

whiptail --title "$TITEL" --yesno "Container $ctid '$name' anlegen?\n\n$kerne Kern(e), $ram MB RAM, $platte GB auf $speicher\nNetz: $netz\n\nDanach wird Lernbüro MT installiert (dauert einige Minuten)." 14 72 || exit 0

echo "==> Ubuntu-24.04-Vorlage"
pveam update >/dev/null
vorlage=$(pveam available --section system | awk '/ubuntu-24\.04-standard/ {print $2}' | sort -V | tail -1)
[ -n "$vorlage" ] || { echo "Keine Ubuntu-24.04-Vorlage gefunden."; exit 1; }
pveam list "$vorlagen" | grep -q "$vorlage" || pveam download "$vorlagen" "$vorlage"

echo "==> Container $ctid anlegen"
pct create "$ctid" "$vorlagen:vztmpl/$vorlage" --hostname "$name" --cores "$kerne" --memory "$ram" --swap 512 \
  --rootfs "$speicher:$platte" --net0 "$netz" ${dns:+--nameserver "$dns"} --unprivileged 1 --features nesting=1 \
  --onboot 1 --ostype ubuntu --password "$pw" --description "Lernbüro MT, https://github.com/mgoebel89/LernbueroMT"
pct start "$ctid"

echo "==> Warte auf Netzwerk"
for _ in $(seq 1 60); do
  pct exec "$ctid" -- getent hosts github.com >/dev/null 2>&1 && break
  sleep 2
done
pct exec "$ctid" -- getent hosts github.com >/dev/null || { echo "Container hat kein Internet (DNS/Gateway pruefen)."; exit 1; }

echo "==> Installation im Container"
pct exec "$ctid" -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update -q >/dev/null &&
  apt-get install -y -q git ca-certificates >/dev/null &&
  git clone -q --branch '$ZWEIG' '$REPO' /opt/lernbuero && bash /opt/lernbuero/deploy/install.sh"

cat <<TEXT

Fertig. Container $ctid ($name). Die Adresse und den Einrichtungscode zeigt die Ausgabe oben.
  Einrichtungscode vergessen: in der Konsole des Containers  lernbuero einrichtungscode
  Update spaeter: dieses Skript erneut starten und "aktualisieren" waehlen, oder im Container: lernbuero-update
TEXT
