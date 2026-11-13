"""Entscheidungsverlauf eines Schuelers (Stufe F), fuer die Schuelerseite der Lehrkraft und den Lernstand-Bericht.

Alles kommt aus dem Ereignisprotokoll (nur anhaengen):
  - Plan von damals: die Plan-Ereignisse (plan_neu, plan, abgewaehlt) bis zum Ende eines frueheren Tages nachgespielt.
    Im Raster erscheint er als grauer Schatten ueber dem Plan von jetzt.
  - Kennzahlen: Plan eingehalten (vergangene Unterrichtstage mit Plan, an denen jede geplante Aufgabe als bearbeitet
    markiert ist; Aufgaben, die vorher fertig gemeldet waren, zaehlen nicht mehr), Verschiebungen (an einem Tag
    geplante Tage einer Aufgabe weggenommen; nicht am Tag des ersten Plans; "durch Ausfall" getrennt gezaehlt),
    Wahlwechsel je Wahlgruppe, Empfehlungen (eingeplant, erledigt, offen), Hilfe gerufen.
  - Entscheidungen: alle Eintraege mit Zeitstempel, Kategorie (fuer den Filter) und Marke (neu, verschoben, durch
    Ausfall, abgewaehlt, Empfehlung).
"""
import datetime
import json

from . import db, unterrichtstage as ut

TAG = datetime.timedelta(days=1)
PLAN_ARTEN = ("plan_neu", "plan", "abgewaehlt")
KATEGORIEN = {
    "plan": ("plan_neu", "plan"),
    "wahl": ("gewaehlt", "abgewaehlt"),
    "stand": ("tagesabschluss", "markiert", "zeitplan_rot"),
    "kann": ("kann_vorher", "kann_nachher"),
    "melden": ("fertig", "fertig_zurueck", "fertig_team", "fertig_bestaetigt", "fertig_noch_nicht", "rueckmeldung", "gespraech", "empfehlung", "empfehlung_entfernt", "empfehlung_erledigt",
               "empfehlung_offen"),
    "nachweis": ("bereit", "bereit_zurueck", "freigeschaltet", "freischaltung_zurueck", "nachweis_ergebnis"),
    "termin": ("termin_gebucht", "termin_abgesagt", "teamtermin", "hilfe", "hilfe_zurueck", "hilfe_erledigt"),
}
KATEGORIE_TEXT = {"plan": "Planung", "wahl": "Wahl", "stand": "Stand und Farben", "kann": "Kann-Liste", "melden": "Melden und Rückmeldung",
                  "nachweis": "Gelingensnachweise", "termin": "Termine und Hilfe", "team": "Lernteams", "sonst": "Sonstiges"}


def kategorie(art):
    if art.startswith("team_"):
        return "team"
    return next((k for k, arten in KATEGORIEN.items() if art in arten), "sonst")


def _ereignisse(con, schueler_id):
    return [{"id": z["id"], "zeit": z["zeit"], "art": z["art"], "wer_art": z["wer_art"], "wer": z["wer"], "daten": json.loads(z["daten"] or "{}")}
            for z in con.execute("SELECT * FROM ereignis WHERE schueler_id = ? ORDER BY id", (schueler_id,))]


def plan_am(ereignisse, stichtag):
    """Plan am Ende des Tages stichtag (ISO-Datum): {aufgabe_id: [Tage]}."""
    plan = {}
    for e in ereignisse:
        if e["art"] not in PLAN_ARTEN or e["zeit"][:10] > stichtag:
            continue
        aid = e["daten"].get("aufgabe_id")
        tage = plan.setdefault(aid, set())
        if e["art"] != "abgewaehlt":
            tage.update(e["daten"].get("hinzu") or [])
        tage.difference_update(e["daten"].get("weg") or [])
    return {aid: sorted(t) for aid, t in plan.items() if t}


def _verschiebungen(ereignisse):
    """{(aufgabe_id, Tag der Aenderung): 'eigen' | 'ausfall'} und die Ereignis-ids, die eine Verschiebung beginnen."""
    erster_plan = {}
    for e in ereignisse:
        if e["art"] == "plan_neu":
            erster_plan.setdefault(e["daten"].get("aufgabe_id"), e["zeit"][:10])
    gruppen, start = {}, {}
    for e in ereignisse:
        d = e["daten"]
        if e["art"] != "plan" or not d.get("weg") or d.get("grund") == "team":
            continue
        aid, tag = d.get("aufgabe_id"), e["zeit"][:10]
        art = "ausfall" if d.get("grund") == "ausfall" else "eigen"
        if art == "eigen" and erster_plan.get(aid) == tag:
            continue   # am Tag des ersten Plans wird noch geplant, nicht verschoben
        if (aid, tag, art) not in gruppen:
            gruppen[(aid, tag, art)] = e
            start[e["id"]] = art
    return gruppen, start


