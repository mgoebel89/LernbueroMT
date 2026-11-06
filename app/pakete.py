"""Lernpakete (Stufe B): Pflichtaufgaben, Wahlgruppen ("1 von diesen 3"), Zusatzaufgaben zur Differenzierung (nur fuer
Schueler, denen sie empfohlen werden), Kann-Liste mit Verknuepfung zu den Aufgaben, Gelingensnachweis, Fristen.

Ein Paket gehoert einer Klasse (Team darf aendern, Einsicht nur lesen) oder ist eine Vorlage einer Lehrkraft
(klasse_id NULL, nur die Besitzerin sieht sie; kein Teilen im Kollegium, so entschieden). Kopieren geht in eine
andere eigene Klasse oder als Vorlage; Daten (Freigabe, Fristen) werden dabei nicht mitgenommen.

Reihenfolge: Pflichtaufgaben und Wahlgruppen teilen sich eine Folge (pos), die Wahlaufgaben stehen in ihrer Gruppe,
die Zusatzaufgaben in einem eigenen Block. Fristen: Aufgabe vor Wahlgruppe vor Paket; liegt die Frist auf keinem
Unterrichtstag oder faellt der Tag aus, gilt der naechste Unterrichtstag (wird nur angezeigt, nichts geaendert).
Entfernen deaktiviert nur (aktiv = 0), damit spaeter Plaene und Verlauf der Schueler stimmig bleiben.
"""
import re

from . import db, klassen, unterrichtstage

ARTEN = ("pflicht", "wahl", "zusatz")
ZUSATZ_ARTEN = ("vertiefung", "wiederholung")
NACHWEIS_ARTEN = ("moodle", "praxis", "fachgespraech")
ERGEBNISSE = ("gelungen", "punkte", "note")
LINK = re.compile(r"https?://[^\s<>\"']{3,490}")


class PaketFehler(Exception):
    pass


def _text(wert, name, mindestens=1, hoechstens=120):
    wert = re.sub(r"\s+", " ", str(wert or "")).strip()
    if not mindestens <= len(wert) <= hoechstens:
        raise PaketFehler("%s: bitte %d bis %d Zeichen." % (name, mindestens, hoechstens))
    return wert


def _datum(wert):
    if wert in (None, ""):
        return None
    try:
        return unterrichtstage.datum(wert).isoformat()
    except unterrichtstage.TageFehler:
        raise PaketFehler("Bitte ein gültiges Datum angeben.")


def _link(wert):
    wert = str(wert or "").strip()
    if wert and not LINK.fullmatch(wert):
        raise PaketFehler("Der Moodle-Link muss mit https:// beginnen (Adresse der Aufgabe aus der Browserzeile).")
    return wert


# --- Zugriff ---

