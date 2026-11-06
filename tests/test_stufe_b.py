"""Tests fuer Stufe B: Unterrichtstage (Regeln, Ferien, Ausfall, ohne Lehrkraft, wirksame Fristen), Schulkalender-Abo,
Lernpakete (Aufgaben, Wahlgruppen, Zusatz, Kann-Liste, Gelingensnachweis, Reihenfolge, Kopieren, Vorlagen)."""
import datetime
import shutil
import tempfile
import unittest

from app import db, kalender, klassen, konten, pakete, unterrichtstage as ut

D = datetime.date


class Grund(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        with db.transaktion(self.con):
            self.gob = konten.anlegen(self.con, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.sch = konten.anlegen(self.con, "sch", "Anna Schmidt", "lehrkraft", "geheim123", vorlaeufig=False)
            self.k = klassen.anlegen(self.con, self.gob, "BSMT 24a", "2026/27")["id"]
            self.k2 = klassen.anlegen(self.con, self.gob, "BSMT 24b", "2026/27")["id"]
            klassen.lehrkraft_setzen(self.con, self.gob, self.k, self.sch["id"], "einsicht")
            # Montag jede Woche, Donnerstag nur ungerade KW
            ut.regel_anlegen(self.con, self.gob, self.k, {"wochentag": 0, "von": "07:45", "bis": "13:00",
                                                           "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
            ut.regel_anlegen(self.con, self.gob, self.k, {"wochentag": 3, "rhythmus": "ungerade", "von": "7:45", "bis": "11:15",
                                                           "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)


class Unterrichtstage(Grund):
    def test_regeln_rhythmus(self):
        tage = ut.tage(self.con, self.k, D(2026, 11, 2), D(2026, 11, 15))
        # KW 45 (ungerade): Mo 02.11. und Do 05.11.; KW 46 (gerade): nur Mo 09.11.
        self.assertEqual([t["datum"] for t in tage], ["2026-11-02", "2026-11-05", "2026-11-09"])
        self.assertEqual(tage[1]["von"], "07:45")

    def test_ferien_ausfall_ohne(self):
        with db.transaktion(self.con):
            ut.ferien_anlegen(self.con, self.gob, {"von": "2026-11-09", "bis": "2026-11-09", "name": "Beweglicher Ferientag"})
            ut.besonders_anlegen(self.con, self.gob, self.k, {"art": "ausfall", "von": "2026-11-02", "grund": "Zwischenprüfung"})
            ut.besonders_anlegen(self.con, self.gob, self.k, {"art": "ohne", "von": "2026-11-05", "grund": "Fortbildung"})
        status = {t["datum"]: t["status"] for t in ut.tage(self.con, self.k, D(2026, 11, 2), D(2026, 11, 15))}
        self.assertEqual(status, {"2026-11-02": "ausfall", "2026-11-05": "ohne", "2026-11-09": "ferien"})
        self.assertEqual([t["datum"] for t in ut.unterrichtstage(self.con, self.k, D(2026, 11, 2), D(2026, 11, 20))],
                         ["2026-11-05", "2026-11-16", "2026-11-19"])
        # Frist am Ausfalltag wandert auf den naechsten Unterrichtstag, eine Frist am Unterrichtstag bleibt
        self.assertEqual(ut.wirksame_frist(self.con, self.k, "2026-11-02"), ("2026-11-05", "fällt aus: Zwischenprüfung"))
        self.assertEqual(ut.wirksame_frist(self.con, self.k, "2026-11-05")[0], "2026-11-05")
        self.assertEqual(ut.wirksame_frist(self.con, self.k, "2026-11-11")[0], "2026-11-16")   # Mittwoch

    def test_einsicht_darf_nicht_eintragen(self):
        with self.assertRaises(klassen.KeinZugriff):
            ut.besonders_anlegen(self.con, self.sch, self.k, {"art": "ausfall", "von": "2026-11-02", "grund": "Krank"})
        with self.assertRaises(klassen.KeinZugriff):
            ut.ferien_anlegen(self.con, self.sch, {"von": "2026-11-02", "name": "Ferien"})

    def test_pruefungen(self):
        with self.assertRaises(ut.TageFehler):
            ut.regel_anlegen(self.con, self.gob, self.k, {"wochentag": 1, "von": "10:00", "bis": "09:00"})
        with self.assertRaises(ut.TageFehler):
            ut.besonders_anlegen(self.con, self.gob, self.k, {"art": "frei", "von": "2026-11-02", "grund": "x y"})


@unittest.skipIf(kalender.icalendar is None, "python3-icalendar / recurring-ical-events fehlen")
class Schulkalender(Grund):
    ICS = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\n"
           b"BEGIN:VEVENT\r\nUID:1\r\nDTSTART;VALUE=DATE:20261123\r\nDTEND;VALUE=DATE:20261124\r\nSUMMARY:Beweglicher Ferientag\r\nEND:VEVENT\r\n"
           b"BEGIN:VEVENT\r\nUID:2\r\nDTSTART:20261123T140000\r\nDTEND:20261123T160000\r\nSUMMARY:Gesamtkonferenz\r\nEND:VEVENT\r\n"
           b"END:VCALENDAR\r\n")

    def test_ferien_aus_abo(self):
        laden = lambda url: self.ICS
        status = kalender.abo_setzen(self.con, "schule", None, "webcal://example.org/schule.ics", laden=laden)
        self.assertIsNone(status["fehler"])
        self.assertEqual(status["adresse"], "https://example.org/…")
        self.assertEqual([(f["von"], f["name"], f["quelle"]) for f in ut.ferien_liste(self.con)],
                         [("2026-11-23", "Beweglicher Ferientag", "abo")])
        self.assertEqual({t["datum"]: t["status"] for t in ut.tage(self.con, self.k, D(2026, 11, 23), D(2026, 11, 23))},
                         {"2026-11-23": "ferien"})
        kalender.abo_entfernen(self.con, "schule", None)
        self.assertEqual(ut.ferien_liste(self.con), [])


class Pakete(Grund):
    def paket(self):
        with db.transaktion(self.con):
            pid = pakete.anlegen(self.con, self.gob, self.k, "Elektropneumatik", "LF 4")
            pakete.aendern(self.con, self.gob, pid, {"frist": "2026-12-03", "freigabe": "2026-11-02"})
            p1 = pakete.aufgabe_anlegen(self.con, self.gob, pid, {"titel": "Schaltzeichen nach DIN ISO 1219", "frist": "2026-11-05",
                                                                  "moodle_link": "https://moodle.example/mod/assign/view.php?id=4811"})
            p2 = pakete.aufgabe_anlegen(self.con, self.gob, pid, {"titel": "Zylinderkräfte berechnen", "frist": "2026-11-16"})
            ga = pakete.gruppe_anlegen(self.con, self.gob, pid, {"titel": "Lernsituation", "waehlen": 1, "frist": "2026-11-26"})
            a1 = pakete.aufgabe_anlegen(self.con, self.gob, pid, {"art": "wahl", "wahlgruppe_id": ga, "titel": "Stempelvorrichtung"})
            pakete.aufgabe_anlegen(self.con, self.gob, pid, {"art": "wahl", "wahlgruppe_id": ga, "titel": "Sortierweiche"})
            p3 = pakete.aufgabe_anlegen(self.con, self.gob, pid, {"titel": "Weg-Schritt-Diagramm", "voraussetzung_id": p2})
            z1 = pakete.aufgabe_anlegen(self.con, self.gob, pid, {"art": "zusatz", "zusatz_art": "wiederholung", "titel": "Übung Betätigungsarten"})
            pakete.kann_anlegen(self.con, self.gob, pid, {"text": "Ich kann Schaltzeichen lesen und zuordnen.", "aufgaben": [p1]})
            pakete.kann_anlegen(self.con, self.gob, pid, {"text": "Wegeventile benennen", "aufgaben": [p1, a1, z1]})
            pakete.nachweis_anlegen(self.con, self.gob, pid, {"art": "moodle", "ergebnis": "punkte", "max_punkte": 40,
                                                              "moodle_link": "https://moodle.example/mod/quiz/view.php?id=4830"})
        return pid, dict(p1=p1, p2=p2, p3=p3, ga=ga, a1=a1, z1=z1)

    def test_aufbau_kuerzel_fristen(self):
        with db.transaktion(self.con):
            ut.besonders_anlegen(self.con, self.gob, self.k, {"art": "ausfall", "von": "2026-11-16", "grund": "Zwischenprüfung"})
        pid, ids = self.paket()
        p = pakete.holen(self.con, self.gob, pid)
        self.assertEqual([(e["typ"], e.get("kuerzel") or e["buchstabe"]) for e in p["ablauf"]],
                         [("aufgabe", "P1"), ("aufgabe", "P2"), ("gruppe", "A"), ("aufgabe", "P3")])
        gruppe = p["ablauf"][2]
        self.assertEqual([a["kuerzel"] for a in gruppe["aufgaben"]], ["A1", "A2"])
        self.assertEqual(gruppe["aufgaben"][0]["frist"], "2026-11-26")          # von der Gruppe
        self.assertEqual(gruppe["aufgaben"][0]["quelle"], "gruppe")
        p2 = p["ablauf"][1]
        self.assertEqual((p2["frist"], p2["wirksam"]), ("2026-11-16", "2026-11-19"))   # Ausfall: naechster Unterrichtstag
        self.assertIn("Zwischenprüfung", p2["hinweis"])
        self.assertEqual(p["ablauf"][3]["voraussetzung"], "P2")
        self.assertEqual(p["ablauf"][3]["frist"], "2026-12-03")                 # Paket-Frist
        self.assertEqual([(z["kuerzel"], z["zusatz_art"], z["frist"]) for z in p["zusatz"]], [("Z1", "wiederholung", None)])
        self.assertEqual([(k["kuerzel"], k["text"], k["aufgaben_kuerzel"]) for k in p["kann"]],
                         [("K1", "Schaltzeichen lesen und zuordnen.", ["P1"]), ("K2", "Wegeventile benennen", ["A1", "P1", "Z1"])])
        self.assertEqual(p["nachweise"][0]["max_punkte"], 40)
        self.assertEqual(p["freigabe"]["datum"], "2026-11-02")

    def test_reihenfolge_und_entfernen(self):
        pid, ids = self.paket()
        with db.transaktion(self.con):
            pakete.gruppe_aendern(self.con, self.gob, pid, ids["ga"], {"verschieben": -1})
            pakete.aufgabe_aendern(self.con, self.gob, pid, ids["p2"], {"aktiv": False})
        p = pakete.holen(self.con, self.gob, pid)
        self.assertEqual([e.get("kuerzel") or e["buchstabe"] for e in p["ablauf"]], ["P1", "A", "P3"])
        self.assertIsNone(p["ablauf"][2]["voraussetzung"])   # Voraussetzung P2 entfernt
        with db.transaktion(self.con):
            neu = pakete.aufgabe_anlegen(self.con, self.gob, pid, {"titel": "Neue Pflicht"})
        self.assertEqual(pakete.holen(self.con, self.gob, pid)["ablauf"][-1]["kuerzel"], "P4")   # Nummern werden nicht neu vergeben

    def test_rechte(self):
        pid, ids = self.paket()
        self.assertFalse(pakete.holen(self.con, self.sch, pid)["darf_aendern"])
        with self.assertRaises(klassen.KeinZugriff):
            pakete.aufgabe_anlegen(self.con, self.sch, pid, {"titel": "Darf nicht"})
        with self.assertRaises(pakete.PaketFehler):
            pakete.aufgabe_anlegen(self.con, self.gob, pid, {"titel": "Link", "moodle_link": "javascript:alert(1)"})

    def test_kopieren_und_vorlage(self):
        pid, ids = self.paket()
        with db.transaktion(self.con):
            vorlage = pakete.kopieren(self.con, self.gob, pid)
            kopie = pakete.kopieren(self.con, self.gob, vorlage, self.k2, "Elektropneumatik 24b")
        v = pakete.holen(self.con, self.gob, vorlage)
        self.assertTrue(v["vorlage"])
        self.assertIsNone(v["freigabe"])
        self.assertEqual([x["titel"] for x in pakete.vorlagen(self.con, self.gob)], ["Elektropneumatik"])
        self.assertEqual(pakete.vorlagen(self.con, self.sch), [])
        with self.assertRaises(klassen.KeinZugriff):
            pakete.holen(self.con, self.sch, vorlage)
        with self.assertRaises(pakete.PaketFehler):
            pakete.aendern(self.con, self.gob, vorlage, {"freigabe": "2026-11-02"})
        k = pakete.holen(self.con, self.gob, kopie)
        self.assertEqual((k["klasse"], k["titel"]), ("BSMT 24b", "Elektropneumatik 24b"))
        self.assertEqual([e.get("kuerzel") or e["buchstabe"] for e in k["ablauf"]], ["P1", "P2", "A", "P3"])
        self.assertEqual(k["ablauf"][3]["voraussetzung"], "P2")
        self.assertIsNone(k["ablauf"][0]["frist"])
        self.assertEqual(k["kann"][1]["aufgaben_kuerzel"], ["A1", "P1", "Z1"])
        self.assertEqual(k["nachweise"][0]["ergebnis"], "punkte")


if __name__ == "__main__":
    unittest.main()