def kennzahlen_und_marken(con, schueler, ereignisse, heute):
    sid, kid = schueler["id"], schueler["klasse_id"]
    aufgaben = {z["id"]: z for z in con.execute(
        "SELECT a.id, a.kuerzel, a.art, a.wahlgruppe_id FROM aufgabe a JOIN paket p ON p.id = a.paket_id WHERE p.klasse_id = ?", (kid,))}
    # Plan eingehalten: vergangene Unterrichtstage mit Plan
    plan, ist = {}, {}
    for z in con.execute("SELECT aufgabe_id, datum FROM plan WHERE schueler_id = ?", (sid,)):
        plan.setdefault(z[1], set()).add(z[0])
    for z in con.execute("SELECT aufgabe_id, datum FROM ist WHERE schueler_id = ?", (sid,)):
        ist.setdefault(z[1], set()).add(z[0])
    fertig_ab = {}
    for z in con.execute("SELECT aufgabe_id, zeit FROM meldung WHERE schueler_id = ? AND status IN ('offen', 'angenommen') ORDER BY id", (sid,)):
        fertig_ab.setdefault(z[0], z[1][:10])
    eingehalten = teilweise = gesamt = 0
    heute_offen = False
    if plan:
        tage = {t["datum"]: t for t in ut.unterrichtstage(con, kid, ut.datum(min(plan)), heute)}
        for d in sorted(plan):
            if d not in tage or d > heute.isoformat():
                continue
            soll = {a for a in plan[d] if not (a in fertig_ab and fertig_ab[a] < d)}
            if not soll:
                continue
            erledigt = soll & ist.get(d, set())
            if d == heute.isoformat():
                heute_offen = erledigt != soll
                continue
            gesamt += 1
            if erledigt == soll:
                eingehalten += 1
            elif erledigt:
                teilweise += 1
    # Verschiebungen
    gruppen, start = _verschiebungen(ereignisse)
    je_aufgabe = {}
    for (aid, _, art) in gruppen:
        je_aufgabe.setdefault(aid, {"eigen": 0, "ausfall": 0})[art] += 1
    eigen = sum(v["eigen"] for v in je_aufgabe.values())
    ausfall = sum(v["ausfall"] for v in je_aufgabe.values())
    verschiebungen_text = ", ".join("%s %s" % (aufgaben[a]["kuerzel"] if a in aufgaben else "?", "einmal" if v["eigen"] == 1 else "%d-mal" % v["eigen"])
                                    for a, v in sorted(je_aufgabe.items(), key=lambda x: -x[1]["eigen"]) if v["eigen"])
    # Wahlwechsel je Wahlgruppe
    zuletzt, wechsel, wechsel_ids = {}, [], set()
    for e in ereignisse:
        if e["art"] != "gewaehlt":
            continue
        a = aufgaben.get(e["daten"].get("aufgabe_id"))
        if a is None:
            continue
        vorher = zuletzt.get(a["wahlgruppe_id"])
        if vorher and vorher != a["kuerzel"]:
            wechsel.append("%s → %s" % (vorher, a["kuerzel"]))
            wechsel_ids.add(e["id"])
        zuletzt[a["wahlgruppe_id"]] = a["kuerzel"]
    # Empfehlungen
    emp = con.execute("SELECT aufgabe_id, freigegeben, erledigt FROM empfehlung WHERE schueler_id = ? AND freigegeben IS NOT NULL AND entfernt IS NULL",
                      (sid,)).fetchall()
    geplant_ab = {}
    for d, ids in plan.items():
        for a in ids:
            geplant_ab.setdefault(a, set()).add(d)
    emp_eingeplant = sum(1 for e in emp if not e["erledigt"] and any(d >= e["freigegeben"][:10] for d in geplant_ab.get(e["aufgabe_id"], ())))
    emp_erledigt = sum(1 for e in emp if e["erledigt"])
    hilfe = con.execute("SELECT COUNT(*) FROM hilfe WHERE schueler_id = ?", (sid,)).fetchone()[0]
    kennzahlen = {
        "plan": {"tage": gesamt, "eingehalten": eingehalten, "teilweise": teilweise, "heute_offen": heute_offen},
        "verschiebungen": {"eigen": eigen, "ausfall": ausfall, "text": verschiebungen_text},
        "wahlwechsel": {"anzahl": len(wechsel), "text": ", ".join(wechsel)},
        "empfehlungen": {"anzahl": len(emp), "eingeplant": emp_eingeplant, "erledigt": emp_erledigt,
                         "offen": len(emp) - emp_eingeplant - emp_erledigt},
        "hilfe": hilfe,
    }
    # Marken je Aufgabe fuer das Raster
    marken = {}
    for aid, v in je_aufgabe.items():
        if v["eigen"]:
            marken.setdefault(aid, []).append(["versch", "%d× verschoben" % v["eigen"]])
        if v["ausfall"]:
            marken.setdefault(aid, []).append(["aus", "%d× Ausfall" % v["ausfall"]])
    gewaehlt = {z[0] for z in con.execute("SELECT aufgabe_id FROM wahl WHERE schueler_id = ?", (sid,))}
    for e in ereignisse:
        aid = e["daten"].get("aufgabe_id")
        if e["art"] == "abgewaehlt" and aid not in gewaehlt and not any(m[0] == "weg" for m in marken.get(aid, [])):
            marken.setdefault(aid, []).append(["weg", "abgewählt"])
    for e in emp:
        if not any(m[0] == "emp" for m in marken.get(e["aufgabe_id"], [])):
            marken.setdefault(e["aufgabe_id"], []).append(["emp", "Empfehlung"])
    return kennzahlen, marken, start, wechsel_ids, {e["aufgabe_id"] for e in emp}


