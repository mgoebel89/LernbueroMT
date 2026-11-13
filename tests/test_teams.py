"""Tests fuer Lernteams (Stufe G): Team-Modi, Gruenden, Einladen, Beitreten, Austritt mit Zustimmung, Lehrkraft-Teams und
Stammteams, Fertigmeldung mit Bestaetigung, Rueckmeldung mit Team- und Einzelteil, Nachrichten, Teamtermin und die
Uebernahme der alten Zweierteams."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import db, klassen, lernplan, nachrichten, pakete, rueckmeldung as rm, teams, termine
from test_stufe_d import Basis, D, HEUTE


class Lernteams(Basis):
    def setUp(self):
        super().setUp()
        c = self.con
        with db.transaktion(c):
            self.mehmet = c.execute("SELECT * FROM schueler WHERE id = ?", (klassen.schueler_anlegen(c, self.gob, self.k, "Mehmet", "Yilmaz")["id"],)).fetchone()
            self.paul = c.execute("SELECT * FROM schueler WHERE id = ?", (klassen.schueler_anlegen(c, self.gob, self.k, "Paul", "Becker")["id"],)).fetchone()
            pakete.aufgabe_aendern(c, self.gob, self.pid, self.p2, {"team_modus": "frei", "team_min": 2, "team_max": 3})

    def z(self, s):
        return lernplan.zustand(self.con, s, HEUTE)

    def gruenden(self, s, einladen=(), offen=False, bereich="aufgabe", bezug=None):
        with db.transaktion(self.con):
            return teams.gruenden(self.con, s, bereich, bezug or self.p2, offen, [x["id"] for x in einladen], HEUTE)

    def annehmen(self, s, tid):
        with db.transaktion(self.con):
            teams.antworten(self.con, s, tid, True, HEUTE)

    def test_modi_und_einheiten(self):
        p = self.con.execute("SELECT * FROM paket WHERE id = ?", (self.pid,)).fetchone()
        self.assertEqual(teams.einheit(self.con, self.p1)["modus"], "einzeln")
        e = teams.einheit(self.con, self.p2)
        self.assertEqual((e["modus"], e["bereich"], e["bezug_id"], e["max"]), ("frei", "aufgabe", self.p2, 3))
        with db.transaktion(self.con):
            pakete.aendern(self.con, self.gob, self.pid, {"team_modus": "stamm"})
            pakete.gruppe_aendern(self.con, self.gob, self.pid, self.ga, {"team_modus": "pflicht", "team_min": 3, "team_max": 3})
        self.assertEqual(teams.einheit(self.con, self.p1)["bereich"], "stamm")             # vom Paket
        self.assertEqual(teams.einheit(self.con, self.p2)["bereich"], "aufgabe")           # die Aufgabe gilt vor dem Paket
        self.assertEqual(teams.einheit(self.con, self.a1)["bereich"], "gruppe")
        self.assertEqual(teams.einheit(self.con, self.z1)["modus"], "einzeln")             # Zusatzaufgaben immer allein
        p = self.con.execute("SELECT * FROM paket WHERE id = ?", (self.pid,)).fetchone()
        einh = teams.einheiten_paket(self.con, p)
        self.assertEqual(sorted(einh), sorted(["stamm:%d" % self.k, "aufgabe:%d" % self.p2, "gruppe:%d" % self.ga]))
        self.assertEqual(einh["gruppe:%d" % self.ga]["stichtag"], "2026-11-09")              # Vorgabe: Freigabe + 1 Woche
        with self.assertRaisesRegex(teams.TeamFehler, "unter der kleinsten"):
            pakete.aufgabe_aendern(self.con, self.gob, self.pid, self.p2, {"team_modus": "frei", "team_min": 3, "team_max": 2})
        z = self.z(self.lena)
        self.assertEqual(z["pakete"][0]["einheit"], "stamm:%d" % self.k)
        self.assertTrue(z["einheiten"]["gruppe:%d" % self.ga]["selbst"])
        self.assertFalse(z["einheiten"]["stamm:%d" % self.k]["selbst"])

    def test_gruenden_einladen_beitreten_und_plan(self):
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.jonas, self.p2, hinzu=["2026-11-19"], heute=HEUTE)
        with self.assertRaisesRegex(teams.TeamFehler, "allein"):
            teams.gruenden(self.con, self.lena, "aufgabe", self.p1, False, [], HEUTE)
        tid = self.gruenden(self.lena, [self.jonas])
        self.assertEqual([e["id"] for e in self.z(self.jonas)["einladungen"]], [tid])
        self.assertEqual(teams.teamkollegen(self.con, self.lena["id"], self.p2), [])
        self.annehmen(self.jonas, tid)
        self.assertEqual([s["id"] for s in teams.teamkollegen(self.con, self.lena["id"], self.p2)], [self.jonas["id"]])
        self.assertEqual(self.zeile(self.p2)["plan"], ["2026-11-19"])                       # Plaene zusammengefuehrt
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-09"], heute=HEUTE)
            teams.einladen(self.con, self.jonas, tid, [self.mehmet["id"]], HEUTE)
        self.assertEqual(self.zeile(self.p2, self.jonas)["plan"], ["2026-11-09", "2026-11-19"])
        with self.assertRaisesRegex(teams.TeamFehler, "höchstens 3"):
            teams.einladen(self.con, self.lena, tid, [self.paul["id"]], HEUTE)        # 2 aktiv + 1 eingeladen = voll
        with self.assertRaisesRegex(teams.TeamFehler, "nur auf Einladung"):
            teams.beitreten(self.con, self.paul, tid, HEUTE)
        with db.transaktion(self.con):
            teams.offen_setzen(self.con, self.lena, tid, True)
        f = teams.finden(self.con, self.paul, "aufgabe", self.p2, HEUTE)
        self.assertEqual([t["id"] for t in f["offen"]], [tid])
        self.assertNotIn(self.lena["id"], [x["id"] for x in f["frei"]])
        with db.transaktion(self.con):
            teams.beitreten(self.con, self.paul, tid, HEUTE)                              # offener Platz: Paul ist schneller
        with self.assertRaisesRegex(teams.TeamFehler, "voll"):
            teams.antworten(self.con, self.mehmet, tid, True, HEUTE)
        self.assertEqual(self.zeile(self.p2, self.paul)["plan"], ["2026-11-09", "2026-11-19"])
        self.assertEqual(self.zeile(self.p2)["team"]["anzahl"], 3)

    def test_fertig_mit_bestaetigung(self):
        tid = self.gruenden(self.lena, [self.jonas])
        self.annehmen(self.jonas, tid)
        with db.transaktion(self.con):
            mid = rm.fertig_melden(self.con, self.lena, self.p2, {}, HEUTE)
        self.assertEqual(rm.eingang(self.con, self.sch), [])                                # wartet auf Jonas
        w = rm.eingang(self.con, self.sch, wartend=True)
        self.assertEqual((w[0]["meldung_id"], w[0]["wartet"]), (mid, ["Jonas Weber"]))
        self.assertEqual(rm.zaehler(self.con, self.sch), 0)
        b = self.z(self.jonas)["bestaetigen"]
        self.assertEqual((b[0]["kuerzel"], b[0]["von"]), ("P2", "Lena Krämer"))
        with db.transaktion(self.con):
            rm.noch_nicht_fertig(self.con, self.jonas, b[0]["meldung_id"], "Die Einheiten fehlen.")
        verlauf = nachrichten.fuer_schueler(self.con, self.lena)["verlaeufe"]
        team_v = next(v for v in verlauf if v["team_id"] == tid)
        self.assertIn("noch nicht fertig", team_v["nachrichten"][-1]["text"])
        self.assertEqual(team_v["ungelesen"], 1)
        with db.transaktion(self.con):
            rm.fertig_bestaetigen(self.con, self.jonas, b[0]["meldung_id"], {})
        ein = rm.eingang(self.con, self.sch)
        self.assertEqual((len(ein), ein[0]["name"], len(ein[0]["partner"])), (1, "Lena Krämer + Jonas Weber", 1))
        self.assertEqual(rm.zaehler(self.con, self.sch), 1)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "wartet nicht"):
            rm.fertig_bestaetigen(self.con, self.jonas, b[0]["meldung_id"], {})
        # Uebersicht der Lehrkraft: nichts wartet mehr
        u = teams.uebersicht(self.con, self.sch, self.k)
        team = next(e for e in u["einheiten"] if e["bereich"] == "aufgabe")["teams"][0]
        self.assertEqual(team["wartet"], [])

    def test_austritt_nur_mit_zustimmung(self):
        tid = self.gruenden(self.lena, [self.jonas])
        self.annehmen(self.jonas, tid)
        with self.assertRaisesRegex(teams.TeamFehler, "warum"):
            teams.austritt_anfragen(self.con, self.jonas, tid, "")
        with db.transaktion(self.con):
            teams.austritt_anfragen(self.con, self.jonas, tid, "Andere Tage im Betrieb")
        u = teams.uebersicht(self.con, self.sch, self.k)
        e = next(e for e in u["einheiten"] if e["bereich"] == "aufgabe")
        self.assertEqual(e["austritte"], 1)
        self.assertEqual(next(m for m in e["teams"][0]["mitglieder"] if m["id"] == self.jonas["id"])["austritt"], "Andere Tage im Betrieb")
        self.assertIsNotNone(teams.team_fuer_aufgabe(self.con, self.jonas["id"], self.p2))      # bleibt bis zur Zustimmung
        with self.assertRaises(klassen.KeinZugriff):
            teams.austritt_entscheiden(self.con, self.kl, tid, self.jonas["id"], True)        # Einsicht darf nicht
        with db.transaktion(self.con):
            teams.austritt_entscheiden(self.con, self.sch, tid, self.jonas["id"], True)
        self.assertIsNone(teams.team_fuer_aufgabe(self.con, self.jonas["id"], self.p2))
        # vorgegebenes Team: kein Austrittswunsch
        with db.transaktion(self.con):
            pakete.aufgabe_aendern(self.con, self.gob, self.pid, self.p2, {"team_modus": "vorgabe", "team_min": 2, "team_max": 3})
            t2 = teams.bilden(self.con, self.sch, self.k, "aufgabe", self.p2, [self.jonas["id"], self.mehmet["id"]], "Werkbank", HEUTE)
        with self.assertRaisesRegex(teams.TeamFehler, "Lehrkraft gebildet"):
            teams.austritt_anfragen(self.con, self.jonas, t2, "lieber allein")
        with self.assertRaisesRegex(teams.TeamFehler, "bildet deine Lehrkraft"):
            teams.gruenden(self.con, self.paul, "aufgabe", self.p2, False, [], HEUTE)

    def test_stammteams_zuteilen_und_umsetzen(self):
        with db.transaktion(self.con):
            pakete.aendern(self.con, self.gob, self.pid, {"team_modus": "stamm"})
            t1 = teams.bilden(self.con, self.sch, self.k, "stamm", self.k, [self.lena["id"], self.jonas["id"]], "Werkbank 1", HEUTE)
        self.assertEqual([s["id"] for s in teams.teamkollegen(self.con, self.lena["id"], self.p1)], [self.jonas["id"]])
        self.assertEqual(teams.teamkollegen(self.con, self.lena["id"], self.z1), [])               # Zusatz bleibt allein
        u = teams.uebersicht(self.con, self.sch, self.k)
        stamm = next(e for e in u["einheiten"] if e["bereich"] == "stamm")
        self.assertEqual(sorted(s["name"] for s in stamm["ohne_team"]), ["Mehmet Yilmaz", "Paul Becker"])
        self.assertEqual(stamm["teams"][0]["name"], "Werkbank 1")
        with db.transaktion(self.con):
            teams.mitglied_aendern(self.con, self.sch, t1, self.mehmet["id"], "hinzu", HEUTE)
            t2 = teams.bilden(self.con, self.sch, self.k, "stamm", self.k, [self.jonas["id"], self.paul["id"]], "", HEUTE)   # Jonas wechselt
        self.assertEqual(sorted(s["vorname"] for s in teams.teamkollegen(self.con, self.lena["id"], self.p1)), ["Mehmet"])
        self.assertEqual([s["vorname"] for s in teams.teamkollegen(self.con, self.jonas["id"], self.p1)], ["Paul"])
        hinweise = lernplan.matrix(self.con, self.k, heute=HEUTE)
        lena = next(z for z in hinweise["zeilen"] if z["name"] == "Lena Krämer")
        self.assertEqual(lena["teams"], ["Stammteam mit Mehmet Y."])
        with db.transaktion(self.con):
            teams.mitglied_aendern(self.con, self.sch, t2, self.paul["id"], "entfernen", HEUTE)
            teams.mitglied_aendern(self.con, self.sch, t2, self.jonas["id"], "entfernen", HEUTE)
        self.assertEqual(self.con.execute("SELECT status FROM lernteam WHERE id = ?", (t2,)).fetchone()[0], "aufgeloest")
        with self.assertRaisesRegex(teams.TeamFehler, "kein Team-Modus"):
            teams.bilden(self.con, self.sch, self.k, "aufgabe", self.p1, [self.lena["id"]], "", HEUTE)

    def test_rueckmeldung_team_und_einzeln(self):
        tid = self.gruenden(self.lena, [self.jonas])
        self.annehmen(self.jonas, tid)
        with db.transaktion(self.con):
            mid = rm.fertig_melden(self.con, self.lena, self.p2, {}, HEUTE)
            mj = self.z(self.jonas)["bestaetigen"][0]["meldung_id"]
            rm.fertig_bestaetigen(self.con, self.jonas, mj, {})
            rm.speichern_team(self.con, self.sch, {"team_text": "Gut gemacht, ihr beiden.", "entscheidung": "angenommen", "personen": [
                {"schueler_id": self.lena["id"], "meldung_id": mid, "text": "Lena: sauber gerechnet."},
                {"schueler_id": self.jonas["id"], "meldung_id": mj, "text": "Jonas: Einheiten beachten."}]}, freigeben=True, heute=HEUTE)
        lena = rm.fuer_schueler(self.con, self.lena)["rueckmeldungen"][0]
        jonas = rm.fuer_schueler(self.con, self.jonas)["rueckmeldungen"][0]
        self.assertEqual((lena["team_text"], lena["text"]), ("Gut gemacht, ihr beiden.", "Lena: sauber gerechnet."))
        self.assertEqual((jonas["team_text"], jonas["text"]), ("Gut gemacht, ihr beiden.", "Jonas: Einheiten beachten."))
        self.assertEqual(self.zeile(self.p2, self.jonas)["status"], "angenommen")

    def test_nachrichten(self):
        tid = self.gruenden(self.lena, [self.jonas])
        self.annehmen(self.jonas, tid)
        with db.transaktion(self.con):
            nachrichten.senden_lk(self.con, self.sch, "Bringt die Stückliste mit.", team_id=tid)
            nachrichten.senden_lk(self.con, self.sch, "Nur für dich, Lena.", schueler_id=self.lena["id"])
        with self.assertRaises(klassen.KeinZugriff):
            nachrichten.senden_lk(self.con, self.kl, "Einsicht schreibt nicht", team_id=tid)
        self.assertEqual(nachrichten.ungelesen_schueler(self.con, self.jonas), 1)              # nur der Teamverlauf
        self.assertEqual(nachrichten.ungelesen_schueler(self.con, self.lena), 2)
        jv = nachrichten.fuer_schueler(self.con, self.jonas)["verlaeufe"]
        self.assertEqual([v["team_id"] for v in jv], [None, tid])
        self.assertEqual(jv[0]["nachrichten"], [])                                             # Lenas Einzelverlauf sieht Jonas nicht
        with db.transaktion(self.con):
            nachrichten.gelesen_schueler(self.con, self.lena)
            nachrichten.senden_schueler(self.con, self.jonas, "Mit Drossel?", team_id=tid)
        with self.assertRaisesRegex(nachrichten.NachrichtFehler, "nicht"):
            nachrichten.senden_schueler(self.con, self.paul, "Hallo", team_id=tid)
        self.assertEqual(nachrichten.ungelesen_lk(self.con, self.sch), 1)
        self.assertEqual(nachrichten.ungelesen_lk(self.con, self.gob), 1)                     # jede Lehrkraft der Klasse
        v = nachrichten.verlauf_lk(self.con, self.sch, team_id=tid)
        self.assertEqual([n["von"] for n in v["nachrichten"]], ["Anna Schmidt", "Jonas Weber"])
        self.assertEqual(nachrichten.ungelesen_lk(self.con, self.sch), 0)
        self.assertEqual(nachrichten.ungelesen_lk(self.con, self.gob), 1)
        self.assertEqual(nachrichten.ungelesen_schueler(self.con, self.lena), 1)               # Jonas' Antwort im Team

    def test_teamtermin(self):
        tid = self.gruenden(self.lena, [self.jonas])
        self.annehmen(self.jonas, tid)
        with mock.patch.object(db, "heute", return_value=HEUTE), db.transaktion(self.con):
            zid = termine.zeitfenster_anlegen(self.con, self.sch, self.k, {"art": "sprech", "von": "09:30", "bis": "10:30", "dauer": 15,
                                                                           "woechentlich": True, "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})["zeitfenster"]["id"]
        with db.transaktion(self.con):
            termine.buchen(self.con, self.lena, zid, "2026-11-19", "09:30", "feedback", {"team_id": tid}, HEUTE, "07:00")
        zeilen = self.con.execute("SELECT schueler_id, team_id FROM termin WHERE abgesagt IS NULL ORDER BY schueler_id").fetchall()
        self.assertEqual([(z[0], z[1]) for z in zeilen], [(self.lena["id"], tid), (self.jonas["id"], tid)])
        with self.assertRaisesRegex(termine.TerminFehler, "schon einen offenen"):
            termine.buchen(self.con, self.jonas, zid, "2026-11-26", "09:30", "feedback", {"text": "Frage"}, HEUTE, "07:00")
        tj = next(t for t in termine.termine_schueler(self.con, self.jonas, HEUTE))
        self.assertTrue(tj["anlass"].startswith("Team: Lena, Jonas"))
        with db.transaktion(self.con):
            termine.absagen_schueler(self.con, self.jonas, tj["id"], HEUTE)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM termin WHERE abgesagt IS NULL").fetchone()[0], 0)
        with db.transaktion(self.con):
            termine.teamtermin_eintragen(self.con, self.sch, tid, zid, "2026-11-26", "09:45", "Stückliste mitbringen", HEUTE, "07:00")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM termin WHERE abgesagt IS NULL AND pflicht = 1 AND team_id = ?", (tid,)).fetchone()[0], 2)
        heute = termine.termine_heute(self.con, self.sch, D(2026, 11, 26))
        self.assertEqual([t["name"] for t in heute], ["Lena, Jonas"])


class Uebernahme(unittest.TestCase):
    def test_zweierteams_werden_lernteams(self):
        ordner = tempfile.mkdtemp()
        try:
            con = db.verbinden(os.path.join(ordner, "x.sqlite"))
            with mock.patch.object(db, "MIGRATIONEN", db.MIGRATIONEN[:10]):
                db.migrieren(con)
            j = db.jetzt()
            con.execute("INSERT INTO lehrkraft (kuerzel, name, rolle, pw, erstellt) VALUES ('a', 'A', 'admin', 'x', ?)", (j,))
            con.execute("INSERT INTO klasse (name, erstellt) VALUES ('K', ?)", (j,))
            for n in ("Lena", "Jonas"):
                con.execute("INSERT INTO schueler (klasse_id, vorname, nachname, code, erstellt) VALUES (1, ?, 'X', ?, ?)", (n, n.upper() + "2345678"[:8 - len(n)], j))
            con.execute("INSERT INTO paket (klasse_id, titel, erstellt, team) VALUES (1, 'P', ?, 1)", (j,))
            con.execute("INSERT INTO aufgabe (paket_id, kuerzel, titel, art, pos, erstellt, team) VALUES (1, 'P1', 'T', 'pflicht', 1, ?, 1)", (j,))
            con.execute("INSERT INTO team (klasse_id, bereich, bezug_id, a_id, b_id, status, erstellt, bestaetigt) VALUES (1, 'paket', 1, 1, 2, 'aktiv', ?, ?)",
                        (j, j + "x"))
            con.execute("INSERT INTO meldung (schueler_id, aufgabe_id, zeit) VALUES (1, 1, ?)", (j,))
            db.migrieren(con)
            p = con.execute("SELECT team_modus, team_min, team_max FROM paket").fetchone()
            self.assertEqual(tuple(p), ("frei", 2, 2))
            self.assertEqual(con.execute("SELECT bereich, bezug_id, quelle, status FROM lernteam").fetchone()[:], ("paket", 1, "schueler", "aktiv"))
            self.assertEqual(sorted((z[0], z[1]) for z in con.execute("SELECT schueler_id, status FROM lernteam_mitglied")), [(1, "aktiv"), (2, "aktiv")])
            self.assertEqual([s["id"] for s in teams.teamkollegen(con, 1, 1)], [2])
            self.assertIsNotNone(con.execute("SELECT bestaetigt FROM meldung").fetchone()[0])
            con.close()
        finally:
            shutil.rmtree(ordner, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
