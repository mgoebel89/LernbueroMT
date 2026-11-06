#!/bin/sh
# Konsolenbefehle von Lernbüro MT (als /usr/local/bin/lernbuero installiert). Ohne Argument: Hilfe.
cd /opt/lernbuero || exit 1
exec runuser -u lernbuero -- env LERNBUERO_DATEN=/var/lib/lernbuero python3 -m app.cli "$@"