def _marke(e, start, wechsel_ids, empfohlen, versch_zaehler):
    d = e["daten"]
    if e["art"] == "plan":
        if d.get("grund") == "ausfall":
            return ["aus", "durch Ausfall"]
        if d.get("grund") == "team":
            return ["team", "Team"]
        if start.get(e["id"]) == "eigen":
            n = versch_zaehler[d.get("aufgabe_id")] = versch_zaehler.get(d.get("aufgabe_id"), 0) + 1
            return ["versch", "verschoben" if n == 1 else "%d. Mal" % n]
        return None
    if e["art"] == "plan_neu":
        return ["emp", "Empfehlung"] if d.get("aufgabe_id") in empfohlen else ["neu", "neu"]
    if e["art"] == "gewaehlt":
        return ["versch", "Wechsel"] if e["id"] in wechsel_ids else ["neu", "neu"]
    if e["art"] == "abgewaehlt":
        return ["weg", "abgewählt"]
    if e["art"] in ("empfehlung", "rueckmeldung") and (d.get("empfehlungen") or e["art"] == "empfehlung"):
        return ["emp", "Empfehlung"]
    return None


def stand_optionen(con, schueler, ereignisse, heute):
    """Fruehere Tage zum Vergleichen: der Tag des ersten Plans ("Beginn") und alle Unterrichtstage danach bis gestern."""
    erster = next((e["zeit"][:10] for e in ereignisse if e["art"] in PLAN_ARTEN), None)
    if erster is None or erster >= heute.isoformat():
        return []
    aus = [{"datum": erster, "beginn": True}]
    for t in ut.unterrichtstage(con, schueler["klasse_id"], ut.datum(erster) + TAG, heute - TAG):
        aus.append({"datum": t["datum"], "beginn": False})
    return aus


def verlauf(con, schueler, stand=None, heute=None):
    heute = heute or db.heute()
    ereignisse = _ereignisse(con, schueler["id"])
    optionen = stand_optionen(con, schueler, ereignisse, heute)
    if stand and not any(o["datum"] == stand for o in optionen):
        stand = None
    stand = stand or (optionen[0]["datum"] if optionen else None)
    kennzahlen, marken, start, wechsel_ids, empfohlen = kennzahlen_und_marken(con, schueler, ereignisse, heute)
    zaehler = {}
    liste = []
    for e in ereignisse:
        liste.append(dict(e, kategorie=kategorie(e["art"]), marke=_marke(e, start, wechsel_ids, empfohlen, zaehler)))
    liste.reverse()
    return {"optionen": optionen, "stand": stand, "schatten": plan_am(ereignisse, stand) if stand else {},
            "kennzahlen": kennzahlen, "marken": marken, "entscheidungen": liste, "kategorien": KATEGORIE_TEXT}
