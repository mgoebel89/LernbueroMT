"""Kalender-Abos (ICS), Bauweise wie im TrackingDRS. Stufe B: der Schulkalender (Admin), aus ihm kommen die Ferien
(ganztaegige Eintraege, deren Titel ein Stichwort wie "Ferien" enthaelt). Der Dienstkalender je Lehrkraft folgt mit
Stufe F (Tabelle und Abruf sind schon dafuer gebaut). Der Server holt die Abos alle 30 Minuten neu, nur lesend.

Abruf nur ueber https und nur zu oeffentlichen Adressen (der Container haengt im Schulnetz).
Ohne die Pakete python3-icalendar und python3-recurring-ical-events bleibt der Rest der Anwendung lauffaehig.
"""
import datetime
import ipaddress
import socket
import urllib.parse
import urllib.request

from . import db

try:
    import icalendar
    import recurring_ical_events
except ImportError:   # lokal ohne Pakete: Abos melden einen Fehler, alles andere laeuft
    icalendar = recurring_ical_events = None

ABRUF_ALLE = datetime.timedelta(minutes=30)
MAX_GROESSE = 5 * 1024 * 1024
TAGE_ZURUECK, TAGE_VORAUS = 60, 400
STICHWOERTER = "Ferien, Feiertag, beweglicher Ferientag, unterrichtsfrei"
TAG = datetime.timedelta(days=1)


class KalenderFehler(Exception):
    pass


def url_pruefen(url):
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    teile = urllib.parse.urlsplit(url)
    if teile.scheme != "https" or not teile.hostname or len(url) > 2000:
        raise KalenderFehler("Bitte den vollständigen ICS-Link angeben (beginnt mit https:// oder webcal://).")
    return url


def _oeffentlich(url):
    """Nur Adressen im Internet: kein Zugriff auf das Schulnetz oder den Container selbst."""
    host = urllib.parse.urlsplit(url).hostname
    try:
        adressen = {a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        raise KalenderFehler("Der Server %s ist nicht erreichbar." % host)
    for a in adressen:
        if not ipaddress.ip_address(a.split("%")[0]).is_global:
            raise KalenderFehler("Kalender-Abos gehen nur zu Adressen im Internet.")


class _Weiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, neu):
        neu = url_pruefen(urllib.parse.urljoin(req.full_url, neu))
        _oeffentlich(neu)
        return super().redirect_request(req, fp, code, msg, headers, neu)


def herunterladen(url):
    _oeffentlich(url)
    oeffner = urllib.request.build_opener(_Weiterleitung)
    try:
        with oeffner.open(urllib.request.Request(url, headers={"User-Agent": "LernbueroMT"}), timeout=20) as antwort:
            daten = antwort.read(MAX_GROESSE + 1)
    except KalenderFehler:
        raise
    except Exception as f:
        raise KalenderFehler("Abruf fehlgeschlagen: %s" % (getattr(f, "reason", None) or f))
    if len(daten) > MAX_GROESSE:
        raise KalenderFehler("Der Kalender ist zu groß (höchstens 5 MB).")
    return daten


def _lokal(wert):
    if wert.tzinfo is not None and db.ZONE is not None:
        wert = wert.astimezone(db.ZONE)
    return wert.replace(tzinfo=None, second=0, microsecond=0)


def termine_aus_ics(daten, von, bis):
    """Eintraege zwischen von und bis (date), Serien aufgeloest. Ganztaegige Eintraege mit Datum, Ende einschliesslich."""
    if icalendar is None:
        raise KalenderFehler("Für Kalender-Abos fehlen die Pakete python3-icalendar und python3-recurring-ical-events "
                             "(lernbuero-update installiert sie).")
    try:
        cal = icalendar.Calendar.from_ical(daten)
        ereignisse = recurring_ical_events.of(cal).between(von, bis)
    except Exception:
        raise KalenderFehler("Unter dieser Adresse liegt kein lesbarer Kalender (ICS).")
    liste = []
    for e in ereignisse:
        if str(e.get("STATUS", "")).upper() == "CANCELLED" or e.get("DTSTART") is None:
            continue
        start = e.get("DTSTART").dt
        ende = e.get("DTEND").dt if e.get("DTEND") is not None else None
        if ende is None and e.get("DURATION") is not None:
            ende = start + e.get("DURATION").dt
        titel = str(e.get("SUMMARY") or "(ohne Titel)").strip()[:200]
        ort = str(e.get("LOCATION") or "").strip()[:200]
        if isinstance(start, datetime.datetime):
            start = _lokal(start)
            ende = _lokal(ende) if isinstance(ende, datetime.datetime) else start
            liste.append({"beginn": start.isoformat(timespec="minutes"), "ende": max(ende, start).isoformat(timespec="minutes"),
                          "ganztags": False, "titel": titel, "ort": ort})
        else:
            letzter = (ende - TAG) if isinstance(ende, datetime.date) and ende > start else start
            liste.append({"beginn": start.isoformat(), "ende": letzter.isoformat(), "ganztags": True, "titel": titel, "ort": ort})
    liste.sort(key=lambda t: t["beginn"])
    return liste


