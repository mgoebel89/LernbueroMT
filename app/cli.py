"""Befehle fuer die Konsole des Containers (Aufruf ueber /usr/local/bin/lernbuero):

  lernbuero einrichtungscode            Code fuer /einrichtung zeigen (nur solange es kein Konto gibt)
  lernbuero konten                      alle Lehrkraft-Konten auflisten
  lernbuero admin <kuerzel> <name...>   Admin-Konto mit vorlaeufigem Passwort anlegen (Notfall)
  lernbuero passwort <kuerzel>          vorlaeufiges Passwort setzen und Konto entsperren (Notfall)
  lernbuero sicherung                   Sicherung (ZIP) nach /var/lib/lernbuero/sicherungen (vor jedem Update)
"""
import os
import secrets
import sys

from . import db, konten, updates


def _vorlaeufig():
    return secrets.token_urlsafe(9)


def main(argv):
    daten_dir = os.environ.get("LERNBUERO_DATEN", "/var/lib/lernbuero")
    con = db.oeffnen(daten_dir)
    befehl = argv[0] if argv else ""
    if befehl == "einrichtungscode":
        code = konten.einrichtungscode(con)
        print(code if code else "Die Einrichtung ist abgeschlossen (es gibt schon ein Konto).")
    elif befehl == "konten":
        for k in konten.liste(con):
            print("%-8s %-10s %s%s" % (k["kuerzel"], k["rolle"], k["name"], "  (gesperrt)" if k["gesperrt"] else ""))
    elif befehl == "admin" and len(argv) >= 3:
        pw = _vorlaeufig()
        with db.transaktion(con):
            k = konten.anlegen(con, argv[1], " ".join(argv[2:]), "admin", pw, vorlaeufig=True)
        print("Admin %s angelegt. Vorläufiges Passwort: %s (muss bei der ersten Anmeldung geändert werden)" % (k["kuerzel"], pw))
    elif befehl == "passwort" and len(argv) == 2:
        zeile = con.execute("SELECT id FROM lehrkraft WHERE kuerzel = ?", (argv[1].lower(),)).fetchone()
        if zeile is None:
            print("Kein Konto mit dem Kürzel %s." % argv[1])
            return 1
        pw = _vorlaeufig()
        with db.transaktion(con):
            konten.passwort_setzen(con, zeile[0], pw, vorlaeufig=True)
            con.execute("UPDATE lehrkraft SET gesperrt = 0 WHERE id = ?", (zeile[0],))
        print("Vorläufiges Passwort für %s: %s (muss bei der nächsten Anmeldung geändert werden)" % (argv[1].lower(), pw))
    elif befehl == "sicherung":
        print("Sicherung angelegt: %s" % updates.sicherung_ablegen(con, daten_dir))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except konten.KontoFehler as f:
        print(f)
        sys.exit(1)
