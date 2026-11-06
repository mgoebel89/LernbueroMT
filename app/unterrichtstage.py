"""Unterrichtstage je Klasse: Regeln (Wochentag, Uhrzeit, jede / gerade / ungerade KW, gueltig von bis) wie die
Projektzeiten im TrackingDRS, abzueglich Ferien (Schulkalender-Abo oder von Hand). Dazu besondere Tage der Klasse:

  ausfall  der Unterricht faellt aus (Zwischenpruefung, Krankheit ohne Vertretung). Geplantes muss neu geplant werden,
           eine Verschiebung deswegen zaehlt nicht gegen den Schueler, Fristen wandern auf den naechsten Unterrichtstag.
  ohne     das Lernbuero findet statt, aber ohne die Lehrkraefte der Klasse (Fortbildung, Vertretung): Plan gilt,
           Hilfe-Knopf und Termine sind an dem Tag gesperrt.

Beides darf jede Lehrkraft im Team der Klasse eintragen, auch kurzfristig oder nachtraeglich.
"""
import datetime
import re

from . import db, klassen

TAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
RHYTHMEN = ("jede", "gerade", "ungerade")
UHRZEIT = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
TAG = datetime.timedelta(days=1)
BESONDERS = ("ausfall", "ohne")


class TageFehler(Exception):
    pass


def datum(wert, feld="ein Datum"):
    try:
        return datetime.date.fromisoformat(str(wert or "")[:10])
    except ValueError:
        raise TageFehler("Bitte %s angeben." % feld)


def uhrzeit(wert, feld="eine Uhrzeit"):
    wert = str(wert or "").strip()
    if len(wert) == 4 and wert[1] == ":":
        wert = "0" + wert
    if not UHRZEIT.fullmatch(wert):
        raise TageFehler("Bitte %s als Uhrzeit (HH:MM) angeben." % feld)
    return wert


def _grund(wert):
    wert = re.sub(r"\s+", " ", str(wert or "")).strip()
    if not 2 <= len(wert) <= 80:
        raise TageFehler("Bitte einen Grund mit 2 bis 80 Zeichen angeben.")
    return wert


def schuljahr_grenzen(heute=None):
    """1. August bis 31. Juli des laufenden Schuljahres."""
    heute = heute or db.heute()
    jahr = heute.year if heute.month >= 8 else heute.year - 1
    return datetime.date(jahr, 8, 1), datetime.date(jahr + 1, 7, 31)


# --- Regeln ---

def _regel_daten(z):
    return {"id": z["id"], "wochentag": z["wochentag"], "tag": TAGE[z["wochentag"]], "rhythmus": z["rhythmus"],
            "von": z["von"], "bis": z["bis"], "gueltig_von": z["gueltig_von"], "gueltig_bis": z["gueltig_bis"], "aktiv": bool(z["aktiv"])}


def regeln(con, klasse_id, nur_aktiv=True):
    sql = "SELECT * FROM unterrichtsregel WHERE klasse_id = ?" + (" AND aktiv = 1" if nur_aktiv else "") + " ORDER BY wochentag, von"
    return [_regel_daten(z) for z in con.execute(sql, (klasse_id,))]


def _regel_pruefen(d):
    try:
        wochentag = int(d.get("wochentag"))
    except (TypeError, ValueError):
        raise TageFehler("Bitte einen Wochentag wählen.")
    if not 0 <= wochentag <= 6:
        raise TageFehler("Bitte einen Wochentag wählen.")
    rhythmus = d.get("rhythmus") or "jede"
    if rhythmus not in RHYTHMEN:
        raise TageFehler("Unbekannter Rhythmus.")
    von, bis = uhrzeit(d.get("von"), "den Beginn"), uhrzeit(d.get("bis"), "das Ende")
    if bis <= von:
        raise TageFehler("Das Ende muss nach dem Beginn liegen.")
    anfang, ende = schuljahr_grenzen()
    gv = datum(d.get("gueltig_von") or anfang.isoformat(), "„gültig von“")
    gb = datum(d.get("gueltig_bis") or ende.isoformat(), "„gültig bis“")
    if gb < gv:
        raise TageFehler("„Gültig bis“ liegt vor „gültig von“.")
    return wochentag, rhythmus, von, bis, gv.isoformat(), gb.isoformat()