def _paket(con, pid):
    p = con.execute("SELECT * FROM paket WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise PaketFehler("Dieses Paket gibt es nicht.")
    return p


def pruefen(con, pid, konto, aendern=False):
    p = _paket(con, pid)
    if p["klasse_id"] is None:
        if p["besitzer_id"] != konto["id"]:
            raise klassen.KeinZugriff("Diese Vorlage gehört einer anderen Lehrkraft.")
        return p, "team"
    rolle = klassen.pruefen(con, p["klasse_id"], konto, "aendern" if aendern else "lesen")
    return p, rolle


def _log(con, p, konto, art, **daten):
    db.ereignis(con, p["klasse_id"], None, "lehrkraft", konto["kuerzel"], art, paket=p["titel"], paket_id=p["id"], **daten)


# --- Pakete ---

def _paket_kurz(con, p):
    zahl = con.execute("SELECT COUNT(*) FROM aufgabe WHERE paket_id = ? AND aktiv = 1 AND art != 'zusatz'", (p["id"],)).fetchone()[0]
    return {"id": p["id"], "titel": p["titel"], "lernfeld": p["lernfeld"], "freigabe": p["freigabe"], "frist": p["frist"],
            "archiviert": bool(p["archiviert"]), "aufgaben": zahl, "klasse_id": p["klasse_id"]}


def liste(con, konto, klasse_id):
    klassen.pruefen(con, klasse_id, konto, "lesen")
    return [_paket_kurz(con, p) for p in con.execute(
        "SELECT * FROM paket WHERE klasse_id = ? ORDER BY archiviert, COALESCE(freigabe, '9999'), titel", (klasse_id,))]


def vorlagen(con, konto):
    return [_paket_kurz(con, p) for p in con.execute(
        "SELECT * FROM paket WHERE klasse_id IS NULL AND besitzer_id = ? AND archiviert = 0 ORDER BY titel", (konto["id"],))]


def anlegen(con, konto, klasse_id, titel, lernfeld=""):
    if klasse_id is not None:
        klassen.pruefen(con, klasse_id, konto, "aendern")
    cur = con.execute("INSERT INTO paket (klasse_id, besitzer_id, titel, lernfeld, erstellt) VALUES (?, ?, ?, ?, ?)",
                      (klasse_id, konto["id"], _text(titel, "Titel", 2, 80), _text(lernfeld, "Lernfeld", 0, 20), db.jetzt()))
    p = _paket(con, cur.lastrowid)
    _log(con, p, konto, "paket_angelegt")
    return p["id"]


def aendern(con, konto, pid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    felder = {}
    if "titel" in d:
        felder["titel"] = _text(d["titel"], "Titel", 2, 80)
    if "lernfeld" in d:
        felder["lernfeld"] = _text(d["lernfeld"], "Lernfeld", 0, 20)
    if "frist" in d:
        felder["frist"] = _datum(d["frist"])
    if "freigabe" in d:
        if p["klasse_id"] is None and d["freigabe"]:
            raise PaketFehler("Eine Vorlage lässt sich nicht freigeben. Kopieren Sie sie zuerst in eine Klasse.")
        felder["freigabe"] = _datum(d["freigabe"])
    if "archiviert" in d:
        felder["archiviert"] = 1 if d["archiviert"] else 0
    for spalte, wert in felder.items():
        con.execute("UPDATE paket SET %s = ? WHERE id = ?" % spalte, (wert, pid))
    if felder:
        art = "paket_freigegeben" if felder.get("freigabe") else "paket_geaendert"
        _log(con, p, konto, art, **felder)


# --- Kuerzel und Reihenfolge ---

def _naechste_nummer(con, pid, praefix):
    nummern = [int(z[0][len(praefix):]) for z in con.execute("SELECT kuerzel FROM aufgabe WHERE paket_id = ?", (pid,))
               if z[0].startswith(praefix) and z[0][len(praefix):].isdigit()]
    return max(nummern, default=0) + 1


def _naechste_pos_oben(con, pid):
    a = con.execute("SELECT MAX(pos) FROM aufgabe WHERE paket_id = ? AND art = 'pflicht'", (pid,)).fetchone()[0]
    g = con.execute("SELECT MAX(pos) FROM wahlgruppe WHERE paket_id = ?", (pid,)).fetchone()[0]
    return max(a or 0, g or 0) + 1


def _oben(con, pid):
    """Pflichtaufgaben und Wahlgruppen in ihrer gemeinsamen Folge: [(tabelle, id, pos)]."""
    zeilen = [("aufgabe", z["id"], z["pos"]) for z in con.execute(
        "SELECT id, pos FROM aufgabe WHERE paket_id = ? AND art = 'pflicht' AND aktiv = 1", (pid,))]
    zeilen += [("wahlgruppe", z["id"], z["pos"]) for z in con.execute(
        "SELECT id, pos FROM wahlgruppe WHERE paket_id = ? AND aktiv = 1", (pid,))]
    return sorted(zeilen, key=lambda z: (z[2], z[0], z[1]))


def _tauschen(con, folge, schluessel, richtung):
    """folge: [(tabelle, id, pos)], schluessel: (tabelle, id). Tauscht mit dem Nachbarn und nummeriert neu."""
    i = next((i for i, z in enumerate(folge) if (z[0], z[1]) == schluessel), None)
    j = None if i is None else i + richtung
    if i is None or j is None or not 0 <= j < len(folge):
        return False
    folge[i], folge[j] = folge[j], folge[i]
    for pos, (tabelle, eid, _) in enumerate(folge, 1):
        con.execute("UPDATE %s SET pos = ? WHERE id = ?" % tabelle, (pos, eid))
    return True


def _verschieben(con, pid, tabelle, eid, richtung):
    if tabelle == "aufgabe":
        a = con.execute("SELECT * FROM aufgabe WHERE id = ?", (eid,)).fetchone()
        if a["art"] == "pflicht":
            folge = _oben(con, pid)
        elif a["art"] == "wahl":
            folge = [("aufgabe", z["id"], z["pos"]) for z in con.execute(
                "SELECT id, pos FROM aufgabe WHERE wahlgruppe_id = ? AND aktiv = 1 ORDER BY pos, id", (a["wahlgruppe_id"],))]
        else:
            folge = [("aufgabe", z["id"], z["pos"]) for z in con.execute(
                "SELECT id, pos FROM aufgabe WHERE paket_id = ? AND art = 'zusatz' AND aktiv = 1 ORDER BY pos, id", (pid,))]
    elif tabelle == "wahlgruppe":
        folge = _oben(con, pid)
    else:
        folge = [(tabelle, z["id"], z["pos"]) for z in con.execute(
            "SELECT id, pos FROM %s WHERE paket_id = ? AND aktiv = 1 ORDER BY pos, id" % tabelle, (pid,))]
    return _tauschen(con, folge, (tabelle, eid), richtung)


# --- Aufgaben ---

def _gruppe(con, pid, gid):
    g = con.execute("SELECT * FROM wahlgruppe WHERE id = ? AND paket_id = ? AND aktiv = 1", (gid, pid)).fetchone()
    if g is None:
        raise PaketFehler("Diese Wahlgruppe gibt es nicht.")
    return g


def _aufgabe(con, pid, aid):
    a = con.execute("SELECT * FROM aufgabe WHERE id = ? AND paket_id = ?", (aid, pid)).fetchone()
    if a is None:
        raise PaketFehler("Diese Aufgabe gibt es nicht.")
    return a


def _voraussetzung(con, pid, wert, selbst=None):
    if wert in (None, "", 0):
        return None
    try:
        vid = int(wert)
    except (TypeError, ValueError):
        raise PaketFehler("Ungültige Voraussetzung.")
    if vid == selbst:
        raise PaketFehler("Eine Aufgabe kann nicht ihre eigene Voraussetzung sein.")
    v = _aufgabe(con, pid, vid)
    if not v["aktiv"]:
        raise PaketFehler("Die Voraussetzung ist entfernt.")
    return vid


def aufgabe_anlegen(con, konto, pid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    art = d.get("art") or "pflicht"
    if art not in ARTEN:
        raise PaketFehler("Unbekannte Art.")
    gid = zusatz_art = None
    if art == "pflicht":
        kuerzel, pos = "P%d" % _naechste_nummer(con, pid, "P"), _naechste_pos_oben(con, pid)
    elif art == "wahl":
        g = _gruppe(con, pid, d.get("wahlgruppe_id"))
        gid = g["id"]
        kuerzel = "%s%d" % (g["buchstabe"], _naechste_nummer(con, pid, g["buchstabe"]))
        pos = (con.execute("SELECT MAX(pos) FROM aufgabe WHERE wahlgruppe_id = ?", (gid,)).fetchone()[0] or 0) + 1
    else:
        zusatz_art = d.get("zusatz_art") or "vertiefung"
        if zusatz_art not in ZUSATZ_ARTEN:
            raise PaketFehler("Zusatzaufgabe: Vertiefung oder Wiederholung.")
        kuerzel = "Z%d" % _naechste_nummer(con, pid, "Z")
        pos = (con.execute("SELECT MAX(pos) FROM aufgabe WHERE paket_id = ? AND art = 'zusatz'", (pid,)).fetchone()[0] or 0) + 1
    if d.get("kuerzel"):
        kuerzel = _text(d["kuerzel"], "Kürzel", 1, 6)
    cur = con.execute(
        "INSERT INTO aufgabe (paket_id, kuerzel, titel, art, wahlgruppe_id, zusatz_art, frist, moodle_link, voraussetzung_id, pos, erstellt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pid, kuerzel, _text(d.get("titel"), "Titel der Aufgabe", 2, 120), art, gid, zusatz_art,
         None if art == "zusatz" else _datum(d.get("frist")), _link(d.get("moodle_link")),
         _voraussetzung(con, pid, d.get("voraussetzung_id")), pos, db.jetzt()))
    _log(con, p, konto, "aufgabe_angelegt", kuerzel=kuerzel, titel=d.get("titel"), aufgabenart=art)
    return cur.lastrowid


def aufgabe_aendern(con, konto, pid, aid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    a = _aufgabe(con, pid, aid)
    if d.get("verschieben") in (-1, 1):
        _verschieben(con, pid, "aufgabe", aid, d["verschieben"])
        return
    if d.get("aktiv") is False:
        con.execute("UPDATE aufgabe SET aktiv = 0 WHERE id = ?", (aid,))
        con.execute("UPDATE aufgabe SET voraussetzung_id = NULL WHERE voraussetzung_id = ?", (aid,))
        _log(con, p, konto, "aufgabe_entfernt", kuerzel=a["kuerzel"], titel=a["titel"])
        return
    felder = {}
    if "titel" in d:
        felder["titel"] = _text(d["titel"], "Titel der Aufgabe", 2, 120)
    if "kuerzel" in d:
        felder["kuerzel"] = _text(d["kuerzel"], "Kürzel", 1, 6)
    if "frist" in d and a["art"] != "zusatz":
        felder["frist"] = _datum(d["frist"])
    if "moodle_link" in d:
        felder["moodle_link"] = _link(d["moodle_link"])
    if "voraussetzung_id" in d:
        felder["voraussetzung_id"] = _voraussetzung(con, pid, d["voraussetzung_id"], selbst=aid)
    if "zusatz_art" in d and a["art"] == "zusatz":
        if d["zusatz_art"] not in ZUSATZ_ARTEN:
            raise PaketFehler("Zusatzaufgabe: Vertiefung oder Wiederholung.")
        felder["zusatz_art"] = d["zusatz_art"]
    for spalte, wert in felder.items():
        con.execute("UPDATE aufgabe SET %s = ? WHERE id = ?" % spalte, (wert, aid))
    if felder:
        _log(con, p, konto, "aufgabe_geaendert", kuerzel=felder.get("kuerzel", a["kuerzel"]), felder=sorted(felder))


# --- Wahlgruppen ---

def gruppe_anlegen(con, konto, pid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    belegt = {z[0] for z in con.execute("SELECT buchstabe FROM wahlgruppe WHERE paket_id = ?", (pid,))}
    buchstabe = next(b for b in "ABCDEFGHJKLMNQRSTUVWXY" if b not in belegt)
    waehlen = _waehlen(d.get("waehlen", 1))
    cur = con.execute("INSERT INTO wahlgruppe (paket_id, buchstabe, titel, waehlen, frist, pos) VALUES (?, ?, ?, ?, ?, ?)",
                      (pid, buchstabe, _text(d.get("titel"), "Titel der Wahlgruppe", 0, 80), waehlen, _datum(d.get("frist")),
                       _naechste_pos_oben(con, pid)))
    _log(con, p, konto, "wahlgruppe_angelegt", buchstabe=buchstabe)
    return cur.lastrowid


def _waehlen(wert):
    try:
        wert = int(wert)
    except (TypeError, ValueError):
        raise PaketFehler("Bitte angeben, wie viele Aufgaben gewählt werden.")
    if not 1 <= wert <= 9:
        raise PaketFehler("Gewählt werden 1 bis 9 Aufgaben.")
    return wert


def gruppe_aendern(con, konto, pid, gid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    g = _gruppe(con, pid, gid)
    if d.get("verschieben") in (-1, 1):
        _verschieben(con, pid, "wahlgruppe", gid, d["verschieben"])
        return
    if d.get("aktiv") is False:
        con.execute("UPDATE wahlgruppe SET aktiv = 0 WHERE id = ?", (gid,))
        con.execute("UPDATE aufgabe SET aktiv = 0 WHERE wahlgruppe_id = ?", (gid,))
        _log(con, p, konto, "wahlgruppe_entfernt", buchstabe=g["buchstabe"])
        return
    if "titel" in d:
        con.execute("UPDATE wahlgruppe SET titel = ? WHERE id = ?", (_text(d["titel"], "Titel der Wahlgruppe", 0, 80), gid))
    if "waehlen" in d:
        con.execute("UPDATE wahlgruppe SET waehlen = ? WHERE id = ?", (_waehlen(d["waehlen"]), gid))
    if "frist" in d:
        con.execute("UPDATE wahlgruppe SET frist = ? WHERE id = ?", (_datum(d["frist"]), gid))
    _log(con, p, konto, "wahlgruppe_geaendert", buchstabe=g["buchstabe"])


# --- Kann-Liste ---

def _aufgaben_ids(con, pid, liste):
    ids = []
    for wert in liste or []:
        try:
            a = _aufgabe(con, pid, int(wert))
        except (TypeError, ValueError):
            raise PaketFehler("Ungültige Aufgabe.")
        if a["aktiv"]:
            ids.append(a["id"])
    return sorted(set(ids))


def kann_anlegen(con, konto, pid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    nummern = [int(z[0][1:]) for z in con.execute("SELECT kuerzel FROM kann_aussage WHERE paket_id = ?", (pid,)) if z[0][1:].isdigit()]
    kuerzel = "K%d" % (max(nummern, default=0) + 1)
    pos = (con.execute("SELECT MAX(pos) FROM kann_aussage WHERE paket_id = ?", (pid,)).fetchone()[0] or 0) + 1
    text = _kann_text(d.get("text"))
    cur = con.execute("INSERT INTO kann_aussage (paket_id, kuerzel, text, pos) VALUES (?, ?, ?, ?)", (pid, kuerzel, text, pos))
    con.executemany("INSERT INTO kann_aufgabe (kann_id, aufgabe_id) VALUES (?, ?)",
                    [(cur.lastrowid, a) for a in _aufgaben_ids(con, pid, d.get("aufgaben"))])
    _log(con, p, konto, "kann_angelegt", kuerzel=kuerzel)
    return cur.lastrowid


def _kann_text(wert):
    text = _text(wert, "Kann-Aussage", 3, 200)
    return re.sub(r"^ich kann\s+", "", text, flags=re.IGNORECASE)   # "Ich kann" steht in der Oberflaeche davor


def kann_aendern(con, konto, pid, kid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    k = con.execute("SELECT * FROM kann_aussage WHERE id = ? AND paket_id = ?", (kid, pid)).fetchone()
    if k is None:
        raise PaketFehler("Diese Kann-Aussage gibt es nicht.")
    if d.get("verschieben") in (-1, 1):
        _verschieben(con, pid, "kann_aussage", kid, d["verschieben"])
        return
    if d.get("aktiv") is False:
        con.execute("UPDATE kann_aussage SET aktiv = 0 WHERE id = ?", (kid,))
        _log(con, p, konto, "kann_entfernt", kuerzel=k["kuerzel"])
        return
    if "text" in d:
        con.execute("UPDATE kann_aussage SET text = ? WHERE id = ?", (_kann_text(d["text"]), kid))
    if "aufgaben" in d:
        con.execute("DELETE FROM kann_aufgabe WHERE kann_id = ?", (kid,))
        con.executemany("INSERT INTO kann_aufgabe (kann_id, aufgabe_id) VALUES (?, ?)",
                        [(kid, a) for a in _aufgaben_ids(con, pid, d["aufgaben"])])
    _log(con, p, konto, "kann_geaendert", kuerzel=k["kuerzel"])


# --- Gelingensnachweis ---

def _nachweis_werte(d, alt=None):
    alt = dict(alt) if alt else {}
    art = d.get("art", alt.get("art", "moodle"))
    if art not in NACHWEIS_ARTEN:
        raise PaketFehler("Art: Moodle-Test, praktische Prüfung oder Fachgespräch.")
    ergebnis = d.get("ergebnis", alt.get("ergebnis", "gelungen"))
    if ergebnis not in ERGEBNISSE:
        raise PaketFehler("Unbekannte Ergebnisform.")
    max_punkte = d.get("max_punkte", alt.get("max_punkte"))
    if ergebnis == "punkte":
        try:
            max_punkte = int(max_punkte)
        except (TypeError, ValueError):
            raise PaketFehler("Bitte die höchste Punktzahl angeben.")
        if not 1 <= max_punkte <= 1000:
            raise PaketFehler("Höchste Punktzahl: 1 bis 1000.")
    else:
        max_punkte = None
    titel = _text(d.get("titel", alt.get("titel", "")), "Titel", 0, 80)
    link = _link(d.get("moodle_link", alt.get("moodle_link", ""))) if art == "moodle" else ""
    frist = _datum(d["frist"]) if "frist" in d else alt.get("frist")
    return titel, art, ergebnis, max_punkte, frist, link


def nachweis_anlegen(con, konto, pid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    pos = (con.execute("SELECT MAX(pos) FROM nachweis WHERE paket_id = ?", (pid,)).fetchone()[0] or 0) + 1
    cur = con.execute("INSERT INTO nachweis (paket_id, titel, art, ergebnis, max_punkte, frist, moodle_link, pos) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (pid,) + _nachweis_werte(d) + (pos,))
    _log(con, p, konto, "nachweis_angelegt", nachweisart=d.get("art"))
    return cur.lastrowid


def nachweis_aendern(con, konto, pid, nid, d):
    p, _ = pruefen(con, pid, konto, aendern=True)
    n = con.execute("SELECT * FROM nachweis WHERE id = ? AND paket_id = ?", (nid, pid)).fetchone()
    if n is None:
        raise PaketFehler("Diesen Gelingensnachweis gibt es nicht.")
    if d.get("aktiv") is False:
        con.execute("UPDATE nachweis SET aktiv = 0 WHERE id = ?", (nid,))
        _log(con, p, konto, "nachweis_entfernt")
        return
    con.execute("UPDATE nachweis SET titel = ?, art = ?, ergebnis = ?, max_punkte = ?, frist = ?, moodle_link = ? WHERE id = ?",
                _nachweis_werte(d, n) + (nid,))
    _log(con, p, konto, "nachweis_geaendert")


# --- Gesamtansicht ---

def _frist(con, klasse_id, eigen, *ersatz):
    """(gesetzt, wirksam, hinweis, quelle): eigene Frist oder die naechsthoehere."""
    quelle = "eigen" if eigen else None
    frist = eigen
    for name, wert in ersatz:
        if frist is None and wert:
            frist, quelle = wert, name
    if frist is None:
        return {"frist": None, "wirksam": None, "hinweis": "", "quelle": None}
    wirksam, hinweis = unterrichtstage.wirksame_frist(con, klasse_id, frist) if klasse_id else (frist, "")
    return {"frist": frist, "wirksam": wirksam, "hinweis": hinweis, "quelle": quelle}


def holen(con, konto, pid):
    p, rolle = pruefen(con, pid, konto)
    return struktur(con, p, rolle)


def struktur(con, p, rolle=None):
    """Das ganze Paket mit wirksamen Fristen, ohne Rechtepruefung (fuer holen() und den Lernplan der Schueler)."""
    pid = p["id"]
    kid = p["klasse_id"]
    gruppen = {g["id"]: g for g in con.execute("SELECT * FROM wahlgruppe WHERE paket_id = ? AND aktiv = 1", (pid,))}
    kann_links = {}
    for z in con.execute("SELECT ka.kann_id, ka.aufgabe_id FROM kann_aufgabe ka JOIN kann_aussage k ON k.id = ka.kann_id "
                         "WHERE k.paket_id = ?", (pid,)):
        kann_links.setdefault(z["kann_id"], []).append(z["aufgabe_id"])
    aufgaben = con.execute("SELECT * FROM aufgabe WHERE paket_id = ? AND aktiv = 1 ORDER BY pos, id", (pid,)).fetchall()
    kuerzel = {a["id"]: a["kuerzel"] for a in aufgaben}

    def aufgabe(a):
        g = gruppen.get(a["wahlgruppe_id"])
        frist = _frist(con, kid, a["frist"], ("gruppe", g["frist"] if g else None), ("paket", p["frist"])) if a["art"] != "zusatz" \
            else {"frist": None, "wirksam": None, "hinweis": "", "quelle": None}
        return {"id": a["id"], "kuerzel": a["kuerzel"], "titel": a["titel"], "art": a["art"], "wahlgruppe_id": a["wahlgruppe_id"],
                "zusatz_art": a["zusatz_art"], "moodle_link": a["moodle_link"], "voraussetzung_id": a["voraussetzung_id"],
                "voraussetzung": kuerzel.get(a["voraussetzung_id"]),
                "kann": sorted(k for k, ids in kann_links.items() if a["id"] in ids), **frist, "eigene_frist": a["frist"]}

    ablauf = []
    for tabelle, eid, _ in _oben(con, pid):
        if tabelle == "aufgabe":
            ablauf.append(dict(aufgabe(next(a for a in aufgaben if a["id"] == eid)), typ="aufgabe"))
        else:
            g = gruppen[eid]
            ablauf.append({"typ": "gruppe", "id": g["id"], "buchstabe": g["buchstabe"], "titel": g["titel"], "waehlen": g["waehlen"],
                           **_frist(con, kid, g["frist"], ("paket", p["frist"])), "eigene_frist": g["frist"],
                           "aufgaben": [aufgabe(a) for a in aufgaben if a["wahlgruppe_id"] == g["id"]]})
    zusatz = [aufgabe(a) for a in aufgaben if a["art"] == "zusatz"]
    kann = [{"id": k["id"], "kuerzel": k["kuerzel"], "text": k["text"], "aufgaben": sorted(kann_links.get(k["id"], []),
             key=lambda i: kuerzel.get(i, "")), "aufgaben_kuerzel": sorted(kuerzel[i] for i in kann_links.get(k["id"], []) if i in kuerzel)}
            for k in con.execute("SELECT * FROM kann_aussage WHERE paket_id = ? AND aktiv = 1 ORDER BY pos, id", (pid,))]
    nachweise = [dict(n, **_frist(con, kid, n["frist"], ("paket", p["frist"])))
                 for n in ({"id": z["id"], "titel": z["titel"], "art": z["art"], "ergebnis": z["ergebnis"], "max_punkte": z["max_punkte"],
                            "frist": z["frist"], "moodle_link": z["moodle_link"]}
                           for z in con.execute("SELECT * FROM nachweis WHERE paket_id = ? AND aktiv = 1 ORDER BY pos, id", (pid,)))]
    for n in nachweise:   # die Hilfsfelder aus _frist ueberschreiben "frist" nicht mit der Paketfrist
        n["eigene_frist"] = con.execute("SELECT frist FROM nachweis WHERE id = ?", (n["id"],)).fetchone()[0]
    klasse = con.execute("SELECT name FROM klasse WHERE id = ?", (kid,)).fetchone() if kid else None
    freigabe = None
    if p["freigabe"] and kid:
        w, h = unterrichtstage.wirksame_frist(con, kid, p["freigabe"])
        freigabe = {"datum": p["freigabe"], "wirksam": w, "hinweis": h}
    return {"id": p["id"], "titel": p["titel"], "lernfeld": p["lernfeld"], "klasse_id": kid, "klasse": klasse["name"] if klasse else None,
            "vorlage": kid is None, "rolle": rolle, "darf_aendern": rolle == "team", "archiviert": bool(p["archiviert"]),
            "freigabe": freigabe, "frist": _frist(con, kid, p["frist"]), "ablauf": ablauf, "zusatz": zusatz, "kann": kann,
            "nachweise": nachweise}


# --- Kopieren ---

def kopieren(con, konto, pid, ziel_klasse_id=None, titel=None):
    """Tiefe Kopie in eine Klasse (Team) oder als eigene Vorlage (ziel_klasse_id None). Ohne Daten (Freigabe, Fristen)."""
    p, _ = pruefen(con, pid, konto)
    if ziel_klasse_id is not None:
        klassen.pruefen(con, ziel_klasse_id, konto, "aendern")
    neu = con.execute("INSERT INTO paket (klasse_id, besitzer_id, titel, lernfeld, aus_paket_id, erstellt) VALUES (?, ?, ?, ?, ?, ?)",
                      (ziel_klasse_id, konto["id"], _text(titel or p["titel"], "Titel", 2, 80), p["lernfeld"], pid, db.jetzt())).lastrowid
    gruppen = {}
    for g in con.execute("SELECT * FROM wahlgruppe WHERE paket_id = ? AND aktiv = 1", (pid,)).fetchall():
        gruppen[g["id"]] = con.execute("INSERT INTO wahlgruppe (paket_id, buchstabe, titel, waehlen, pos) VALUES (?, ?, ?, ?, ?)",
                                       (neu, g["buchstabe"], g["titel"], g["waehlen"], g["pos"])).lastrowid
    aufgaben = {}
    alte = con.execute("SELECT * FROM aufgabe WHERE paket_id = ? AND aktiv = 1", (pid,)).fetchall()
    for a in alte:
        aufgaben[a["id"]] = con.execute(
            "INSERT INTO aufgabe (paket_id, kuerzel, titel, art, wahlgruppe_id, zusatz_art, moodle_link, pos, erstellt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (neu, a["kuerzel"], a["titel"], a["art"], gruppen.get(a["wahlgruppe_id"]), a["zusatz_art"], a["moodle_link"], a["pos"],
             db.jetzt())).lastrowid
    for a in alte:
        if a["voraussetzung_id"] in aufgaben:
            con.execute("UPDATE aufgabe SET voraussetzung_id = ? WHERE id = ?", (aufgaben[a["voraussetzung_id"]], aufgaben[a["id"]]))
    for k in con.execute("SELECT * FROM kann_aussage WHERE paket_id = ? AND aktiv = 1", (pid,)).fetchall():
        kid = con.execute("INSERT INTO kann_aussage (paket_id, kuerzel, text, pos) VALUES (?, ?, ?, ?)",
                          (neu, k["kuerzel"], k["text"], k["pos"])).lastrowid
        con.executemany("INSERT INTO kann_aufgabe (kann_id, aufgabe_id) VALUES (?, ?)",
                        [(kid, aufgaben[z[0]]) for z in con.execute("SELECT aufgabe_id FROM kann_aufgabe WHERE kann_id = ?", (k["id"],))
                         if z[0] in aufgaben])
    for n in con.execute("SELECT * FROM nachweis WHERE paket_id = ? AND aktiv = 1", (pid,)).fetchall():
        con.execute("INSERT INTO nachweis (paket_id, titel, art, ergebnis, max_punkte, moodle_link, pos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (neu, n["titel"], n["art"], n["ergebnis"], n["max_punkte"], n["moodle_link"], n["pos"]))
    _log(con, _paket(con, neu), konto, "paket_kopiert", aus=p["titel"], aus_id=pid)
    return neu
