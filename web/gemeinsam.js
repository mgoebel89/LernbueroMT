// Gemeinsame Hilfen fuer alle Seiten (Bauweise wie im TrackingDRS): Schnittstelle, DOM-Bau ohne innerHTML, Meldungen,
// Overlays (jede Entscheidung in einem Fenster: am PC in der Mitte, am Handy als Blatt von unten), Symbole.
'use strict';

const L = {
  NAME: 'Lernbüro MT',

  async api(methode, url, daten) {
    const kopf = { 'X-Lernbuero': '1' };
    if (daten !== undefined) kopf['Content-Type'] = 'application/json';
    let antwort;
    try {
      antwort = await fetch(url, { method: methode, headers: kopf, credentials: 'same-origin',
        body: daten !== undefined ? JSON.stringify(daten) : undefined });
    } catch (e) {
      throw new Error('Keine Verbindung zum Server.');
    }
    let inhalt = {};
    try { inhalt = await antwort.json(); } catch (e) { /* leer */ }
    if (!antwort.ok) {
      const f = new Error(inhalt.fehler || 'Fehler ' + antwort.status);
      f.status = antwort.status;
      throw f;
    }
    return inhalt;
  },

  // el('div', {class: 'karte', onclick: fn}, 'Text', kindElement, [weitere])
  el(tag, attribute, ...kinder) {
    const e = document.createElement(tag);
    for (const [name, wert] of Object.entries(attribute || {})) {
      if (wert === null || wert === undefined || wert === false) continue;
      if (name.startsWith('on')) e.addEventListener(name.slice(2), wert);
      else if (name === 'class') e.className = wert;
      else if (name === 'text') e.textContent = wert;
      else if (name === 'value') e.value = wert;
      else if (name === 'checked') e.checked = true;
      else e.setAttribute(name, wert === true ? '' : wert);
    }
    const anhaengen = k => {
      if (k === null || k === undefined || k === false) return;
      if (Array.isArray(k)) k.forEach(anhaengen);
      else e.appendChild(typeof k === 'string' || typeof k === 'number' ? document.createTextNode(String(k)) : k);
    };
    kinder.forEach(anhaengen);
    return e;
  },

  leeren(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; },

  setzen(e, ...kinder) {
    L.leeren(e);
    kinder.flat(Infinity).forEach(k => { if (k !== null && k !== undefined && k !== false) e.append(k); });
    return e;
  },

  meldung(text, fehler) {
    let ort = document.getElementById('meldungen');
    if (!ort) { ort = L.el('div', { id: 'meldungen', 'aria-live': 'polite' }); document.body.appendChild(ort); }
    const m = L.el('div', { class: 'meldung' + (fehler ? ' fehler' : ''), text });
    ort.appendChild(m);
    setTimeout(() => m.remove(), fehler ? 7000 : 3500);
  },

  titel(text) { document.title = text ? text + ' · ' + L.NAME : L.NAME; },

  // Strichsymbole im 24er Raster (Lucide-Formen, ISC-Lizenz)
  SYMBOLE: {
    plan: 'M3 3v18h18M7 5h8v3.5H7zM10 10.5h9V14h-9zM7 16h5v2.5H7z',
    heute: 'M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41',
    kann: 'M3 17l2 2 4-4M3 7l2 2 4-4M13 6h8M13 12h8M13 18h8',
    rueck: 'M7.9 20A9 9 0 1 0 4 16.1L2 22Z',
    gn: 'M12 2a6 6 0 1 0 0 12a6 6 0 1 0 0-12M15.48 12.89 17 22l-5-3-5 3 1.52-9.11',
    hilfe: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01',
    uebersicht: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
    klassen: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8a4 4 0 1 0 0-8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
    archiv: 'M3 4h18v5H3zM5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4',
    lehrkraefte: 'M12 2a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4 21c1-4 4.2-6 8-6s7 2 8 6M17 11l2 2 4-4',
    einstellungen: 'M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
    konto: 'M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4 21c1-4 4.2-6 8-6s7 2 8 6',
    hoch: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
    laden: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
    plus: 'M12 5v14M5 12h14',
    qr: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h3v3h-3zM20 14v.01M14 20h.01M17 17h4v4h-4z',
    auge: 'M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7ZM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6',
    pakete: 'M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z',
    kalender: 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM16 2v4M8 2v4M3 10h18',
    hoch_pfeil: 'M12 19V5M5 12l7-7 7 7',
    runter_pfeil: 'M12 5v14M19 12l-7 7-7-7',
    extern: 'M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
    kopie: 'M8 8h12v12H8zM16 8V4H4v12h4',
    haken: 'M20 6 9 17l-5-5',
    uhr: 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M12 6v6l4 2',
    pruefen: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z',
    mikro: 'M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v3',
    stern: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z',
    zu: 'M18 6 6 18M6 6l12 12',
  },

  // Einschaetzung in 4 Stufen: gespeichert wird immer 1 bis 4, die Klasse zeigt Smileys oder Zahlen
  STUFEN: [['😟', 'muss viel üben', 'Ich muss noch viel üben'], ['😐', 'brauche Hilfe', 'Ich brauche noch Hilfe'],
    ['🙂', 'meist allein', 'Ich kann es meistens allein'], ['😀', 'kann es perfekt', 'Ich kann es perfekt']],
  stufeText(wert, zahlen) {
    if (!wert) return '–';
    const s = L.STUFEN[wert - 1];
    return (zahlen ? String(wert) : s[0]) + ' ' + s[1];
  },
  // Vier Knoepfe; aendern(stufe) bei Klick. Ohne aendern nur Anzeige.
  skala(wert, aendern, zahlen) {
    let ort;
    const neu = w => L.el('div', { class: 'skala' }, L.STUFEN.map(([smiley, text], i) => L.el('button', {
      type: 'button', class: w === i + 1 ? 'an' : null, disabled: !aendern,
      onclick: () => { aendern(i + 1); const n = neu(i + 1); ort.replaceWith(n); ort = n; } },
    L.el('b', { text: zahlen ? String(i + 1) : smiley }), text)));
    ort = neu(wert);
    return ort;
  },

  symbol(name) {
    const ns = 'http://www.w3.org/2000/svg';
    const s = document.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('class', 'symbol');
    const p = document.createElementNS(ns, 'path');
    p.setAttribute('d', L.SYMBOLE[name]);
    s.appendChild(p);
    return s;
  },

  // Overlay mit einer Frage. inhalt: Element(e); speichern(form) darf einen Fehler werfen: er erscheint im Fenster.
  // Rueckgabe: Promise mit dem Ergebnis von speichern() oder null bei Abbrechen.
  // weitere: [{ text, speichern(form) }] zusaetzliche Knoepfe vor dem Hauptknopf (z. B. "Entwurf speichern")
  dialog({ titel, inhalt, knopf = 'Speichern', abbrechen = 'Abbrechen', speichern, gefaehrlich = false, breit = false, weitere = [], fuss = null }) {
    return new Promise(fertig => {
      const fehler = L.el('div', { class: 'fehlertext', role: 'alert' });
      const ok = knopf ? L.el('button', { type: 'submit', class: gefaehrlich ? 'warnen' : 'haupt', text: knopf }) : null;
      const alle = [];
      const ausfuehren = async (funktion, knopfEl) => {
        fehler.textContent = '';
        alle.forEach(b => { b.disabled = true; });
        try { schliessen(funktion ? await funktion(form) : true); }
        catch (e) { fehler.textContent = e.message; alle.forEach(b => { b.disabled = false; }); }
      };
      const extra = weitere.map(w => L.el('button', { type: 'button', text: w.text, class: w.klasse || null, onclick: ev => ausfuehren(w.speichern, ev.currentTarget) }));
      const form = L.el('form', { method: 'dialog' },
        L.el('h2', { class: 'dreieck', text: titel }), inhalt, fehler,
        L.el('div', { class: 'knoepfe' + (extra.length ? ' mehr' : '') }, fuss ? L.el('span', { class: 'fuss leise klein' }, fuss) : null,
          abbrechen ? L.el('button', { type: 'button', text: abbrechen, onclick: () => schliessen(null) }) : null, extra, ok));
      alle.push(...extra);
      if (ok) alle.push(ok);
      const d = L.el('dialog', { class: breit ? 'breit' : null }, form);
      const schliessen = wert => { d.close(); d.remove(); fertig(wert); };
      d.addEventListener('cancel', ev => { ev.preventDefault(); schliessen(null); });
      form.addEventListener('submit', ev => { ev.preventDefault(); ausfuehren(speichern, ok); });
      document.body.appendChild(d);
      d.showModal();
      const erstes = form.querySelector('input:not([type=hidden]):not([readonly]), select, textarea');
      // ohne Eingabefeld der Hauptknopf: sonst waehlt die Eingabetaste den ersten Knopf einer Skala aus
      if (erstes) erstes.focus(); else if (ok) ok.focus();
    });
  },

  TAGE: ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'],
  // '2026-11-05' -> 'Do 05.11.'; mit jahr -> 'Do 05.11.2026'
  tag(iso, jahr) {
    if (!iso) return '';
    const d = new Date(iso.slice(0, 10) + 'T12:00:00');
    return L.TAGE[d.getDay()] + ' ' + iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + (jahr ? iso.slice(0, 4) : '');
  },
  uhr(zeit) { return zeit ? zeit.slice(11, 16) : ''; },
  // '2026-11-05T09:12:00' -> 'heute 09:12' / 'Do 05.11. 09:12'
  wann(zeit) {
    if (!zeit) return '';
    return (zeit.slice(0, 10) === L.heute() ? 'heute' : L.tag(zeit)) + ' ' + zeit.slice(11, 16);
  },
  heute() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  },

  // Knopf in einem Overlay, der das Overlay schliesst und danach etwas anderes tut (z. B. "Entfernen …" mit Rueckfrage)
  nebenknopf(text, aktion, klasse = 'warnen klein') {
    const k = L.el('button', { type: 'button', class: klasse, text, onclick: () => {
      k.closest('dialog').dispatchEvent(new Event('cancel'));
      setTimeout(aktion, 0);
    } });
    return k;
  },

  feld(beschriftung, eingabe, hilfe) {
    return L.el('label', { class: 'feld' }, beschriftung, eingabe, hilfe ? L.el('span', { class: 'hilfe', text: hilfe }) : null);
  },

  async herunterladen(url) {
    // ueber fetch, damit Fehler (z. B. keine Schueler) als Meldung erscheinen statt als leere Seite
    const antwort = await fetch(url, { credentials: 'same-origin' });
    if (!antwort.ok) {
      let text = 'Fehler ' + antwort.status;
      try { text = (await antwort.json()).fehler || text; } catch (e) { /* leer */ }
      throw new Error(text);
    }
    const name = decodeURIComponent(((antwort.headers.get('Content-Disposition') || '').match(/filename\*=UTF-8''(.+)$/) || [])[1] || 'datei');
    const blob = await antwort.blob();
    const a = L.el('a', { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  },
};
