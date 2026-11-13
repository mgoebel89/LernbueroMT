"""Tests fuer Stufe F: Dienstkalender, Kalenderansicht, Verlauf mit Schatten und Kennzahlen, Berichte als PDF, Archiv."""
import datetime
import unittest
from unittest import mock

from app import berichte, db, kalender, kalenderansicht, klassen, lernplan, pakete, termine, verlauf
from test_stufe_d import Basis, D, HEUTE


def um(zeit):
    """Ereignisse mit dieser Uhrzeit schreiben (Verlauf ueber mehrere Tage)."""
    return mock.patch.object(db, "jetzt", return_value=zeit)


class Dienstkalender(Basis):
    def setUp(self):
        super().setUp()
        c = self.con
        with db.transaktion(c):
            c.execute("INSERT INTO kalender_abo (art, lehrkraft_id, url) VALUES ('dienst', ?, 'https://example.org/x.ics')", (self.sch["id"],))
            aid = c.execute("SELECT id FROM kalender_abo WHERE art = 'dienst'").fetchone()[0]
            c.executemany("INSERT INTO kalender_termin (abo_id, beginn, ende, ganztags, titel) VALUES (?, ?, ?, ?, ?)",
                          [(aid, "2026-11-19T10:30", "2026-11-19T10:45", 0, "Fachkonferenz"),
                           (aid, "2026-11-25", "2026-11-25", 1, "Elternsprechtag")])

    def fenster(self):
        with mock.patch.object(db, "heute", return_value=HEUTE), db.transaktion(self.con):
            return termine.zeitfenster_anlegen(self.con, self.sch, self.k, {"art": "sprech", "von": "10:15", "bis": "11:15", "dauer": 15, "puffer": 5,
                                                                            "woechentlich": True, "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})

    def test_belegt_und_kollision(self):
        belegt = kalender.dienst_belegt(self.con, self.sch["id"], D(2026, 11, 19))
        self.assertEqual(belegt, [(630, 645, "Fachkonferenz")])
        self.assertEqual(kalender.dienst_belegt(self.con, self.sch["id"], D(2026, 11, 25)), [])      # ganztaegig sperrt nichts
        self.assertEqual(kalender.kollision("10:35", "10:50", belegt), "Fachkonferenz")
        self.assertIsNone(kalender.kollision("10:15", "10:30", belegt))
        self.assertEqual(kalender.dienst_belegt(self.con, self.gob["id"], D(2026, 11, 19)), [])     # nur der eigene Kalender

    def test_plaetze_gesperrt_und_warnung(self):
        e = self.fenster()
        self.assertTrue(any("Dienstkalender: Fachkonferenz am Do 19.11." in w for w in e["warnungen"]), e["warnungen"])
        zid = e["zeitfenster"]["id"]
        frei = termine.freie_plaetze(self.con, self.lena, "feedback", HEUTE, "07:00")
        tag = next(x for x in frei if x["datum"] == "2026-11-19")
        self.assertEqual(tag["plaetze"], ["10:15", "10:55"])                                       # 10:35 faellt in die Konferenz
        with self.assertRaisesRegex(termine.TerminFehler, "vergeben"):
            termine.buchen(self.con, self.lena, zid, "2026-11-19", "10:35", "feedback", {"text": "Frage"}, HEUTE, "07:00")
        b = termine.belegung(self.con, self.sch, self.k, HEUTE, 21)
        z = next(x for x in b if x["datum"] == "2026-11-19")
        self.assertEqual([p.get("dienst") for p in z["plaetze"] if not p.get("puffer")], [None, "Fachkonferenz", None])
        b2 = termine.belegung(self.con, self.gob, self.k, HEUTE, 21)                                # Kollegen sehen keinen Titel
        self.assertEqual(next(x for x in b2 if x["datum"] == "2026-11-19")["plaetze"][2]["dienst"], "Dienstkalender")


class Kalenderansicht(Basis):
    def test_halbjahr(self):
        self.assertEqual(kalenderansicht.halbjahr(D(2026, 11, 13)), (D(2026, 8, 1), D(2027, 1, 31), "1. Halbjahr 2026/27"))
        self.assertEqual(kalenderansicht.halbjahr(D(2027, 1, 20))[2], "1. Halbjahr 2026/27")
        self.assertEqual(kalenderansicht.halbjahr(D(2027, 3, 1)), (D(2027, 2, 1), D(2027, 7, 31), "2. Halbjahr 2026/27"))

    def test_ebenen(self):
        with mock.patch.object(db, "heute", return_value=HEUTE), db.transaktion(self.con):
            termine.zeitfenster_anlegen(self.con, self.gob, self.k, {"art": "pruefung", "von": "10:15", "bis": "11:15", "dauer": 15,
                                                                    "woechentlich": True, "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})
            self.con.execute("INSERT INTO ferien (von, bis, name) VALUES ('2026-12-23', '2027-01-08', 'Weihnachtsferien')")
        a = kalenderansicht.ansicht(self.con, self.gob, D(2026, 11, 1), D(2026, 12, 31))
        nach = {}
        for e in a["eintraege"]:
            nach.setdefault(e["datum"], []).append((e["ebene"], e["text"]))
        self.assertIn(("frist", "Frist P1"), nach["2026-11-05"])
        self.assertIn(("frist", "Frist P2"), nach["2026-11-19"])
        self.assertIn(("frist", "Paket-Frist Elektropneumatik"), nach["2026-12-03"])
        self.assertIn(("unterricht", "Elektropneumatik frei"), nach["2026-11-02"])
        self.assertIn(("ferien", "Ausfall: Zwischenprüfung"), nach["2026-11-16"])
        self.assertIn(("ferien", "ohne Lehrkraft: Fortbildung"), nach["2026-11-12"])
        self.assertIn(("pruefung", "10:15 Prüfungszeit 0/4"), nach["2026-11-19"])
        self.assertNotIn("pruefung", [x[0] for x in nach["2026-11-12"]])                            # ohne Lehrkraft: keine Termine
        self.assertEqual(a["tage"]["2026-12-28"]["ferien"], "Weihnachtsferien")
        self.assertEqual(a["tage"]["2026-11-09"]["unterricht"][0]["klasse"], "BSMT 24a")
        b = kalenderansicht.ansicht(self.con, self.sch, D(2026, 11, 1), D(2026, 12, 31))             # fremde Zeitfenster nicht
        self.assertFalse([e for e in b["eintraege"] if e["ebene"] == "pruefung"])
        with self.assertRaises(kalenderansicht.KalenderansichtFehler):
            kalenderansicht.ansicht(self.con, self.gob, D(2026, 1, 1), D(2026, 12, 31))


class Verlauf(Basis):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            self.a2 = pakete.aufgabe_anlegen(self.con, self.gob, self.pid, {"art": "wahl", "wahlgruppe_id": self.ga, "titel": "Hubtisch"})
        c, s = self.con, self.lena
        with um("2026-11-02T08:00:00"), db.transaktion(c):
            for kid in (self.k1, self.k2):
                lernplan.kann_einschaetzen(c, s, kid, 2, aufgabe_id=self.p1, heute=D(2026, 11, 2))
            lernplan.planen(c, s, self.p1, hinzu=["2026-11-05"], heute=D(2026, 11, 2))
            lernplan.planen(c, s, self.p2, hinzu=["2026-11-09", "2026-11-12"], heute=D(2026, 11, 2))
            lernplan.planen(c, s, self.p2, weg=["2026-11-12"], heute=D(2026, 11, 2))              # am Tag des ersten Plans: kein Verschieben
            lernplan.waehlen(c, s, self.a1, heute=D(2026, 11, 2))
        with um("2026-11-05T09:00:00"), db.transaktion(c):
            lernplan.planen(c, s, self.p2, hinzu=["2026-11-19"], weg=["2026-11-09"], heute=HEUTE)   # verschoben
            lernplan.markieren(c, s, self.p1, "2026-11-05", "g", HEUTE)
            lernplan.waehlen(c, s, self.a2, heute=HEUTE)                                            # Wahlwechsel A1 -> A2

    def test_plan_von_damals(self):
        ev = verlauf._ereignisse(self.con, self.lena["id"])
        self.assertEqual(verlauf.plan_am(ev, "2026-11-02"), {self.p1: ["2026-11-05"], self.p2: ["2026-11-09"]})
        self.assertEqual(verlauf.plan_am(ev, "2026-11-05"), {self.p1: ["2026-11-05"], self.p2: ["2026-11-19"]})
        self.assertEqual(verlauf.plan_am(ev, "2026-11-01"), {})

    def test_verlauf_kennzahlen_marken(self):
        v = verlauf.verlauf(self.con, self.lena, heute=D(2026, 11, 10))
        self.assertEqual([o["datum"] for o in v["optionen"]], ["2026-11-02", "2026-11-05", "2026-11-09"])
        self.assertTrue(v["optionen"][0]["beginn"])
        self.assertEqual(v["stand"], "2026-11-02")
        self.assertEqual(v["schatten"][self.p2], ["2026-11-09"])
        k = v["kennzahlen"]
        self.assertEqual(k["plan"], {"tage": 1, "eingehalten": 1, "teilweise": 0, "heute_offen": False})   # nur Do 05.11. hatte Plan
        self.assertEqual((k["verschiebungen"]["eigen"], k["verschiebungen"]["ausfall"], k["verschiebungen"]["text"]), (1, 0, "P2 einmal"))
        self.assertEqual(k["wahlwechsel"], {"anzahl": 1, "text": "A1 → A2"})
        self.assertIn(["versch", "1× verschoben"], v["marken"][self.p2])
        self.assertIn(["weg", "abgewählt"], v["marken"][self.a1])
        marken = [(e["art"], e["marke"]) for e in v["entscheidungen"] if e["marke"]]
        self.assertIn(("plan", ["versch", "verschoben"]), marken)
        self.assertIn(("gewaehlt", ["versch", "Wechsel"]), marken)
        self.assertIn(("abgewaehlt", ["weg", "abgewählt"]), marken)
        self.assertEqual(v["entscheidungen"][0]["zeit"][:10], "2026-11-05")                          # neueste zuerst
        self.assertEqual(verlauf.verlauf(self.con, self.lena, "2026-11-05", D(2026, 11, 10))["schatten"][self.p2], ["2026-11-19"])
        self.assertEqual(verlauf.verlauf(self.con, self.lena, "2026-10-01", D(2026, 11, 10))["stand"], "2026-11-02")   # unbekannt -> Beginn

    def test_ausfall_verschiebung_zaehlt_getrennt(self):
        with um("2026-11-10T08:00:00"), db.transaktion(self.con):
            self.con.execute(   # geplant, bevor der Ausfall eingetragen wurde
"INSERT INTO plan (schueler_id, aufgabe_id, datum) VALUES (?, ?, '2026-11-16')", (self.lena["id"], self.p2))
            lernplan.ausfall_verschieben(self.con, self.lena, D(2026, 11, 10))
        k = verlauf.verlauf(self.con, self.lena, heute=D(2026, 11, 10))["kennzahlen"]["verschiebungen"]
        self.assertEqual((k["eigen"], k["ausfall"]), (1, 1))


class Berichte(Verlauf):
    def test_pdfs(self):
        with mock.patch.object(db, "heute", return_value=D(2026, 11, 10)):
            b = berichte.lernstand(self.con, self.lena["id"])
            k = berichte.klassenuebersicht(self.con, self.k)
            alle = berichte.lernstand_klasse(self.con, self.k)
        for inhalt in (b, k, alle):
            self.assertTrue(inhalt.startswith(b"%PDF-1.4") and inhalt.rstrip().endswith(b"%%EOF"))
        self.assertIn("Lena Krämer".encode("cp1252"), b)
        self.assertIn(b"Lernstand-Bericht", b)
        self.assertIn(b"Schaltzeichen", b)
        self.assertIn(b"Kann-Liste", b)
        self.assertIn(b"/MediaBox [0 0 841.89 595.28]", k)                                            # quer
        self.assertIn("Jonas Weber".encode("cp1252"), alle)
        self.assertGreaterEqual(alle.count(b"/Type /Page "), 2)                                        # je Schueler eine neue Seite


class Archiv(Basis):
    def test_archivieren_nur_lesbar_reaktivieren(self):
        with mock.patch.object(db, "heute", return_value=HEUTE), db.transaktion(self.con):
            zid = termine.zeitfenster_anlegen(self.con, self.sch, self.k, {"art": "sprech", "von": "10:15", "bis": "11:15", "dauer": 15,
                                                                           "woechentlich": True, "gueltig_von": "2026-11-05", "gueltig_bis": "2027-06-17"})["zeitfenster"]["id"]
        with db.transaktion(self.con):
            self.con.execute("INSERT INTO termin (zeitfenster_id, schueler_id, datum, beginn, ende, art, gebucht) VALUES (?, ?, '2099-01-01', '10:15', '10:30', 'feedback', 'x')",
                             (zid, self.lena["id"]))
            klassen.aendern(self.con, self.sch, self.k, {"archiviert": True})
        self.assertIsNone(klassen.per_code(self.con, self.lena["code"]))
        self.assertEqual(klassen.zugriff(self.con, self.k, self.sch), "einsicht")
        self.assertEqual(klassen.zugriff(self.con, self.k, self.sch, roh=True), "team")
        with self.assertRaisesRegex(klassen.KeinZugriff, "archiviert"):
            klassen.pruefen(self.con, self.k, self.sch, "aendern")
        with self.assertRaises(klassen.KeinZugriff):
            pakete.aendern(self.con, self.sch, self.pid, {"titel": "Neu"})
        with self.assertRaisesRegex(klassen.KlassenFehler, "wieder aktivieren"):
            klassen.aendern(self.con, self.sch, self.k, {"name": "BSMT 24b"})
        self.assertIsNotNone(self.con.execute("SELECT abgesagt FROM termin WHERE datum = '2099-01-01'").fetchone()[0])
        daten = klassen.holen(self.con, self.sch, self.k)
        self.assertTrue(daten["archiviert"] and daten["darf_archiv"])
        self.assertNotIn("code", daten["schueler"][0])
        jahr = int(daten["archiviert_am"][:4])
        self.assertEqual(daten["loeschen_ab"], "%d%s" % (jahr + 1, daten["archiviert_am"][4:10]))
        self.assertFalse(daten["loeschen_faellig"])
        with self.assertRaises(klassen.KeinZugriff):
            klassen.aendern(self.con, self.kl, self.k, {"archiviert": False})                            # Einsicht darf nicht
        with db.transaktion(self.con):
            klassen.aendern(self.con, self.sch, self.k, {"archiviert": False, "name": "egal"})
        self.assertEqual(klassen.zugriff(self.con, self.k, self.sch), "team")
        self.assertIsNotNone(klassen.per_code(self.con, self.lena["code"]))
        self.assertIsNone(klassen.holen(self.con, self.sch, self.k)["archiviert_am"])

    def test_loeschfrist_und_loeschen(self):
        self.assertEqual(klassen.loeschen_ab(self.con, "2026-08-31T10:00:00"), "2027-08-31")
        db.einstellung_setzen(self.con, "loeschfrist_monate", "6")
        self.assertEqual(klassen.loeschen_ab(self.con, "2026-08-31T10:00:00"), "2027-02-28")
        with self.assertRaisesRegex(klassen.KlassenFehler, "nur für archivierte"):
            klassen.loeschen(self.con, self.sch, self.k, "BSMT 24a")
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-09"], heute=HEUTE)
            klassen.aendern(self.con, self.sch, self.k, {"archiviert": True})
        with self.assertRaisesRegex(klassen.KlassenFehler, "Namen der Klasse"):
            klassen.loeschen(self.con, self.sch, self.k, "falsch")
        with self.assertRaises(klassen.KeinZugriff):
            klassen.loeschen(self.con, self.kl, self.k, "BSMT 24a")
        with db.transaktion(self.con):
            self.assertEqual(klassen.loeschen(self.con, self.sch, self.k, " bsmt 24a "), 2)
        for tabelle in ("klasse", "schueler", "plan", "paket", "aufgabe", "kann_aussage", "unterrichtsregel"):
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM %s" % tabelle).fetchone()[0], 0, tabelle)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM ereignis WHERE klasse_id IS NOT NULL OR schueler_id IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT art FROM ereignis ORDER BY id DESC LIMIT 1").fetchone()[0], "klasse_geloescht")
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_admin_ohne_zuordnung_darf_archiv(self):
        with db.transaktion(self.con):
            klassen.lehrkraft_setzen(self.con, self.gob, self.k, self.gob["id"], None)
            klassen.aendern(self.con, self.gob, self.k, {"archiviert": True})
        self.assertTrue(klassen.liste(self.con, self.gob, archiv=True)[0]["darf_archiv"])
        self.assertFalse(klassen.liste(self.con, self.kl, archiv=True)[0]["darf_archiv"])


class KannPflicht(Basis):
    """Kann-Liste "vorher" vor jedem Anfangen, "nachher" nur fuer fertig gemeldete Aufgaben, Hinweis in der Klassenmatrix."""

    def test_markieren_und_fertig_brauchen_vorher(self):
        with self.assertRaisesRegex(lernplan.PlanFehler, "„vorher“ für P1"):
            lernplan.markieren(self.con, self.lena, self.p1, "2026-11-05", "g", HEUTE)          # ungeplant markieren
        self.vorher(self.lena, self.p1)
        with db.transaktion(self.con):
            lernplan.markieren(self.con, self.lena, self.p1, "2026-11-05", "g", HEUTE)
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-05", "y", HEUTE)          # P2 ohne Kann-Liste: frei
        with db.transaktion(self.con):
            lernplan.markieren(self.con, self.lena, self.p1, "2026-11-05", None, HEUTE)         # Farbe entfernen geht immer

    def test_spaeter_verknuepfte_aussage(self):
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-09"], heute=HEUTE)
            k3 = pakete.kann_anlegen(self.con, self.gob, self.pid, {"text": "Kolbenkraft berechnen", "aufgaben": [self.p2]})
        with self.assertRaisesRegex(lernplan.PlanFehler, "„vorher“ für P2"):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-12"], heute=HEUTE)
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, weg=["2026-11-09"], heute=HEUTE)          # wegnehmen geht
        lena = next(z for z in lernplan.matrix(self.con, self.k, heute=HEUTE)["zeilen"] if z["name"] == "Lena Krämer")
        self.assertFalse([h for h in lena["hinweise"] if "Kann" in h])                       # nichts mehr geplant: kein Hinweis
        with db.transaktion(self.con):
            self.con.execute("INSERT INTO plan (schueler_id, aufgabe_id, datum) VALUES (?, ?, '2026-11-09')", (self.lena["id"], self.p2))
        lena = next(z for z in lernplan.matrix(self.con, self.k, heute=HEUTE)["zeilen"] if z["name"] == "Lena Krämer")
        self.assertIn("Kann-Liste vorher fehlt (P2)", lena["hinweise"])
        with db.transaktion(self.con):
            lernplan.kann_einschaetzen(self.con, self.lena, k3, 1, aufgabe_id=self.p2, heute=HEUTE)
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-12"], heute=HEUTE)

    def test_nachher_nur_nach_fertigmelden_und_als_nachher_gespeichert(self):
        with self.assertRaisesRegex(lernplan.PlanFehler, "fertig gemeldet"):
            lernplan.kann_einschaetzen(self.con, self.jonas, self.k1, 3, art="nachher", aufgabe_id=self.p1, heute=HEUTE)
        with db.transaktion(self.con):   # wie beim Teampartner: Meldung ohne eigene Einschaetzung "nachher"
            self.con.execute("INSERT INTO meldung (schueler_id, aufgabe_id, zeit) VALUES (?, ?, ?)", (self.jonas["id"], self.p1, db.jetzt()))
        jonas = next(z for z in lernplan.matrix(self.con, self.k, heute=HEUTE)["zeilen"] if z["name"] == "Jonas Weber")
        self.assertIn("Kann-Liste nachher fehlt (P1)", jonas["hinweise"])
        with db.transaktion(self.con):
            lernplan.kann_einschaetzen(self.con, self.jonas, self.k1, 3, art="nachher", aufgabe_id=self.p1, heute=HEUTE)
            lernplan.kann_einschaetzen(self.con, self.jonas, self.k2, 4, art="nachher", aufgabe_id=self.p1, heute=HEUTE)
        arten = {z[0] for z in self.con.execute("SELECT art FROM kann_einschaetzung WHERE schueler_id = ?", (self.jonas["id"],))}
        self.assertEqual(arten, {"nachher"})
        self.assertEqual(self.zeile(self.p1, self.jonas)["kann_stand"], "fertig")


if __name__ == "__main__":
    unittest.main()
