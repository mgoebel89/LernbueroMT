"""Moodle-Teilnehmerliste einlesen und mit der Klasse abgleichen (keine Schnittstelle, nur der Datei-Export).

Gelesen wird dasselbe Format wie im Lehrerkalender (drs-lxc, services/moodle_csv.py):
  - Moodle-Export als CSV mit Kopfzeile (Vorname, Nachname, ...; Trenner , ; oder Tab, gern mit BOM)
  - klassische Liste ohne Kopfzeile: Nachname;Vorname je Zeile
  - zusaetzlich JSON (Moodle "Herunterladen als JSON": Liste von Objekten, auch verschachtelt)
Gibt es eine Spalte "Rolle(n)", werden Trainer/innen und Lehrkraefte uebersprungen. Gespeichert werden nur Vor- und
Nachname: E-Mail, ID-Nummer und alle anderen Spalten werden nicht uebernommen.

Abgleich wie im drs-lxc: Namen werden gefaltet (Gross/klein, Umlaute, Akzente, Leer- und Trennzeichen), "Meyer" trifft
aber nie "Meyer-Schmidt". Der volle Name schlaegt den Nachnamen, in ZWEI Durchgaengen: sonst schnappt ein
Nachnamens-Treffer einen Schueler weg, den eine spaetere Zeile eindeutig beansprucht. Gleiche Nachnamen ohne passenden
Vornamen bleiben offen (lieber neu anlegen als zwei Schueler vertauschen).
"""
import csv
import io
import json
import re
import unicodedata

MAX_ZEICHEN = 2_000_000

NACHNAME = ("nachname", "lastname", "last name", "surname", "familienname")
VORNAME = ("vorname", "firstname", "first name", "given name")
ROLLE = ("rolle", "rollen", "role", "roles")
LEHRKRAFT_ROLLEN = ("trainer", "lehrer", "teacher", "manager", "kursersteller", "coursecreator")


class MoodleFehler(Exception):
    pass