def regel_anlegen(con, konto, klasse_id, d):
    klassen.pruefen(con, klasse_id, konto, "aendern")
    werte = _regel_pruefen(d)
    cur = con.execute("INSERT INTO unterrichtsregel (klasse_id, wochentag, rhythmus, von, bis, gueltig_von, gueltig_bis, erstellt) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (klasse_id,) + werte + (db.jetzt(),))
    db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "regel_angelegt", tag=TAGE[werte[0]], rhythmus=werte[1],
                von=werte[2], bis=werte[3])
    return cur.lastrowid


def regel_aendern(con, konto, klasse_id, regel_id, d):
    klassen.pruefen(con, klasse_id, konto, "aendern")
    alt = con.execute("SELECT * FROM unterrichtsregel WHERE id = ? AND klasse_id = ?", (regel_id, klasse_id)).fetchone()
    if alt is None:
        raise TageFehler("Diese Regel gibt es nicht.")
    if d.get("aktiv") is False:
        con.execute("UPDATE unterrichtsregel SET aktiv = 0 WHERE id = ?", (regel_id,))
        db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "regel_entfernt", tag=TAGE[alt["wochentag"]])
        return
    werte = _regel_pruefen(dict(_regel_daten(alt), **d))
    con.execute("UPDATE unterrichtsregel SET wochentag = ?, rhythmus = ?, von = ?, bis = ?, gueltig_von = ?, gueltig_bis = ? WHERE id = ?",
                werte + (regel_id,))
    db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "regel_geaendert", tag=TAGE[werte[0]])


# --- Besondere Tage ---

def besonders_anlegen(con, konto, klasse_id, d):
    klassen.pruefen(con, klasse_id, konto, "aendern")
    art = d.get("art")
    if art not in BESONDERS:
        raise TageFehler("Bitte „fällt aus“ oder „findet statt, ohne Sie“ wählen.")
    von = datum(d.get("von"), "den ersten Tag")
    bis = datum(d.get("bis") or von.isoformat(), "den letzten Tag")
    if bis < von:
        raise TageFehler("Der letzte Tag liegt vor dem ersten.")
    if (bis - von).days > 120:
        raise TageFehler("Höchstens 120 Tage auf einmal.")
    grund = _grund(d.get("grund"))
    cur = con.execute("INSERT INTO tag_besonders (klasse_id, von, bis, art, grund, wer, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (klasse_id, von.isoformat(), bis.isoformat(), art, grund, konto["kuerzel"], db.jetzt()))
    db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "tag_" + art, von=von.isoformat(), bis=bis.isoformat(), grund=grund)
    return cur.lastrowid


def besonders_entfernen(con, konto, klasse_id, bid):
    klassen.pruefen(con, klasse_id, konto, "aendern")
    z = con.execute("SELECT * FROM tag_besonders WHERE id = ? AND klasse_id = ? AND aktiv = 1", (bid, klasse_id)).fetchone()
    if z is None:
        raise TageFehler("Diesen Eintrag gibt es nicht.")
    con.execute("UPDATE tag_besonders SET aktiv = 0 WHERE id = ?", (bid,))
    db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "tag_" + z["art"] + "_entfernt", von=z["von"], bis=z["bis"])


def besondere(con, klasse_id, von=None):
    sql = "SELECT * FROM tag_besonders WHERE klasse_id = ? AND aktiv = 1" + (" AND bis >= ?" if von else "") + " ORDER BY von"
    return [{"id": z["id"], "von": z["von"], "bis": z["bis"], "art": z["art"], "grund": z["grund"], "wer": z["wer"]}
            for z in con.execute(sql, (klasse_id, von) if von else (klasse_id,))]


# --- Ferien (fuer alle Klassen; von Hand oder aus dem Schulkalender) ---

def ferien_liste(con, von=None):
    sql = "SELECT * FROM ferien WHERE aktiv = 1" + (" AND bis >= ?" if von else "") + " ORDER BY von"
    return [{"id": z["id"], "von": z["von"], "bis": z["bis"], "name": z["name"], "quelle": z["quelle"]}
            for z in con.execute(sql, (von,) if von else ())]


def ferien_anlegen(con, konto, d):
    if konto["rolle"] != "admin":
        raise klassen.KeinZugriff("Ferien trägt der Admin ein.")
    von = datum(d.get("von"), "den ersten Tag")
    bis = datum(d.get("bis") or von.isoformat(), "den letzten Tag")
    if bis < von:
        raise TageFehler("Der letzte Tag liegt vor dem ersten.")
    name = _grund(d.get("name"))
    con.execute("INSERT INTO ferien (von, bis, name) VALUES (?, ?, ?)", (von.isoformat(), bis.isoformat(), name))
    db.ereignis(con, None, None, "lehrkraft", konto["kuerzel"], "ferien_angelegt", von=von.isoformat(), bis=bis.isoformat(), name=name)


