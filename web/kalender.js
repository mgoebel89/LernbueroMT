// Kalender der Lehrkraft (Stufe F): Woche, Monat oder Halbjahr, immer als Wochenzeilen (KW) mit Montag bis Freitag;
// Samstag und Sonntag erscheinen nur, wenn dort etwas steht. Ebenen einzeln ein- und ausblendbar (merkt sich der Browser).
// Der Dienstkalender kommt als iCal-Abo aus Outlook (nur lesen, nur für die Lehrkraft selbst), wie im TrackingDRS.
'use strict';
const Kalender = (() => {
  const el = L.el;
  const EBENEN = [['dienst', 'Dienstkalender'], ['unterricht', 'Unterrichtstage'], ['sprech', 'Sprechzeiten'], ['pruefung', 'Prüfungszeiten'],
    ['frist', 'Fristen'], ['gn', 'Gelingensnachweise'], ['ferien', 'Ferien, Ausfall']];
  const ANSICHTEN = [['woche', 'Woche'], ['monat', 'Monat'], ['halbjahr', 'Halbjahr']];
  const WOCHENTAGE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];
  const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  const SPEICHER = 'lbmt-kalender';
  let Z = null;

  function laden() {
    let z = {};
    try { z = JSON.parse(localStorage.getItem(SPEICHER) || '{}') || {}; } catch (e) { z = {}; }
    return { ansicht: ['woche', 'monat', 'halbjahr'].includes(z.ansicht) ? z.ansicht : 'halbjahr', klasse: z.klasse || '',
      aus: Array.isArray(z.aus) ? z.aus : [], datum: L.heute() };
  }
  function merken() {
    try { localStorage.setItem(SPEICHER, JSON.stringify({ ansicht: Z.ansicht, klasse: Z.klasse, aus: Z.aus })); } catch (e) { /* privat */ }
  }

  const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  const datum = s => new Date(s.slice(0, 10) + 'T12:00:00');
  const plus = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const montag = d => plus(d, -((d.getDay() + 6) % 7));
  function kw(d) {   // ISO-Kalenderwoche
    const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const t = x.getUTCDay() || 7;
    x.setUTCDate(x.getUTCDate() + 4 - t);
    return Math.ceil(((x - Date.UTC(x.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7);
  }
  function halbjahr(d) {   // 1. August bis 31. Januar, 1. Februar bis 31. Juli
    const m = d.getMonth(), j = d.getFullYear();
    if (m >= 7) return { von: new Date(j, 7, 1, 12), bis: new Date(j + 1, 0, 31, 12), name: '1. Halbjahr ' + j + '/' + String(j + 1).slice(2) };
    if (m === 0) return { von: new Date(j - 1, 7, 1, 12), bis: new Date(j, 0, 31, 12), name: '1. Halbjahr ' + (j - 1) + '/' + String(j).slice(2) };
    return { von: new Date(j, 1, 1, 12), bis: new Date(j, 6, 31, 12), name: '2. Halbjahr ' + (j - 1) + '/' + String(j).slice(2) };
  }
  function bereich() {
    const a = datum(Z.datum);
    if (Z.ansicht === 'woche') { const v = montag(a); return { von: v, bis: plus(v, 6), titel: 'KW ' + kw(v) + ' · ' + L.tag(iso(v)) + ' bis ' + L.tag(iso(plus(v, 6)), true) }; }
    if (Z.ansicht === 'monat') {
      const erster = new Date(a.getFullYear(), a.getMonth(), 1, 12), letzter = new Date(a.getFullYear(), a.getMonth() + 1, 0, 12);
      return { von: montag(erster), bis: plus(montag(letzter), 6), titel: MONATE[a.getMonth()] + ' ' + a.getFullYear(), monat: a.getMonth() };
    }
    const h = halbjahr(a);
    const start = plus(h.von, h.von.getDay() === 6 ? 2 : h.von.getDay() === 0 ? 1 : 0);   // beginnt das Halbjahr am Wochenende: ab Montag
    return { von: montag(start), bis: plus(montag(h.bis), 6), titel: h.name, hj: h };
  }
  function blaettern(richtung) {
    const a = datum(Z.datum);
    if (Z.ansicht === 'woche') Z.datum = iso(plus(a, 7 * richtung));
    else if (Z.ansicht === 'monat') Z.datum = iso(new Date(a.getFullYear(), a.getMonth() + richtung, 1, 12));
    else Z.datum = iso(new Date(a.getFullYear(), a.getMonth() + 6 * richtung, 1, 12));
    seite();
  }

  async function seite() {
    if (!Z) Z = laden();
    document.getElementById('unter').textContent = 'Kalender';
    L.titel('Kalender');
    const b = bereich();
    const d = await L.api('GET', '/api/kalender?von=' + iso(b.von) + '&bis=' + iso(b.bis) + (Z.klasse ? '&klasse=' + Z.klasse : ''));
    if (Z.klasse && !d.alle_klassen.some(k => String(k.id) === String(Z.klasse))) { Z.klasse = ''; merken(); return seite(); }
    const inhalt = document.getElementById('inhalt');
    const klasse = el('select', { 'aria-label': 'Klasse', onchange: ev => { Z.klasse = ev.target.value; merken(); seite(); } },
      el('option', { value: '', text: 'alle meine Klassen' }));
    d.alle_klassen.forEach(k => klasse.appendChild(el('option', { value: k.id, text: k.name })));
    klasse.value = Z.klasse;
    const schalter = el('div', { class: 'schalter', role: 'group', 'aria-label': 'Ansicht' }, ANSICHTEN.map(([a, t]) => el('button', {
      type: 'button', class: Z.ansicht === a ? 'an' : null, 'aria-pressed': Z.ansicht === a ? 'true' : 'false', text: t,
      onclick: () => { Z.ansicht = a; merken(); seite(); } })));
    const navi = el('div', { class: 'kal-navi' },
      el('button', { type: 'button', class: 'leicht', 'aria-label': 'zurück', onclick: () => blaettern(-1) }, L.symbol('links')),
      el('b', { text: b.titel }),
      el('button', { type: 'button', class: 'leicht', 'aria-label': 'weiter', onclick: () => blaettern(1) }, L.symbol('rechts')),
      el('button', { type: 'button', class: 'klein', text: 'heute', onclick: () => { Z.datum = L.heute(); seite(); } }));
    const ebenen = el('div', { class: 'kal-ebenen' }, EBENEN.map(([e, t]) => el('button', {
      type: 'button', class: 'fchip' + (Z.aus.includes(e) ? ' aus' : ''), 'aria-pressed': Z.aus.includes(e) ? 'false' : 'true',
      title: Z.aus.includes(e) ? 'einblenden' : 'ausblenden',
      onclick: () => { Z.aus = Z.aus.includes(e) ? Z.aus.filter(x => x !== e) : Z.aus.concat([e]); merken(); seite(); } },
    el('i', { class: 'f-' + e }), t)));
    const dienst = d.dienst;
    const dienstText = !dienst ? 'Dienstkalender nicht verbunden' : dienst.fehler ? 'Dienstkalender: Fehler beim Abruf'
      : 'Dienstkalender abgerufen ' + (dienst.stand ? L.wann(dienst.stand) : '–') + ' · nur lesen';
    L.setzen(inhalt,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Kalender' }), schalter, d.alle_klassen.length > 1 ? klasse : null,
        el('button', { type: 'button', class: 'klein' + (dienst && dienst.fehler ? ' warnen' : ''), onclick: () => dienstDialog(d) }, L.symbol('kalender'), dienstText)),
      el('div', { class: 'karte stapel' }, el('div', { class: 'zeile kal-kopf' }, navi, ebenen), tabelle(d, b),
        el('p', { class: 'leise klein', text: 'Ihr Dienstkalender kommt als iCal-Abo aus Outlook, wie im TrackingDRS. Lernbüro MT liest ihn nur, sieht ihn nur für Sie und schreibt nichts nach Outlook zurück. Termine mit Uhrzeit sperren die Plätze Ihrer Sprech- und Prüfungszeiten. Sprech- und Prüfungszeiten zeigen „gebucht/Plätze“.' })));
  }

  function tabelle(d, b) {
    const zeige = e => !Z.aus.includes(e.ebene);
    const je = {};
    d.eintraege.filter(zeige).forEach(e => { (je[e.datum] = je[e.datum] || []).push(e); });
    const tage = d.tage || {};
    const wochenende = [5, 6].filter(i => { for (let w = montag(b.von); w <= b.bis; w = plus(w, 7)) { if (je[iso(plus(w, i))]) return true; } return false; });
    const spalten = [0, 1, 2, 3, 4].concat(wochenende);
    const heute = L.heute();
    const woche = Z.ansicht === 'woche';
    const kopf = el('tr', {}, el('th', { class: 'kw', text: 'KW' }), spalten.map(i => el('th', { text: woche ? WOCHENTAGE[i].slice(0, 2) + ' ' + L.tag(iso(plus(b.von, i))).slice(3) : WOCHENTAGE[i] })));
    const zeilen = [];
    let letzterMonat = null;
    for (let w = new Date(b.von); w <= b.bis; w = plus(w, 7)) {
      const m = plus(w, 3).getMonth();   // der Donnerstag bestimmt den Monat der Woche
      if (Z.ansicht === 'halbjahr' && m !== letzterMonat) {
        zeilen.push(el('tr', { class: 'kal-monat' }, el('td', { colspan: spalten.length + 1, text: MONATE[m] + ' ' + plus(w, 3).getFullYear() })));
        letzterMonat = m;
      }
      zeilen.push(el('tr', {}, el('td', { class: 'kw', text: 'KW ' + kw(w) }), spalten.map(i => {
        const tag = iso(plus(w, i));
        const t = tage[tag] || { unterricht: [], ferien: null };
        const ut = t.unterricht.length && !Z.aus.includes('unterricht');
        const fer = t.ferien && !Z.aus.includes('ferien');
        const ausser = b.monat !== undefined && plus(w, i).getMonth() !== b.monat;
        const ausserHj = b.hj && (plus(w, i) < b.hj.von || plus(w, i) > b.hj.bis);
        const lernbuero = ut ? ' · ' + (t.unterricht.length > 1 || (d.klassen.length > 1 && !Z.klasse) ? t.unterricht.map(u => u.klasse).join(', ') : 'Lernbüro') : '';
        return el('td', { class: ['t', ut ? 'ut' : '', fer ? 'fer' : '', tag === heute ? 'heute' : '', ausser || ausserHj ? 'ausser' : ''].join(' ').replace(/\s+/g, ' ').trim(),
          title: ut ? t.unterricht.map(u => u.klasse + ' ' + u.von + '–' + u.bis + (u.ohne ? ' (ohne Lehrkraft)' : '')).join('\n') : null },
        el('span', { class: 'tagnr', text: tag.slice(8, 10) + '.' + tag.slice(5, 7) + '.' + lernbuero }),
        (je[tag] || []).map(e => el('span', { class: 'ev ' + art(e), title: e.titel + (e.details.length ? '\n' + e.details.join('\n') : '') }, e.text,
          woche && e.details.length ? el('span', { class: 'ev-details' }, e.details.map(x => el('span', { text: x }))) : null)));
      })));
    }
    return el('div', { class: 'rollbar' }, el('table', { class: 'kal' + (woche ? ' woche' : '') + (Z.ansicht === 'halbjahr' ? ' halbjahr' : '') },
      el('thead', {}, kopf), el('tbody', {}, zeilen)));
  }

  function art(e) {
    return { dienst: 'dienst', frist: 'fst', gn: 'gn', aus: 'aus', ohne: 'ohne', info: 'info', sprech: 'sz', pruefung: 'sz n' }[e.art] || '';
  }

  async function dienstDialog(d) {
    const s = d.dienst;
    const url = el('input', { type: 'url', placeholder: 'https://outlook.office365.com/owa/calendar/…/calendar.ics', autocomplete: 'off' });
    const stand = s ? el('div', { class: 'banner' + (s.fehler ? ' warnung' : '') },
      el('b', { text: s.adresse }), ' · ', s.stand ? 'zuletzt abgerufen ' + L.wann(s.stand) + ', ' + s.anzahl + ' Termine' : 'noch nicht abgerufen',
      s.fehler ? el('div', { text: 'Fehler beim letzten Versuch: ' + s.fehler }) : null) : null;
    const ok = await L.dialog({
      titel: 'Dienstkalender', knopf: s ? 'Adresse ändern' : 'Verbinden', breit: true,
      inhalt: el('div', { class: 'stapel' },
        el('p', { class: 'leise', text: 'In Outlook im Web: Einstellungen → Kalender → Freigegebene Kalender → „Kalender veröffentlichen“, Kalender wählen, „Alle Details anzeigen“, veröffentlichen und den ICS-Link kopieren. Lernbüro MT holt ihn alle 30 Minuten und liest nur.' }),
        d.pakete_da ? null : el('div', { class: 'banner warnung', text: 'Im Container fehlen noch die Pakete für Kalender-Abos. Ein Update installiert sie.' }),
        stand, L.feld(s ? 'Neue Adresse (ICS-Link)' : 'Adresse (ICS-Link)', url, 'Der Link ist geheim: wer ihn hat, sieht Ihren Kalender. Gespeichert wird er nur im Container.'),
        s ? el('div', { class: 'zeile' },
          L.nebenknopf('Jetzt abrufen', async () => { try { await L.api('POST', '/api/kalender/dienst', { abrufen: true }); seite(); } catch (e) { L.meldung(e.message, true); } }, 'klein'),
          L.nebenknopf('Verbindung entfernen …', async () => {
            const weg = await L.dialog({ titel: 'Dienstkalender entfernen?', knopf: 'Entfernen', gefaehrlich: true,
              inhalt: el('p', { text: 'Die Termine verschwinden aus dem Lernbüro und sperren keine Plätze mehr. In Outlook ändert sich nichts.' }),
              speichern: () => L.api('POST', '/api/kalender/dienst/entfernen', {}) });
            if (weg) seite();
          })) : null),
      speichern: async () => {
        if (!url.value.trim()) throw new Error('Bitte den ICS-Link einfügen.');
        const r = await L.api('POST', '/api/kalender/dienst', { url: url.value.trim() });
        if (r.dienst && r.dienst.fehler) throw new Error(r.dienst.fehler);
        return r;
      },
    });
    if (ok) { L.meldung('Dienstkalender verbunden: ' + ok.dienst.anzahl + ' Termine.'); seite(); }
  }

  return { seite };
})();
