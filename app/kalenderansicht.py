"""Kalender der Lehrkraft (Stufe F): Woche, Monat oder Halbjahr mit den Ebenen
  dienst      Termine aus dem eigenen Dienstkalender (nur fuer die Lehrkraft selbst)
  unterricht  Unterrichtstage der Klassen (Hintergrund), Paket-Freigaben
  sprech      eigene Sprechzeiten mit Belegung
  pruefung    eigene Pruefungszeiten mit Belegung
  frist       Fristen von Aufgaben, Wahlgruppen und Paketen
  gn          Fristen der Gelingensnachweise
  ferien      Ferien, Ausfall, "findet statt, ohne Lehrkraft"
Je Klasse oder fuer alle Klassen der Lehrkraft (Team und Einsicht, ohne Archiv). Die Oberflaeche blendet die Ebenen
ein und aus; der Server liefert immer alle.
"""
import datetime

from . import kalender, klassen, nachweise, pakete, termine, unterrichtstage as ut

TAG = datetime.timedelta(days=1)
MAX_TAGE = 200


class KalenderansichtFehler(Exception):
    pass


def halbjahr(heute):
    """(von, bis, name) des Halbjahres, in dem heute liegt: 1. August bis 31. Januar, 1. Februar bis 31. Juli."""
    if heute.month >= 8:
        j = heute.year
        return datetime.date(j, 8, 1), datetime.date(j + 1, 1, 31), "1. Halbjahr %d/%02d" % (j, (j + 1) % 100)
    if heute.month == 1:
        j = heute.year - 1
        return datetime.date(j, 8, 1), datetime.date(j + 1, 1, 31), "1. Halbjahr %d/%02d" % (j, (j + 1) % 100)
    j = heute.year - 1
    return datetime.date(j + 1, 2, 1), datetime.date(j + 1, 7, 31), "2. Halbjahr %d/%02d" % (j, (j + 1) % 100)