def ferien_entfernen(con, konto, fid):
    if konto["rolle"] != "admin":
        raise klassen.KeinZugriff("Ferien trägt der Admin ein.")
    z = con.execute("SELECT * FROM ferien WHERE id = ? AND aktiv = 1 AND quelle = 'hand'", (fid,)).fetchone()
    if z is None:
        raise TageFehler("Diesen Eintrag gibt es nicht (Ferien aus dem Schulkalender ändern Sie dort).")
    con.execute("UPDATE ferien SET aktiv = 0 WHERE id = ?", (fid,))


# --- Tage berechnen ---

def _greift(r, tag):
    if tag.weekday() != r["wochentag"] or not r["gueltig_von"] <= tag.isoformat() <= r["gueltig_bis"]:
        return False
    gerade = tag.isocalendar()[1] % 2 == 0
    return r["rhythmus"] == "jede" or gerade == (r["rhythmus"] == "gerade")


def tage(con, klasse_id, von, bis):
    """Alle Tage von..bis (date, einschliesslich), an denen eine Regel der Klasse greift, mit Status:
    unterricht | ohne (findet statt, ohne Lehrkraft) | ausfall | ferien. Bei mehreren Regeln am selben Tag gilt der
    frueheste Beginn und das spaeteste Ende (ein Unterrichtstag je Datum)."""
    rs = regeln(con, klasse_id)
    if not rs or von > bis:
        return []
    v, b = von.isoformat(), bis.isoformat()
    ferien = con.execute("SELECT von, bis, name FROM ferien WHERE aktiv = 1 AND bis >= ? AND von <= ?", (v, b)).fetchall()
    sonder = con.execute("SELECT * FROM tag_besonders WHERE klasse_id = ? AND aktiv = 1 AND bis >= ? AND von <= ? ORDER BY id",
                         (klasse_id, v, b)).fetchall()
    liste = []
    tag = von
    while tag <= bis:
        passend = [r for r in rs if _greift(r, tag)]
        if passend:
            d = tag.isoformat()
            eintrag = {"datum": d, "tag": TAGE[tag.weekday()], "kw": tag.isocalendar()[1],
                       "von": min(r["von"] for r in passend), "bis": max(r["bis"] for r in passend),
                       "status": "unterricht", "grund": "", "besonders_id": None}
            f = next((f for f in ferien if f["von"] <= d <= f["bis"]), None)
            s = [x for x in sonder if x["von"] <= d <= x["bis"]]
            ausfall = next((x for x in reversed(s) if x["art"] == "ausfall"), None)
            ohne = next((x for x in reversed(s) if x["art"] == "ohne"), None)
            if f:
                eintrag.update(status="ferien", grund=f["name"])
            elif ausfall:
                eintrag.update(status="ausfall", grund=ausfall["grund"], besonders_id=ausfall["id"])
            elif ohne:
                eintrag.update(status="ohne", grund=ohne["grund"], besonders_id=ohne["id"])
            liste.append(eintrag)
        tag += TAG
    return liste


def findet_statt(t):
    return t["status"] in ("unterricht", "ohne")


def unterrichtstage(con, klasse_id, von, bis):
    """Nur die Tage, an denen das Lernbuero stattfindet (mit oder ohne Lehrkraft)."""
    return [t for t in tage(con, klasse_id, von, bis) if findet_statt(t)]


def wirksame_frist(con, klasse_id, frist):
    """Frist (ISO-Text) -> (wirksames Datum, Hinweis). Faellt der Fristtag aus oder ist er kein Unterrichtstag, gilt der
    naechste Unterrichtstag; ohne weitere Unterrichtstage bleibt die Frist stehen."""
    if not frist:
        return None, ""
    d = datum(frist)
    tag = tage(con, klasse_id, d, d)
    if tag and findet_statt(tag[0]):
        return frist, ""
    naechste = unterrichtstage(con, klasse_id, d + TAG, d + 120 * TAG)
    if not naechste:
        return frist, "kein Unterrichtstag" if not tag else "fällt aus"
    grund = ("fällt aus: " + tag[0]["grund"]) if tag else "kein Unterrichtstag"
    return naechste[0]["datum"], grund