def falten(text):
    """'Müller-Lüdenscheidt ' -> 'muellerluedenscheidt'"""
    t = str(text or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", t)


def _norm(s):
    return str(s or "").strip().strip('"').strip("'").lower()


def _spalte(kopf, schluessel):
    for i, h in enumerate(kopf):
        if any(k == h for k in schluessel):
            return i
    for i, h in enumerate(kopf):
        if any(k in h for k in schluessel):
            return i
    return None


def _ist_lehrkraft(rolle):
    r = _norm(rolle)
    return any(k in r for k in LEHRKRAFT_ROLLEN)


def _eintrag(vorname, nachname, rolle=""):
    vorname, nachname = re.sub(r"\s+", " ", str(vorname or "")).strip(), re.sub(r"\s+", " ", str(nachname or "")).strip()
    if not nachname:
        return None
    return {"vorname": vorname[:60], "nachname": nachname[:60], "lehrkraft": _ist_lehrkraft(rolle), "rolle": str(rolle or "").strip()[:60]}


def _csv(text):
    zeilen = [z for z in text.splitlines() if z.strip()]
    if not zeilen:
        return [], "leer"
    erste = _norm(zeilen[0])
    if any(k in erste for k in VORNAME) and any(k in erste for k in NACHNAME):
        zaehler = {t: zeilen[0].count(t) for t in (",", ";", "\t")}
        trenner = max(zaehler, key=zaehler.get)
        tabelle = list(csv.reader(io.StringIO(text), delimiter=trenner, quotechar='"'))
        kopf = [_norm(h) for h in tabelle[0]]
        i_nach, i_vor, i_rolle = _spalte(kopf, NACHNAME), _spalte(kopf, VORNAME), _spalte(kopf, ROLLE)
        aus = []
        for zeile in tabelle[1:]:
            if not zeile or not any(z.strip() for z in zeile):
                continue
            wert = lambda i: zeile[i] if i is not None and i < len(zeile) else ""
            e = _eintrag(wert(i_vor), wert(i_nach), wert(i_rolle))
            if e:
                aus.append(e)
        return aus, "moodle-csv"
    aus = []
    for zeile in zeilen:
        teile = re.split(r"[;\t,]", zeile.strip())
        e = _eintrag(teile[1] if len(teile) > 1 else "", teile[0])
        if e:
            aus.append(e)
    return aus, "liste"


def _json(daten):
    objekte = []

    def sammeln(x):
        if isinstance(x, list):
            for y in x:
                sammeln(y)
        elif isinstance(x, dict):
            if any(isinstance(v, (list, dict)) for v in x.values()) and not any(_norm(k) in VORNAME + NACHNAME for k in x):
                for v in x.values():
                    sammeln(v)
            else:
                objekte.append(x)
    sammeln(daten)
    aus = []
    for o in objekte:
        kopf = [_norm(k) for k in o]
        werte = list(o.values())
        i_nach, i_vor, i_rolle = _spalte(kopf, NACHNAME), _spalte(kopf, VORNAME), _spalte(kopf, ROLLE)
        if i_nach is None:
            continue
        e = _eintrag(werte[i_vor] if i_vor is not None else "", werte[i_nach], werte[i_rolle] if i_rolle is not None else "")
        if e:
            aus.append(e)
    return aus, "moodle-json"


def lesen(text):
    """Text der Datei -> (Eintraege, Format). Eintrag: {vorname, nachname, lehrkraft, rolle}."""
    if not isinstance(text, str) or not text.strip():
        raise MoodleFehler("Die Datei ist leer.")
    if len(text) > MAX_ZEICHEN:
        raise MoodleFehler("Die Datei ist zu groß.")
    text = text.lstrip("﻿")
    if text.lstrip()[:1] in "[{":
        try:
            eintraege, art = _json(json.loads(text))
        except ValueError:
            raise MoodleFehler("Die JSON-Datei ist nicht lesbar.")
    else:
        eintraege, art = _csv(text)
    if not eintraege:
        raise MoodleFehler("In der Datei wurde kein einziger Name erkannt. Erwartet wird die Teilnehmerliste aus Moodle "
                           "(Spalten Vorname und Nachname) oder eine Liste Nachname;Vorname.")
    return eintraege, art


def abgleich(vorhandene, eintraege):
    """vorhandene: Zeilen aus `schueler` (id, vorname, nachname, aktiv). Rueckgabe: Liste von Zeilen fuer die
    Zuordnungstabelle: {aktion, vorname, nachname, rolle, schueler_id, hinweis}
      behalten     schon in der Klasse
      reaktivieren in der Klasse, aber archiviert: wird wieder aktiv
      neu          wird angelegt
      lehrkraft    Trainer/in o. ae., wird uebersprungen
      doppelt      steht zweimal in der Datei, nur der erste Eintrag zaehlt
      fehlt        in der Klasse, aber nicht mehr in Moodle (archivieren nur auf Wunsch)
    """
    frei = {s["id"]: s for s in vorhandene}
    ergebnis = [None] * len(eintraege)
    gesehen = set()
    schueler_zeilen = []
    for i, e in enumerate(eintraege):
        if e["lehrkraft"]:
            ergebnis[i] = dict(e, aktion="lehrkraft", schueler_id=None, hinweis="")
            continue
        schluessel = falten(e["vorname"]) + "|" + falten(e["nachname"])
        if schluessel in gesehen:
            ergebnis[i] = dict(e, aktion="doppelt", schueler_id=None, hinweis="steht mehrfach in der Datei")
            continue
        gesehen.add(schluessel)
        schueler_zeilen.append(i)

    def treffer(s, i, hinweis=""):
        e = eintraege[i]
        ergebnis[i] = dict(e, aktion="behalten" if s["aktiv"] else "reaktivieren", schueler_id=s["id"], hinweis=hinweis)
        del frei[s["id"]]

    # 1. Durchgang: voller Name
    for i in schueler_zeilen:
        e = eintraege[i]
        kandidaten = [s for s in frei.values()
                      if falten(s["vorname"]) == falten(e["vorname"]) and falten(s["nachname"]) == falten(e["nachname"])]
        if len(kandidaten) == 1:
            treffer(kandidaten[0], i)
    # 2. Durchgang: nur Nachname, wenn er auf beiden Seiten eindeutig ist
    offen = [i for i in schueler_zeilen if ergebnis[i] is None]
    for i in offen:
        e = eintraege[i]
        nn = falten(e["nachname"])
        kandidaten = [s for s in frei.values() if falten(s["nachname"]) == nn]
        gleiche = [j for j in offen if ergebnis[j] is None and falten(eintraege[j]["nachname"]) == nn]
        if len(kandidaten) == 1 and len(gleiche) == 1:
            s = kandidaten[0]
            treffer(s, i, "Vorname im Lernbüro: %s" % s["vorname"])
    for i in schueler_zeilen:
        if ergebnis[i] is None:
            ergebnis[i] = dict(eintraege[i], aktion="neu", schueler_id=None, hinweis="")
    for s in sorted(frei.values(), key=lambda s: (s["nachname"], s["vorname"])):
        if s["aktiv"]:
            ergebnis.append({"vorname": s["vorname"], "nachname": s["nachname"], "lehrkraft": False, "rolle": "",
                             "aktion": "fehlt", "schueler_id": s["id"], "hinweis": ""})
    return ergebnis