def _klassen(con, konto, klasse_id):
    if klasse_id:
        klassen.pruefen(con, klasse_id, konto, "lesen")
        k = con.execute("SELECT id, name FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
        return [{"id": k["id"], "name": k["name"]}]
    return [{"id": k["id"], "name": k["name"]} for k in klassen.liste(con, konto) if k["rolle"] in ("team", "einsicht")]


def ansicht(con, konto, von, bis, klasse_id=None):
    if bis < von or (bis - von).days > MAX_TAGE:
        raise KalenderansichtFehler("Höchstens %d Tage auf einmal." % MAX_TAGE)
    liste = _klassen(con, konto, klasse_id)
    mehrere = len(liste) > 1
    tage, eintraege = {}, []

    def tag(d):
        return tage.setdefault(d, {"unterricht": [], "ferien": None})

    def neu(d, ebene, text, zeit="", titel="", klasse=None, details=None, art=None):
        eintraege.append({"datum": d, "ebene": ebene, "art": art or ebene, "zeit": zeit, "text": text, "titel": titel or text,
                          "klasse": klasse, "details": details or []})

    # Ferien (fuer alle gleich)
    for f in con.execute("SELECT von, bis, name FROM ferien WHERE aktiv = 1 AND bis >= ? AND von <= ? ORDER BY von",
                         (von.isoformat(), bis.isoformat())):
        a, b = max(von, ut.datum(f["von"])), min(bis, ut.datum(f["bis"]))
        d = a
        while d <= b:
            tag(d.isoformat())["ferien"] = f["name"]
            d += TAG
        neu(a.isoformat(), "ferien", f["name"], titel="%s (%s bis %s)" % (f["name"], ut.datum(f["von"]).strftime("%d.%m."),
                                                                          ut.datum(f["bis"]).strftime("%d.%m.%Y")), art="aus")

    for k in liste:
        name = k["name"]
        zusatz = " (%s)" % name if mehrere else ""
        # Unterrichtstage, Ausfall, ohne Lehrkraft
        for t in ut.tage(con, k["id"], von, bis):
            if t["status"] in ("unterricht", "ohne"):
                tag(t["datum"])["unterricht"].append({"klasse": name, "von": t["von"], "bis": t["bis"], "ohne": t["status"] == "ohne"})
            if t["status"] == "ausfall":
                neu(t["datum"], "ferien", "Ausfall%s: %s" % (zusatz, t["grund"]), klasse=name, art="aus")
            elif t["status"] == "ohne":
                neu(t["datum"], "ferien", "ohne Lehrkraft%s: %s" % (zusatz, t["grund"]), klasse=name, art="ohne")
        # eigene Sprech- und Pruefungszeiten mit Belegung
        for z in con.execute("SELECT * FROM zeitfenster WHERE klasse_id = ? AND lehrkraft_id = ? AND aktiv = 1", (k["id"], konto["id"])).fetchall():
            for d, t in termine.fenstertage(con, z, von, bis):
                if t is None or t["status"] != "unterricht":
                    continue
                gebucht = termine._gebucht(con, z["id"], d.isoformat())
                belegt = kalender.dienst_belegt(con, konto["id"], d)
                plaetze = termine.plaetze(z)
                gesperrt = [b for b, e in plaetze if b not in gebucht and kalender.kollision(b, e, belegt)]
                details = ["%s %s · %s" % (b, "%s %s" % (g["vorname"], g["nachname"]), termine._anlass_text(con, g))
                           for b, g in sorted(gebucht.items())]
                details += ["%s nicht buchbar (Dienstkalender)" % b for b in gesperrt]
                text = "%s %s %d/%d" % (z["von"], termine.ARTEN[z["art"]], len(gebucht), len(plaetze))
                neu(d.isoformat(), z["art"], text + zusatz, zeit=z["von"], klasse=name, details=details,
                    titel="%s %s–%s%s: %d von %d Plätzen gebucht" % (termine.ARTEN[z["art"]], z["von"], z["bis"], zusatz, len(gebucht), len(plaetze)))
        # Fristen, Gelingensnachweise, Freigaben
        for p in con.execute("SELECT * FROM paket WHERE klasse_id = ? AND archiviert = 0", (k["id"],)).fetchall():
            s = pakete.struktur(con, p)
            entwurf = "" if p["freigabe"] else " (Entwurf)"
            fristen = {}
            for e in s["ablauf"]:
                if e["typ"] == "gruppe":
                    if e["quelle"] == "eigen" and e["wirksam"]:
                        fristen.setdefault(e["wirksam"], []).append("Wahl " + e["buchstabe"])
                    for a in e["aufgaben"]:
                        if a["quelle"] == "eigen" and a["wirksam"]:
                            fristen.setdefault(a["wirksam"], []).append(a["kuerzel"])
                elif e["quelle"] == "eigen" and e["wirksam"]:
                    fristen.setdefault(e["wirksam"], []).append(e["kuerzel"])
            for d, kz in fristen.items():
                if von.isoformat() <= d <= bis.isoformat():
                    neu(d, "frist", "Frist " + ", ".join(kz) + zusatz, klasse=name, titel="Frist %s · %s%s%s" % (", ".join(kz), s["titel"], entwurf, zusatz))
            pf = s["frist"]["wirksam"]
            if pf and von.isoformat() <= pf <= bis.isoformat():
                neu(pf, "frist", "Paket-Frist " + s["titel"] + zusatz, klasse=name, titel="Paket-Frist %s%s%s" % (s["titel"], entwurf, zusatz))
            for n in s["nachweise"]:
                if n["wirksam"] and von.isoformat() <= n["wirksam"] <= bis.isoformat():
                    neu(n["wirksam"], "gn", "GN " + nachweise.ART_TEXT[n["art"]] + zusatz, klasse=name, art="gn",
                        titel="Gelingensnachweis %s%s · %s%s%s" % (nachweise.ART_TEXT[n["art"]], " " + n["titel"] if n["titel"] else "",
                                                                  s["titel"], entwurf, zusatz))
            fg = s["freigabe"]["wirksam"] if s["freigabe"] else None
            if fg and von.isoformat() <= fg <= bis.isoformat():
                neu(fg, "unterricht", s["titel"] + " frei" + zusatz, klasse=name, art="info", titel="Freigabe des Pakets %s%s" % (s["titel"], zusatz))

    # eigener Dienstkalender
    for t in kalender.dienst_termine(con, konto["id"], von, bis):
        if t["ganztags"]:
            a, b = max(von, ut.datum(t["beginn"][:10])), min(bis, ut.datum(t["ende"][:10]))
            d = a
            while d <= b:
                neu(d.isoformat(), "dienst", t["titel"], titel=t["titel"] + (" · " + t["ort"] if t["ort"] else ""), art="dienst")
                d += TAG
        else:
            d = t["beginn"][:10]
            if d < von.isoformat():
                continue
            zeit = t["beginn"][11:16]
            neu(d, "dienst", zeit + " " + t["titel"], zeit=zeit, art="dienst",
                titel="%s–%s %s%s" % (zeit, t["ende"][11:16], t["titel"], " · " + t["ort"] if t["ort"] else ""))

    rang = {"ferien": 0, "dienst": 1, "unterricht": 2, "sprech": 3, "pruefung": 3, "frist": 4, "gn": 5}
    eintraege.sort(key=lambda e: (e["datum"], rang.get(e["ebene"], 9), e["zeit"] or "", e["text"]))
    return {"von": von.isoformat(), "bis": bis.isoformat(), "klassen": liste, "alle_klassen": _klassen(con, konto, None) if klasse_id else liste,
            "tage": tage, "eintraege": eintraege,
            "dienst": kalender.abo_status(con, "dienst", konto["id"]), "pakete_da": kalender.icalendar is not None}
