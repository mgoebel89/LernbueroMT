"""Tests fuer Stufe A: Datenbank, Konten, Klassen mit Team und Einsicht, Moodle-Import, QR-Code, PDF, Webserver.
Aufruf im Repo-Ordner:  python -m unittest discover -s tests
"""
import ast
import http.client
import json
import os
import pathlib
import shutil
import tempfile
import threading
import unittest

from app import db, klassen, konten, moodle, pdf, qr, server

REPO = pathlib.Path(__file__).resolve().parent.parent


class Python311(unittest.TestCase):
    """Der Container hat Python 3.12, das Repo soll aber auch mit 3.11 laufen (Debian 12)."""

    def test_syntax(self):
        for datei in REPO.rglob("*.py"):
            with self.subTest(datei=str(datei.relative_to(REPO))):
                ast.parse(datei.read_text(encoding="utf-8"), feature_version=(3, 11))


class MitDatenbank(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def konto(self, kuerzel="gob", rolle="admin"):
        with db.transaktion(self.con):
            return konten.anlegen(self.con, kuerzel, "Konto " + kuerzel.upper(), rolle, "geheim123", vorlaeufig=False)


class Konten(MitDatenbank):
    def test_anmelden_und_sitzung(self):
        k = self.konto()
        wert, konto = konten.anmelden(self.con, "GOB", "geheim123")
        self.assertEqual(konto["id"], k["id"])
        self.assertEqual(konten.sitzung_pruefen(self.con, wert)["kuerzel"], "gob")
        with self.assertRaises(konten.KontoFehler):
            konten.anmelden(self.con, "gob", "falsch123")

    def test_einrichtungscode_nur_ohne_konto(self):
        code = konten.einrichtungscode(self.con)
        self.assertRegex(code, r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}")
        with db.transaktion(self.con):
            konten.einrichten(self.con, code.lower(), "gob", "Matthias Göbel", "geheim123")
        self.assertIsNone(konten.einrichtungscode(self.con))


class Klassen(MitDatenbank):
    def setUp(self):
        super().setUp()
        self.gob = self.konto("gob", "lehrkraft")
        self.sch = self.konto("sch", "lehrkraft")
        self.adm = self.konto("adm", "admin")
        with db.transaktion(self.con):
            self.k = klassen.anlegen(self.con, self.gob, "BSMT 24a", "2026/27")

    def test_ersteller_ist_team_andere_sehen_nichts(self):
        self.assertEqual(self.k["rolle"], "team")
        self.assertEqual([k["name"] for k in klassen.liste(self.con, self.gob)], ["BSMT 24a"])
        self.assertEqual(klassen.liste(self.con, self.sch), [])
        with self.assertRaises(klassen.KeinZugriff):
            klassen.holen(self.con, self.sch, self.k["id"])

    def test_einsicht_liest_ohne_codes_und_aendert_nichts(self):
        with db.transaktion(self.con):
            klassen.schueler_anlegen(self.con, self.gob, self.k["id"], "Lena", "Krämer")
            klassen.lehrkraft_setzen(self.con, self.gob, self.k["id"], self.sch["id"], "einsicht")
        d = klassen.holen(self.con, self.sch, self.k["id"])
        self.assertEqual(d["rolle"], "einsicht")
        self.assertNotIn("code", d["schueler"][0])
        self.assertIn("code", klassen.holen(self.con, self.gob, self.k["id"])["schueler"][0])
        with self.assertRaises(klassen.KeinZugriff):
            klassen.schueler_anlegen(self.con, self.sch, self.k["id"], "Tim", "Schäfer")

    def test_admin_sieht_klasse_aber_keine_schueler(self):
        d = klassen.holen(self.con, self.adm, self.k["id"])
        self.assertEqual(d["rolle"], "admin")
        self.assertNotIn("schueler", d)
        with db.transaktion(self.con):
            klassen.lehrkraft_setzen(self.con, self.adm, self.k["id"], self.sch["id"], "team")
        self.assertEqual(klassen.holen(self.con, self.sch, self.k["id"])["rolle"], "team")

    def test_letzte_lehrkraft_im_team_bleibt(self):
        with self.assertRaises(klassen.KlassenFehler):
            klassen.lehrkraft_setzen(self.con, self.gob, self.k["id"], self.gob["id"], "einsicht")
        with self.assertRaises(klassen.KlassenFehler):
            klassen.lehrkraft_setzen(self.con, self.gob, self.k["id"], self.gob["id"], None)

    def test_code_neu_macht_alten_ungueltig(self):
        with db.transaktion(self.con):
            s = klassen.schueler_anlegen(self.con, self.gob, self.k["id"], "Lena", "Krämer")
        alt = s["code"]
        self.assertRegex(alt, r"[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}")
        self.assertEqual(klassen.per_code(self.con, alt.lower())["vorname"], "Lena")
        with db.transaktion(self.con):
            neu = klassen.schueler_aendern(self.con, self.gob, self.k["id"], s["id"], {"code_neu": True})["code"]
        self.assertIsNone(klassen.per_code(self.con, alt))
        self.assertIsNotNone(klassen.per_code(self.con, neu))
        with db.transaktion(self.con):
            klassen.aendern(self.con, self.gob, self.k["id"], {"archiviert": True})
        self.assertIsNone(klassen.per_code(self.con, neu))


class Moodle(unittest.TestCase):
    CSV = ("﻿Vorname,Nachname,ID-Nummer,E-Mail-Adresse,Rollen\n"
           "Lena,Krämer,123,lena@x.de,Teilnehmer/in\n"
           "Jonas,Weber,124,jonas@x.de,Teilnehmer/in\n"
           "Matthias,Göbel,9,mg@x.de,Trainer/in\n"
           "Elif,Demir,125,elif@x.de,Teilnehmer/in\n"
           "Lena,Krämer,123,lena@x.de,Teilnehmer/in\n")

    def test_csv_mit_rollen(self):
        eintraege, art = moodle.lesen(self.CSV)
        self.assertEqual(art, "moodle-csv")
        self.assertEqual([e["nachname"] for e in eintraege], ["Krämer", "Weber", "Göbel", "Demir", "Krämer"])
        self.assertTrue(eintraege[2]["lehrkraft"])
        self.assertNotIn("email", eintraege[0])

    def test_semikolon_und_liste_und_json(self):
        self.assertEqual(moodle.lesen("Vorname;Nachname\nTim;Schäfer\n")[0][0]["vorname"], "Tim")
        self.assertEqual(moodle.lesen("Schäfer;Tim\nBecker;Paul\n")[0][1], dict(vorname="Paul", nachname="Becker", lehrkraft=False, rolle=""))
        daten = json.dumps([[{"Vorname": "Sarah", "Nachname": "Hoffmann", "Rollen": "Teilnehmer/in"}]])
        self.assertEqual(moodle.lesen(daten)[0][0]["nachname"], "Hoffmann")
        with self.assertRaises(moodle.MoodleFehler):
            moodle.lesen("nur Unsinn ohne Trenner\n" * 0 + " ")

    def test_abgleich(self):
        vorhandene = [
            {"id": 1, "vorname": "Lena", "nachname": "Kraemer", "aktiv": 1},     # Umlaut gefaltet
            {"id": 2, "vorname": "Jo", "nachname": "Weber", "aktiv": 1},          # nur Nachname eindeutig
            {"id": 3, "vorname": "Kevin", "nachname": "Braun", "aktiv": 1},       # fehlt in Moodle
            {"id": 4, "vorname": "Elif", "nachname": "Demir", "aktiv": 0},        # archiviert -> wieder aktiv
            {"id": 5, "vorname": "Anna", "nachname": "Meyer", "aktiv": 1},
        ]
        eintraege, _ = moodle.lesen(self.CSV + "Anna,Meyer-Schmidt,1,a@x.de,Teilnehmer/in\n")
        zeilen = moodle.abgleich(vorhandene, eintraege)
        aktion = {(z["vorname"], z["nachname"]): (z["aktion"], z["schueler_id"]) for z in zeilen if z["aktion"] != "doppelt"}
        self.assertEqual(aktion[("Lena", "Krämer")], ("behalten", 1))
        self.assertEqual(aktion[("Jonas", "Weber")], ("behalten", 2))
        self.assertEqual(aktion[("Matthias", "Göbel")][0], "lehrkraft")
        self.assertEqual(aktion[("Elif", "Demir")], ("reaktivieren", 4))
        self.assertEqual(aktion[("Anna", "Meyer-Schmidt")], ("neu", None))   # Meyer trifft nie Meyer-Schmidt
        self.assertEqual(aktion[("Kevin", "Braun")], ("fehlt", 3))
        self.assertEqual(aktion[("Anna", "Meyer")], ("fehlt", 5))
        self.assertEqual(sum(1 for z in zeilen if z["aktion"] == "doppelt"), 1)

    def test_voller_name_schlaegt_nachname(self):
        vorhandene = [{"id": 1, "vorname": "Tim", "nachname": "Weber", "aktiv": 1}]
        eintraege, _ = moodle.lesen("Vorname,Nachname\nJonas,Weber\nTim,Weber\n")
        zeilen = moodle.abgleich(vorhandene, eintraege)
        self.assertEqual([(z["vorname"], z["aktion"]) for z in zeilen], [("Jonas", "neu"), ("Tim", "behalten")])


class QR(unittest.TestCase):
    def test_reed_solomon_beispiel(self):
        # bekanntes Beispiel "HELLO WORLD", Version 1-M (thonky.com)
        daten = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(qr.rs_rest(daten, qr.rs_teiler(10)), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_formatbits(self):
        self.assertEqual(format(qr.format_bits(0), "015b"), "101010000010010")   # M, Maske 0

    def test_groesse_und_muster(self):
        m = qr.matrix("http://192.168.7.3/s/K7Q4M2XD")
        self.assertEqual(len(m), 29)   # Version 3
        for x, y in ((0, 0), (22, 0), (0, 22)):   # Suchmuster: Rand dunkel, Ring hell, Kern dunkel
            self.assertTrue(all(m[y][x + i] for i in range(7)))
            self.assertFalse(m[y + 1][x + 1])
            self.assertTrue(m[y + 3][x + 3])
        self.assertTrue(m[29 - 8][8])   # dunkles Modul
        self.assertTrue(qr.svg("x").startswith("<svg"))
        with self.assertRaises(qr.QrFehler):
            qr.matrix("x" * 400)


class PDF(unittest.TestCase):
    def test_qr_karten(self):
        schueler = [{"vorname": "Lena", "nachname": "Krämer", "code": "K7Q4M2XD"}] * 12
        daten = pdf.qr_karten("BSMT 24a", schueler, "http://192.168.7.3")
        self.assertTrue(daten.startswith(b"%PDF-1.4"))
        self.assertTrue(daten.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/Count 2", daten)
        self.assertIn(b"K7Q4-M2XD", daten)


class Webserver(unittest.TestCase):
    """Echter Server auf zufaelligen Ports: Lehrerseite (wie HTTPS, hier ohne TLS) und Schuelerport."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        db.oeffnen(self.ordner).close()
        pfad = db.pfad(self.ordner)
        self.lehrer = server.HTTPServer(("127.0.0.1", 0), server.Handler, pfad)
        self.schueler = server.HTTPServer(("127.0.0.1", 0), server.SchuelerHandler, pfad)
        for s in (self.lehrer, self.schueler):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        self.cookie = None

    def tearDown(self):
        for s in (self.lehrer, self.schueler):
            s.shutdown()
            s.server_close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def anfrage(self, methode, pfad, daten=None, port=None, kopf=True):
        c = http.client.HTTPConnection("127.0.0.1", port or self.lehrer.server_address[1], timeout=10)
        koepfe = {"Content-Type": "application/json"}
        if kopf:
            koepfe["X-Lernbuero"] = "1"
        if self.cookie:
            koepfe["Cookie"] = self.cookie
        c.request(methode, pfad, body=json.dumps(daten).encode() if daten is not None else None, headers=koepfe)
        r = c.getresponse()
        inhalt = r.read()
        neu = r.getheader("Set-Cookie")
        if neu:
            self.cookie = neu.split(";")[0]
        c.close()
        try:
            return r.status, json.loads(inhalt)
        except ValueError:
            return r.status, inhalt

    def test_ablauf(self):
        con = db.verbinden(db.pfad(self.ordner))
        code = konten.einrichtungscode(con)
        con.close()
        status, _ = self.anfrage("POST", "/api/einrichtung", {"code": code, "kuerzel": "gob", "name": "Matthias Göbel",
                                                               "passwort": "geheim123"})
        self.assertEqual(status, 200)
        self.assertEqual(self.anfrage("POST", "/api/klassen", {"name": "BSMT 24a"}, kopf=False)[0], 403)   # ohne Schutzkopf
        status, d = self.anfrage("POST", "/api/klassen", {"name": "BSMT 24a", "schuljahr": "2026/27"})
        kid = d["klasse"]["id"]
        status, d = self.anfrage("POST", "/api/klassen/%d/moodle/vorschau" % kid, {"datei": Moodle.CSV})
        self.assertEqual(status, 200)
        self.assertEqual(sorted(z["aktion"] for z in d["zeilen"]), ["doppelt", "lehrkraft", "neu", "neu", "neu"])
        status, d = self.anfrage("POST", "/api/klassen/%d/moodle/uebernehmen" % kid, {"datei": Moodle.CSV})
        self.assertEqual(d["ergebnis"], {"neu": 3, "reaktiviert": 0, "archiviert": 0})
        lena = [s for s in d["klasse"]["schueler"] if s["vorname"] == "Lena"][0]
        status, inhalt = self.anfrage("GET", "/api/klassen/%d/qr-karten.pdf" % kid)
        self.assertEqual(status, 200)
        self.assertTrue(inhalt.startswith(b"%PDF"))

        # Schuelerport: nur Schuelerpfade, Lehrerpfade werden umgeleitet bzw. abgelehnt
        sp = self.schueler.server_address[1]
        self.cookie = None
        status, d = self.anfrage("GET", "/api/s/" + lena["code"], port=sp)
        self.assertEqual((status, d["vorname"], d["klasse"]), (200, "Lena", "BSMT 24a"))
        self.assertEqual(self.anfrage("GET", "/api/s/ABCD-EFGH", port=sp)[0], 404)
        self.assertEqual(self.anfrage("GET", "/lehrer", port=sp)[0], 301)
        self.assertEqual(self.anfrage("POST", "/api/anmelden", {"kuerzel": "gob", "passwort": "geheim123"}, port=sp)[0], 403)
        self.assertEqual(self.anfrage("GET", "/", port=sp)[0], 200)   # Startseite zum Code-Eingeben
        self.assertEqual(self.anfrage("GET", "/s/" + lena["code"], port=sp)[0], 200)


if __name__ == "__main__":
    unittest.main()