def ferien_aus(liste, stichwoerter):
    woerter = [w.strip().lower() for w in (stichwoerter or "").split(",") if w.strip()]
    return sorted({(t["beginn"][:10], t["ende"][:10], t["titel"][:80]) for t in liste
                   if t["ganztags"] and any(w in t["titel"].lower() for w in woerter)})


def _abo(con, art, lehrkraft_id):
    return con.execute("SELECT * FROM kalender_abo WHERE art = ? AND COALESCE(lehrkraft_id, 0) = ?",
                       (art, lehrkraft_id or 0)).fetchone()


def abo_status(con, art, lehrkraft_id=None):
    """Die Adresse selbst ist geheim (wer sie hat, liest mit): die Oberflaeche sieht nur den Server."""
    a = _abo(con, art, lehrkraft_id)
    if a is None:
        return None
    teile = urllib.parse.urlsplit(a["url"])
    return {"adresse": "%s://%s/…" % (teile.scheme, teile.hostname), "stand": a["stand"], "versuch": a["versuch"],
            "fehler": a["fehler"], "anzahl": a["anzahl"]}


def abo_setzen(con, art, lehrkraft_id, url, laden=herunterladen):
    url = url_pruefen(url)
    with db.transaktion(con):
        a = _abo(con, art, lehrkraft_id)
        if a is None:
            con.execute("INSERT INTO kalender_abo (art, lehrkraft_id, url) VALUES (?, ?, ?)", (art, lehrkraft_id, url))
        else:
            con.execute("UPDATE kalender_abo SET url = ?, versuch = NULL, stand = NULL, fehler = NULL WHERE id = ?", (url, a["id"]))
    return abrufen(con, art, lehrkraft_id, laden)


def abo_entfernen(con, art, lehrkraft_id):
    with db.transaktion(con):
        a = _abo(con, art, lehrkraft_id)
        if a is not None:
            con.execute("DELETE FROM kalender_abo WHERE id = ?", (a["id"],))
            if art == "schule":
                _ferien_uebernehmen(con, [])


def _ferien_uebernehmen(con, neu):
    """Ferien aus dem Schulkalender ersetzen (quelle 'abo'); von Hand eingetragene bleiben. In einer Transaktion."""
    alt = sorted((z["von"], z["bis"], z["name"]) for z in con.execute("SELECT * FROM ferien WHERE quelle = 'abo' AND aktiv = 1"))
    if alt == sorted(neu):
        return False
    con.execute("UPDATE ferien SET aktiv = 0 WHERE quelle = 'abo' AND aktiv = 1")
    con.executemany("INSERT INTO ferien (von, bis, name, quelle) VALUES (?, ?, ?, 'abo')", neu)
    db.ereignis(con, None, None, "system", "System", "ferien_abo", anzahl=len(neu))
    return True


def abrufen(con, art, lehrkraft_id=None, laden=herunterladen):
    """Holt ein Abo neu. Bei einem Fehler bleiben die zuletzt geholten Termine stehen, der Fehler wird gemerkt."""
    a = _abo(con, art, lehrkraft_id)
    if a is None:
        raise KalenderFehler("Es ist kein Kalender hinterlegt.")
    jetzt = db.jetzt()
    heute = datetime.date.fromisoformat(jetzt[:10])
    try:
        liste = termine_aus_ics(laden(a["url"]), heute - TAGE_ZURUECK * TAG, heute + TAGE_VORAUS * TAG)
    except KalenderFehler as f:
        con.execute("UPDATE kalender_abo SET versuch = ?, fehler = ? WHERE id = ?", (jetzt, str(f), a["id"]))
        return abo_status(con, art, lehrkraft_id)
    with db.transaktion(con):
        con.execute("DELETE FROM kalender_termin WHERE abo_id = ?", (a["id"],))
        con.executemany("INSERT INTO kalender_termin (abo_id, beginn, ende, ganztags, titel, ort) VALUES (?, ?, ?, ?, ?, ?)",
                        [(a["id"], t["beginn"], t["ende"], 1 if t["ganztags"] else 0, t["titel"], t["ort"]) for t in liste])
        con.execute("UPDATE kalender_abo SET versuch = ?, stand = ?, fehler = NULL, anzahl = ? WHERE id = ?",
                    (jetzt, jetzt, len(liste), a["id"]))
        if art == "schule":
            _ferien_uebernehmen(con, ferien_aus(liste, db.einstellung(con, "schulkalender_stichwoerter", STICHWOERTER)))
    return abo_status(con, art, lehrkraft_id)


def faellige_abrufen(con, laden=herunterladen):
    """Fuer den Takt des Servers: alle Abos, deren letzter Versuch mehr als 30 Minuten her ist."""
    grenze = (datetime.datetime.fromisoformat(db.jetzt()) - ABRUF_ALLE).isoformat()
    neu = 0
    for a in con.execute("SELECT * FROM kalender_abo WHERE versuch IS NULL OR versuch < ?", (grenze,)).fetchall():
        status = abrufen(con, a["art"], a["lehrkraft_id"], laden)
        neu += 0 if status["fehler"] else 1
    return neu
