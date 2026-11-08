"""Nicht im Zeitplan: Markiert ein Schueler eine Aufgabe an einem Tag rot (im Raster oder im Tagesabschluss), gibt er an,
warum er nicht im Zeitplan ist und welche Hilfe er braucht (Auswahl und/oder eigener Text, beides Pflicht).

Folgen: "Erklaerung jetzt" stellt ihn in die Hilfe-Reihe (nur im Lernbuero mit Lehrkraft), "Feedbackgespraech" oeffnet
danach auf der Schuelerseite die Terminbuchung. Die Lehrkraefte sehen die Angaben in der "Jetzt"-Spalte, bis eine
Lehrkraft "gesehen" tippt, dazu als Hinweis in der Matrix und im Verlauf der Schuelerseite.
Wird die Farbe spaeter geaendert oder entfernt, gilt der Eintrag als aufgehoben (bleibt im Verlauf).
"""
import json
import re

from . import db, klassen

GRUENDE = {"schwer": "schwerer als gedacht", "verstehe": "ich verstehe etwas nicht", "gefehlt": "ich habe gefehlt",
           "verplant": "verplant, zu wenig geschafft", "technik": "Problem mit Material, Technik oder Moodle", "team": "Problem im Team"}
HILFEN = {"jetzt": "Erklärung jetzt", "feedback": "Feedbackgespräch", "frist": "neue Frist", "material": "Material oder Unterlage",
          "keine": "keine Hilfe, ich plane neu"}


class ZeitplanFehler(Exception):
    pass


def pruefen(problem):
    """{gruende, grund_text, hilfe, hilfe_text} -> bereinigt; je Frage mindestens eine Auswahl oder ein Text."""
    if not isinstance(problem, dict):
        raise ZeitplanFehler("Bitte sag kurz, warum du nicht im Zeitplan bist und welche Hilfe du brauchst.")
    gruende = [g for g in (problem.get("gruende") or []) if g in GRUENDE]
    hilfe = [h for h in (problem.get("hilfe") or []) if h in HILFEN]
    grund_text = re.sub(r"\s+", " ", str(problem.get("grund_text") or "")).strip()[:400]
    hilfe_text = re.sub(r"\s+", " ", str(problem.get("hilfe_text") or "")).strip()[:400]
    if not gruende and not grund_text:
        raise ZeitplanFehler("Bitte sag kurz, warum du nicht im Zeitplan bist.")
    if not hilfe and not hilfe_text:
        raise ZeitplanFehler("Bitte wähle, welche Hilfe du brauchst (oder „keine Hilfe, ich plane neu“).")
    return {"gruende": sorted(set(gruende), key=list(GRUENDE).index), "grund_text": grund_text,
            "hilfe": sorted(set(hilfe), key=list(HILFEN).index), "hilfe_text": hilfe_text}


def text(p):
    """Kurzfassung fuer Anzeigen: 'Grund: … · Hilfe: …'."""
    gruende = [GRUENDE[g] for g in p["gruende"]] + ([p["grund_text"]] if p["grund_text"] else [])
    hilfe = [HILFEN[h] for h in p["hilfe"]] + ([p["hilfe_text"]] if p["hilfe_text"] else [])
    return "Grund: %s · Hilfe: %s" % (", ".join(gruende), ", ".join(hilfe))


def _daten(z):
    p = {"gruende": json.loads(z["gruende"]), "grund_text": z["grund_text"], "hilfe": json.loads(z["hilfe"]), "hilfe_text": z["hilfe_text"]}
    return dict(p, id=z["id"], schueler_id=z["schueler_id"], aufgabe_id=z["aufgabe_id"], datum=z["datum"], zeit=z["zeit"],
                aufgehoben=z["aufgehoben"], gesehen=z["gesehen"], text=text(p))


def speichern(con, schueler, aufgabe_id, datum, problem):
    p = pruefen(problem)
    con.execute("INSERT INTO zeitplan_problem (schueler_id, klasse_id, aufgabe_id, datum, gruende, grund_text, hilfe, hilfe_text, zeit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (schueler_id, aufgabe_id, datum) DO UPDATE SET gruende = excluded.gruende, "
                "grund_text = excluded.grund_text, hilfe = excluded.hilfe, hilfe_text = excluded.hilfe_text, zeit = excluded.zeit, "
                "aufgehoben = NULL, gesehen = NULL, gesehen_von = NULL",
                (schueler["id"], schueler["klasse_id"], aufgabe_id, datum, json.dumps(p["gruende"]), p["grund_text"], json.dumps(p["hilfe"]),
                 p["hilfe_text"], db.jetzt()))
    return p


