"""Tests fuer Zweierteams: Einladung, gemeinsamer Plan und Wahl, gemeinsame Fertigmeldung und Rueckmeldung, Paket-Team."""
import unittest
from unittest import mock

from app import db, klassen, lernplan, pakete, rueckmeldung as rm, teams, termine
from test_stufe_d import Basis, D, HEUTE


class Teams(Basis):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con):
            pakete.aufgabe_aendern(self.con, self.gob, self.pid, self.p2, {"team": True})
            pakete.aufgabe_aendern(self.con, self.gob, self.pid, self.a1, {"team": True})

    def z(self, s):
        return lernplan.zustand(self.con, s, HEUTE)

    def test_einladen_annehmen_gemeinsamer_plan_und_meldung(self):
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-09"], heute=HEUTE)
            lernplan.planen(self.con, self.jonas, self.p2, hinzu=["2026-11-19"], heute=HEUTE)
        with self.assertRaisesRegex(teams.TeamFehler, "anderen"):
            teams.einladen(self.con, self.lena, "aufgabe", self.p2, self.lena["id"], HEUTE)
        with self.assertRaisesRegex(teams.TeamFehler, "nicht für Zweierteams"):
            teams.einladen(self.con, self.lena, "aufgabe", self.p1, self.jonas["id"], HEUTE)
        with db.transaktion(self.con):
            tid = teams.einladen(self.con, self.lena, "aufgabe", self.p2, self.jonas["id"], HEUTE)
        zj = self.z(self.jonas)
        self.assertEqual([(e["id"], e["partner"]) for e in zj["einladungen"]], [(tid, "Lena Krämer")])
        self.assertIsNone(teams.partner(self.con, self.lena["id"], self.p2))
        with self.assertRaisesRegex(teams.TeamFehler, "nur der Eingeladene"):
            teams.antworten(self.con, self.lena, tid, True, HEUTE)
        with db.transaktion(self.con):
            teams.antworten(self.con, self.jonas, tid, True, HEUTE)
        self.assertEqual(teams.partner(self.con, self.lena["id"], self.p2)["id"], self.jonas["id"])
        # Plaene zusammengefuehrt, danach gespiegelt
        self.assertEqual(self.zeile(self.p2)["plan"], ["2026-11-09", "2026-11-19"])
        self.assertEqual(self.zeile(self.p2, self.jonas)["plan"], ["2026-11-09", "2026-11-19"])
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.jonas, self.p2, hinzu=["2026-11-23"], weg=["2026-11-09"], heute=HEUTE)
        self.assertEqual(self.zeile(self.p2)["plan"], ["2026-11-19", "2026-11-23"])
        self.assertEqual(self.zeile(self.p2)["team"]["partner"], "Jonas Weber")
        # Farbmarkierung bleibt je Person
        with db.transaktion(self.con):
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-05", "y", HEUTE)
        self.assertEqual(self.zeile(self.p2, self.jonas)["ist"], {})
        # einer meldet fuer beide
        with db.transaktion(self.con):
            mid = rm.fertig_melden(self.con, self.lena, self.p2, {}, HEUTE)
        self.assertEqual(self.zeile(self.p2, self.jonas)["status"], "fertig")
        ein = rm.eingang(self.con, self.gob)
        self.assertEqual(len(ein), 1)
        self.assertEqual(ein[0]["name"], "Lena Krämer + Jonas Weber")
        pm = ein[0]["partner"][0]["meldung_id"]
        v = rm.vorlage(self.con, self.gob, self.lena["id"], meldung_id=mid, heute=HEUTE)
        self.assertEqual([p["schueler"]["vorname"] for p in v["partner"]], ["Jonas"])
        # Gespraech fuer beide im selben Platz
        with db.transaktion(self.con), mock.patch.object(db, "heute", return_value=HEUTE):
            zf = termine.zeitfenster_anlegen(self.con, self.gob, self.k, {"art": "sprech", "von": "09:30", "bis": "10:30", "dauer": 10,
                                                                         "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})["zeitfenster"]
            termine.gespraech_eintragen(self.con, self.gob, mid, zf["id"], "2026-11-19", "09:30", heute=HEUTE, jetzt_hhmm="09:00")
        self.assertEqual(termine.termine_schueler(self.con, self.jonas, HEUTE)[0]["pflicht"], True)
        bel = termine.belegung(self.con, self.gob, self.k, von=D(2026, 11, 19), tage=1)
        self.assertIn("Lena Krämer + Jonas Weber", [p["termin"]["name"] for p in bel[0]["plaetze"] if p.get("termin")])
        # eine Rueckmeldung, Entscheidung fuer beide, Kann und Empfehlungen je Person
        with db.transaktion(self.con):
            rm.speichern_team(self.con, self.gob, {"text": "Gut zusammengearbeitet.", "entscheidung": "ueberarbeiten", "neue_frist": "2026-11-23",
                                                   "personen": [{"schueler_id": self.lena["id"], "meldung_id": mid, "empfehlungen": [{"aufgabe_id": self.z1}]},
                                                                {"schueler_id": self.jonas["id"], "meldung_id": pm}]},
                              freigeben=True, heute=HEUTE)
        self.assertEqual((self.zeile(self.p2)["status"], self.zeile(self.p2, self.jonas)["status"]), ("ueberarbeiten", "ueberarbeiten"))
        self.assertEqual(rm.fuer_schueler(self.con, self.jonas)["rueckmeldungen"][0]["text"], "Gut zusammengearbeitet.")
        self.assertEqual(len(rm.fuer_schueler(self.con, self.jonas)["rueckmeldungen"][0]["empfehlungen"]), 0)
        self.assertEqual(len(rm.fuer_schueler(self.con, self.lena)["rueckmeldungen"][0]["empfehlungen"]), 1)
        # zurueckziehen einer neuen Teammeldung gilt fuer beide
        with db.transaktion(self.con):
            mid2 = rm.fertig_melden(self.con, self.jonas, self.p2, {}, HEUTE)
            rm.zurueckziehen(self.con, self.jonas, mid2)
        self.assertEqual(self.zeile(self.p2)["status"], "ueberarbeiten")

    def test_paket_team_wahl_gespiegelt_und_aufloesen(self):
        with db.transaktion(self.con):
            pakete.aendern(self.con, self.gob, self.pid, {"team": True})
        with self.assertRaisesRegex(teams.TeamFehler, "Paket-Team"):
            teams.einladen(self.con, self.lena, "aufgabe", self.p2, self.jonas["id"], HEUTE)
        with self.assertRaises(klassen.KeinZugriff):
            teams.bilden(self.con, self.kl, self.k, "paket", self.pid, self.lena["id"], self.jonas["id"], HEUTE)
        with db.transaktion(self.con):
            tid = teams.bilden(self.con, self.sch, self.k, "paket", self.pid, self.lena["id"], self.jonas["id"], HEUTE)
            lernplan.waehlen(self.con, self.lena, self.a1, heute=HEUTE)
            lernplan.planen(self.con, self.lena, self.p1, hinzu=["2026-11-09"], heute=HEUTE)
        self.assertTrue(self.zeile(self.a1, self.jonas)["gewaehlt"])
        self.assertEqual(self.zeile(self.p1, self.jonas)["plan"], ["2026-11-09"])
        self.assertIsNone(teams.partner(self.con, self.lena["id"], self.z1))                   # Zusatzaufgaben nie im Team
        m = lernplan.matrix(self.con, self.k, heute=HEUTE)
        self.assertEqual(next(z for z in m["zeilen"] if z["id"] == self.lena["id"])["teams"], ["Paket mit Jonas Weber"])
        lst = teams.liste_klasse(self.con, self.kl, self.k, self.pid)
        self.assertEqual(([t["titel"] for t in lst["teams"]], lst["darf"]), (["ganzes Paket Elektropneumatik"], False))
        with db.transaktion(self.con):
            lernplan.waehlen(self.con, self.jonas, self.a1, False, heute=HEUTE)
        self.assertFalse(self.zeile(self.a1)["gewaehlt"])
        with db.transaktion(self.con):
            teams.aufloesen(self.con, self.sch, tid)
            lernplan.planen(self.con, self.lena, self.p1, hinzu=["2026-11-19"], heute=HEUTE)
        self.assertEqual(self.zeile(self.p1, self.jonas)["plan"], ["2026-11-09"])

    def test_abwahl_beendet_aufgaben_team_und_ablehnen(self):
        with db.transaktion(self.con):
            lernplan.waehlen(self.con, self.lena, self.a1, heute=HEUTE)
            tid = teams.einladen(self.con, self.lena, "aufgabe", self.a1, self.jonas["id"], HEUTE)
            teams.antworten(self.con, self.jonas, tid, True, HEUTE)
        self.assertTrue(self.zeile(self.a1, self.jonas)["gewaehlt"])                           # Partner waehlt mit
        with db.transaktion(self.con):
            lernplan.waehlen(self.con, self.lena, self.a1, False, heute=HEUTE)
        self.assertIsNone(teams.partner(self.con, self.jonas["id"], self.a1))
        with db.transaktion(self.con):
            lernplan.waehlen(self.con, self.lena, self.a1, heute=HEUTE)
            tid2 = teams.einladen(self.con, self.lena, "aufgabe", self.a1, self.jonas["id"], HEUTE)
            teams.antworten(self.con, self.jonas, tid2, False, HEUTE)
        self.assertEqual(self.z(self.jonas)["einladungen"], [])
        self.assertIsNone(teams.partner(self.con, self.lena["id"], self.a1))


if __name__ == "__main__":
    unittest.main()