def aufheben(con, schueler_id, aufgabe_id, datum):
    con.execute("UPDATE zeitplan_problem SET aufgehoben = ? WHERE schueler_id = ? AND aufgabe_id = ? AND datum = ? AND aufgehoben IS NULL",
                (db.jetzt(), schueler_id, aufgabe_id, datum))


def fuer_schueler(con, schueler_id):
    """{aufgabe_id: {datum: problem}} der nicht aufgehobenen Eintraege (Tooltip am roten Balken)."""
    aus = {}
    for z in con.execute("SELECT * FROM zeitplan_problem WHERE schueler_id = ? AND aufgehoben IS NULL", (schueler_id,)):
        aus.setdefault(z["aufgabe_id"], {})[z["datum"]] = _daten(z)
    return aus


def verlauf(con, konto, schueler_id):
    s = con.execute("SELECT klasse_id FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if s is None:
        raise ZeitplanFehler("Diesen Schüler gibt es nicht.")
    klassen.pruefen(con, s[0], konto, "lesen")
    aus = []
    for z in con.execute("SELECT p.*, a.kuerzel, a.titel FROM zeitplan_problem p JOIN aufgabe a ON a.id = p.aufgabe_id "
                         "WHERE p.schueler_id = ? ORDER BY p.datum DESC, p.id DESC", (schueler_id,)):
        aus.append(dict(_daten(z), kuerzel=z["kuerzel"], titel=z["titel"]))
    return aus


def liste_lk(con, konto):
    """Offene (nicht gesehene, nicht aufgehobene) Eintraege aller Klassen der Lehrkraft, neueste zuerst."""
    aus = []
    for z in con.execute("SELECT p.*, s.vorname, s.nachname, k.name AS klasse, kl.rolle, a.kuerzel, a.titel FROM zeitplan_problem p "
                         "JOIN schueler s ON s.id = p.schueler_id JOIN klasse k ON k.id = p.klasse_id "
                         "JOIN klasse_lehrkraft kl ON kl.klasse_id = p.klasse_id AND kl.lehrkraft_id = ? JOIN aufgabe a ON a.id = p.aufgabe_id "
                         "WHERE p.gesehen IS NULL AND p.aufgehoben IS NULL AND s.aktiv = 1 AND k.archiviert = 0 ORDER BY p.zeit DESC",
                         (konto["id"],)):
        aus.append(dict(_daten(z), name="%s %s" % (z["vorname"], z["nachname"]), klasse_id=z["klasse_id"], klasse=z["klasse"],
                        kuerzel=z["kuerzel"], titel=z["titel"], darf=z["rolle"] == "team"))
    return aus


def gesehen(con, konto, problem_id):
    z = con.execute("SELECT * FROM zeitplan_problem WHERE id = ?", (problem_id,)).fetchone()
    if z is None:
        raise ZeitplanFehler("Diesen Eintrag gibt es nicht.")
    klassen.pruefen(con, z["klasse_id"], konto, "aendern")
    con.execute("UPDATE zeitplan_problem SET gesehen = ?, gesehen_von = ? WHERE id = ?", (db.jetzt(), konto["id"], problem_id))


def offen_je_schueler(con, klasse_id):
    """{schueler_id: ["P2 nicht im Zeitplan", …]} der offenen Eintraege (Hinweis in der Matrix)."""
    aus = {}
    for z in con.execute("SELECT p.schueler_id, a.kuerzel FROM zeitplan_problem p JOIN aufgabe a ON a.id = p.aufgabe_id "
                         "WHERE p.klasse_id = ? AND p.aufgehoben IS NULL AND p.gesehen IS NULL ORDER BY p.datum DESC", (klasse_id,)):
        eintrag = "%s nicht im Zeitplan" % z["kuerzel"]
        if eintrag not in aus.setdefault(z["schueler_id"], []):
            aus[z["schueler_id"]].append(eintrag)
    return aus
