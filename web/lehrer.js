// Lehrerbereich, Stufe A: Klassen mit Team und Einsicht, Schueler, Moodle-Teilnehmerliste (Assistent), QR-Karten,
// Lehrkraefte (Admin), Einstellungen mit Update und Sicherung, eigenes Konto. Jede Entscheidung laeuft ueber ein Overlay.
// Stufe C: Klassenmatrix, Schuelerplan. Stufe D: "Jetzt" (Hilfe-Reihe, Termine heute, Zu pruefen), Rueckmeldungen und
// Empfehlungen (rueck.js), Sprech- und Pruefungszeiten (zeitfenster.js). Stufe E: Bereit-Liste der Gelingensnachweise,
// "in Moodle freigeschaltet", Ergebnis ueber das Rueckmeldungsfenster, Reiter "Gelingensnachweise" auf der Schuelerseite.
'use strict';
const { el } = L;
const S = { konto: null, lehrkraefte: null, update: null, zu_pruefen: 0, nachweise: 0 };
const inhalt = document.getElementById('inhalt');
const NAV = [
  { a: 'uebersicht', text: 'Übersicht', s: 'uebersicht' },
  { a: 'pruefen', text: 'Zu prüfen', s: 'pruefen' },
  { a: 'nachweise', text: 'Nachweise', s: 'gn' },
  { a: 'zeitfenster', text: 'Zeitfenster', s: 'uhr' },
  { a: 'klassen', text: 'Klassen', s: 'klassen' },
  { a: 'pakete', text: 'Pakete', s: 'pakete' },
  { a: 'archiv', text: 'Archiv', s: 'archiv' },
  { a: 'lehrkraefte', text: 'Lehrkräfte', s: 'lehrkraefte', admin: true },
  { a: 'einstellungen', text: 'Einstellungen', s: 'einstellungen', admin: true },
  { a: 'konto', text: 'Mein Konto', s: 'konto' },
];
const AKTION = {
  behalten: ['blau', 'behalten'], reaktivieren: ['gruen', 'wieder aktiv'], neu: ['gruen', 'anlegen'],
  lehrkraft: ['', 'überspringen'], doppelt: ['', 'doppelt'], fehlt: ['gelb', 'nicht mehr in Moodle'],
};

function titelSetzen(text) {
  document.getElementById('unter').textContent = text;
  L.titel(text);
}

function fehlerZeigen(e) {
  if (e.status === 401) { location.replace('/anmelden'); return; }
  L.setzen(inhalt, el('div', { class: 'leer', text: e.message }));
}

function passwortVorschlag() {
  const zeichen = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  return Array.from(crypto.getRandomValues(new Uint32Array(10)), z => zeichen[z % zeichen.length]).join('');
}

async function lehrkraefte(neu) {
  if (!S.lehrkraefte || neu) S.lehrkraefte = (await L.api('GET', '/api/lehrkraefte')).lehrkraefte;
  return S.lehrkraefte;
}

function rolleChip(rolle) {
  return { team: el('span', { class: 'chip blau', text: 'Team' }), einsicht: el('span', { class: 'chip' }, L.symbol('auge'), 'Einsicht'),
    admin: el('span', { class: 'chip gelb', text: 'Admin' }) }[rolle] || null;
}

// --- Start und Navigation ---

async function start() {
  try {
    const ich = await L.api('GET', '/api/ich');
    S.konto = ich.konto;
    S.update = ich.update;
    S.zu_pruefen = ich.zu_pruefen || 0;
    S.nachweise = ich.nachweise || 0;
  } catch (e) {
    if (e.status === 401) { location.replace('/anmelden'); return; }
    fehlerZeigen(e);
    return;
  }
  document.getElementById('wer').textContent = S.konto.name + ' · ' + S.konto.kuerzel.toUpperCase();
  L.setzen(document.getElementById('navigation'), NAV.filter(n => !n.admin || S.konto.rolle === 'admin').map(n =>
    el('a', { href: '#' + n.a, 'data-ansicht': n.a }, L.symbol(n.s), n.text,
      n.a === 'einstellungen' && S.update ? el('span', { class: 'chip gelb klein', text: 'Update' }) : null,
      n.a === 'pruefen' ? el('span', { class: 'chip rot klein nav-zahl', hidden: !S.zu_pruefen, text: String(S.zu_pruefen) }) : null,
      n.a === 'nachweise' ? el('span', { class: 'chip lila klein nav-zahl-gn', hidden: !S.nachweise, text: String(S.nachweise) }) : null)));
  document.getElementById('abmelden').addEventListener('click', async () => {
    try { await L.api('POST', '/api/abmelden', {}); } finally { location.href = '/anmelden'; }
  });
  if (S.konto.pw_vorlaeufig) await passwortPflicht();
  window.addEventListener('hashchange', zeigen);
  zeigen();
  // "Jetzt" live: Hilfe-Reihe, Termine und Eingang alle 10 Sekunden, solange kein Overlay offen ist
  setInterval(async () => {
    if (document.hidden || document.querySelector('dialog')) return;
    const ort = document.getElementById('jetzt');
    try {
      const j = await L.api('GET', '/api/jetzt');
      navZahl(j.eingang.length, j.bereit.length);
      if (ort && document.body.contains(ort)) ort.replaceWith(jetztKarte(j));
    } catch (e) { if (e.status === 401) location.replace('/anmelden'); }
  }, 10000);
}

function navZahl(n, gn) {
  S.zu_pruefen = n;
  const c = document.querySelector('nav.seite .nav-zahl');
  if (c) { c.textContent = String(n); c.hidden = !n; }
  if (gn === undefined) return;
  S.nachweise = gn;
  const g = document.querySelector('nav.seite .nav-zahl-gn');
  if (g) { g.textContent = String(gn); g.hidden = !gn; }
}

async function zeigen() {
  const [ansicht, id, id2] = (location.hash.slice(1) || 'uebersicht').split('/');
  const nav = ansicht === 'klasse' ? 'klassen' : ansicht === 'paket' ? 'pakete' : ansicht === 'schueler' ? 'uebersicht' : ansicht;
  const [, , , reiter] = (location.hash.slice(1) || '').split('/');
  document.querySelectorAll('nav.seite a').forEach(a => a.classList.toggle('an', a.dataset.ansicht === nav));
  try {
    if (ansicht === 'uebersicht') await uebersichtZeigen(Number(id) || null, Number(id2) || null);
    else if (ansicht === 'schueler') await schuelerZeigen(Number(id), Number(id2), reiter || 'plan');
    else if (ansicht === 'pruefen') await pruefenZeigen();
    else if (ansicht === 'nachweise') await nachweiseZeigen();
    else if (ansicht === 'zeitfenster') await Zeiten.seite(Number(id) || null);
    else if (ansicht === 'pakete') await Pakete.uebersicht(Number(id) || null);
    else if (ansicht === 'paket') await Pakete.editor(Number(id));
    else if (ansicht === 'klassen') await klassenZeigen(false);
    else if (ansicht === 'archiv') await klassenZeigen(true);
    else if (ansicht === 'klasse') await klasseZeigen(Number(id));
    else if (ansicht === 'lehrkraefte') await lehrkraefteZeigen();
    else if (ansicht === 'einstellungen') await einstellungenZeigen();
    else if (ansicht === 'konto') kontoZeigen();
    else location.hash = 'uebersicht';
  } catch (e) { fehlerZeigen(e); }
}

async function passwortPflicht() {
  const neu = el('input', { type: 'password', autocomplete: 'new-password', minlength: 8, required: true });
  const alt = el('input', { type: 'password', autocomplete: 'current-password', required: true });
  await L.dialog({
    titel: 'Eigenes Passwort festlegen', abbrechen: null, knopf: 'Passwort speichern',
    inhalt: el('div', { class: 'felder' }, el('p', { class: 'leise', text: 'Ihr Konto hat ein vorläufiges Passwort. Bitte legen Sie jetzt ein eigenes fest.' }),
      L.feld('Vorläufiges Passwort', alt), L.feld('Neues Passwort', neu, 'mindestens 8 Zeichen')),
    speichern: async () => { S.konto = (await L.api('POST', '/api/passwort', { alt: alt.value, neu: neu.value })).konto; },
  });
}

// --- Uebersicht: links "Jetzt", rechts die Klassenmatrix ---

const MZ = { offen: '–', geplant: '▭', arbeit: '◐', fertig: '!', angenommen: '✓', ueberarbeiten: '↺' };
const MZ_TEXT = { offen: 'offen', geplant: 'geplant', arbeit: 'in Arbeit', fertig: 'fertig gemeldet', angenommen: 'angenommen', ueberarbeiten: 'überarbeiten' };

function seit(zeit) {
  const m = Math.max(0, Math.round((Date.now() - new Date(zeit).getTime()) / 60000));
  return m < 1 ? 'gerade eben' : m < 60 ? 'seit ' + m + ' min' : 'seit ' + L.uhr(zeit);
}

function kannKurz(kann) {
  return kann.filter(k => k.stufe).map(k => k.kuerzel + ' „' + L.STUFEN[k.stufe - 1][1] + '“').join(', ');
}

function jetztKarte(j) {
  const hilfe = el('div', { class: 'karte stapel jetzt-hilfe' + (j.hilfe.length ? ' an' : '') },
    el('div', { class: 'zeile' }, el('b', { class: 'hilfe-zahl', text: String(j.hilfe.length) }), el('h3', { text: 'Hilfe gerade' })),
    j.hilfe.length ? j.hilfe.map((h, i) => el('div', { class: 'jz' }, el('span', { class: 'nr', text: String(i + 1) }),
      el('div', {}, el('b', { text: h.name }), el('div', { class: 'leise klein', text: [h.klasse, h.kuerzel ? h.kuerzel + ' ' + h.titel : '', seit(h.zeit)].filter(Boolean).join(' · ') })),
      h.darf ? el('button', { type: 'button', class: 'klein', onclick: async () => {
        try { await L.api('POST', '/api/hilfe/' + h.id + '/erledigt', {}); const n = await L.api('GET', '/api/jetzt'); document.getElementById('jetzt').replaceWith(jetztKarte(n)); }
        catch (e) { L.meldung(e.message, true); }
      } }, L.symbol('haken'), 'erledigt') : null))
      : el('p', { class: 'leise klein', text: 'Niemand wartet.' }),
    el('p', { class: 'leise klein', text: 'Sehen alle Lehrkräfte der Klasse. „Erledigt“ gilt für alle.' }));
  const termine = el('div', { class: 'karte stapel' }, el('h3', { text: 'Termine heute' }),
    j.termine.length ? j.termine.map(t => el('div', { class: 'jz' }, el('span', { class: 'mono', text: t.beginn }),
      el('div', {}, el('b', { text: (Zeiten.TERMINART[t.art] || t.art) + ' · ' + t.name }), el('div', { class: 'leise klein', text: 'Anlass ' + t.anlass + (t.rueckmeldung ? ' · Rückmeldung freigegeben' : '') })),
      el('button', { type: 'button', class: 'klein', onclick: () => Rueck.oeffnen({ schueler: t.schueler_id, termin: t.id, danach: zeigen }) }, 'öffnen')))
      : el('p', { class: 'leise klein', text: 'Heute keine gebuchten Termine.' }));
  const pruefen = el('div', { class: 'karte stapel' }, el('div', { class: 'zeile' }, el('h3', { text: 'Zu prüfen' }),
    j.eingang.length ? el('span', { class: 'chip rot klein', text: String(j.eingang.length) }) : null,
    j.eingang.length > 5 ? el('a', { class: 'rechts klein', href: '#pruefen', text: 'alle' }) : null),
    j.eingang.length ? j.eingang.slice(0, 5).map(m => eingangZeile(m)) : el('p', { class: 'leise klein', text: 'Nichts fertig gemeldet.' }));
  const bereit = el('div', { class: 'karte stapel' }, el('div', { class: 'zeile' }, el('h3', { text: 'Bereit für Gelingensnachweis' }),
    j.bereit.length ? el('span', { class: 'chip lila klein', text: String(j.bereit.length) }) : null,
    j.bereit.length > 5 ? el('a', { class: 'rechts klein', href: '#nachweise', text: 'alle' }) : null),
    j.bereit.length ? j.bereit.slice(0, 5).map(bereitZeile) : el('p', { class: 'leise klein', text: 'Niemand bereit gemeldet.' }));
  return el('div', { id: 'jetzt', class: 'stapel jetzt' }, hilfe, termine, pruefen, bereit);
}

function bereitStand(b) {
  if (b.termin) return 'Termin ' + L.tag(b.termin.datum) + ' ' + b.termin.beginn;
  if (b.status === 'frei') return 'seit ' + L.wann(b.frei) + ' in Moodle frei ✓';
  return b.art === 'moodle' ? 'bereit seit ' + L.wann(b.bereit) : 'bereit, noch kein Termin';
}

function bereitZeile(b) {
  const freischalten = b.darf && b.art === 'moodle' && b.status === 'bereit';
  return el('div', { class: 'jz' }, el('span', { class: 'mz gn-bereit', text: 'GN' }),
    el('div', {}, el('b', { text: b.name }), el('div', { class: 'leise klein', text: [b.klasse, b.art_text + (b.titel ? ' ' + b.titel : '') + ' · ' + b.paket,
      b.nr > 1 ? b.nr + '. Versuch' : '', bereitStand(b)].filter(Boolean).join(' · ') }),
    b.entwurf_id ? el('span', { class: 'chip gelb klein', text: 'Ihr Entwurf' }) : null),
    freischalten ? el('button', { type: 'button', class: 'klein haupt', onclick: () => freischaltenFragen(b) }, 'in Moodle frei')
      : el('button', { type: 'button', class: 'klein' + (b.darf ? ' haupt' : ''), onclick: () => Rueck.oeffnen({ schueler: b.schueler_id, versuch: b.versuch_id, danach: zeigen }) },
        b.darf ? 'Ergebnis' : 'ansehen'));
}

async function freischaltenFragen(b) {
  const ok = await L.dialog({
    titel: 'Test für ' + b.name + ' freigeschaltet?', knopf: 'In Moodle freigeschaltet',
    inhalt: el('div', { class: 'stapel', style: 'gap:8px' },
      el('p', { text: 'Schalten Sie den Test in Moodle für ' + b.name + ' frei (Benutzerüberschreibung oder Gruppe) und bestätigen Sie das hier. ' + b.name.split(' ')[0] + ' sieht dann „jetzt schreiben“.' }),
      b.moodle_link ? el('a', { class: 'knopf klein', style: 'justify-self:start', href: b.moodle_link, target: '_blank', rel: 'noopener' }, L.symbol('extern'), 'Test in Moodle öffnen') : null),
    speichern: () => L.api('POST', '/api/versuche/' + b.versuch_id + '/frei', { frei: true }),
  });
  if (ok) zeigen();
}

async function nachweiseZeigen() {
  titelSetzen('Nachweise');
  const j = await L.api('GET', '/api/jetzt');
  navZahl(j.eingang.length, j.bereit.length);
  const arten = [['moodle', 'Moodle-Test: in Moodle freischalten, dann Ergebnis'], ['fachgespraech', 'Fachgespräch'], ['praxis', 'Praktische Prüfung']];
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Bereit für Gelingensnachweis' })),
    j.bereit.length ? arten.filter(([a]) => j.bereit.some(b => b.art === a)).map(([a, t]) => el('div', { class: 'karte stapel' }, el('h2', { text: t }),
      j.bereit.filter(b => b.art === a).map(bereitZeile)))
      : el('div', { class: 'leer', text: 'Niemand ist gerade bereit gemeldet.' }),
    el('p', { class: 'leise klein', text: 'Das Ergebnis tragen Sie im Fenster „Rückmeldung“ ein: gelungen oder noch nicht gelungen, wahlweise Punkte oder Note, Text per Diktat, Empfehlungen. Bei „noch nicht“ setzen Sie eine neue Frist, eine Sperre gibt es nicht.' }));
}

function eingangZeile(m) {
  return el('div', { class: 'jz' }, el('span', { class: 'mono kz-blau', text: m.kuerzel }),
    el('div', {}, el('b', { text: m.name }), el('div', { class: 'leise klein', text: [m.klasse, 'fertig ' + L.wann(m.zeit), kannKurz(m.kann)].filter(Boolean).join(' · ') }),
      m.entwurf_id ? el('span', { class: 'chip gelb klein', text: 'Ihr Entwurf' }) : null,
      m.gespraech ? el('span', { class: 'chip blau klein' }, L.symbol('uhr'), 'Gespräch ' + L.tag(m.gespraech.datum) + ' ' + m.gespraech.beginn) : null),
    el('button', { type: 'button', class: 'klein' + (m.darf ? ' haupt' : ''), onclick: () => Rueck.oeffnen({ schueler: m.schueler_id, meldung: m.meldung_id, danach: zeigen }) },
      m.darf ? 'öffnen' : 'ansehen'));
}

async function uebersichtZeigen(kid, pid) {
  titelSetzen('Übersicht');
  const [{ klassen }, j] = await Promise.all([L.api('GET', '/api/klassen'), L.api('GET', '/api/jetzt')]);
  navZahl(j.eingang.length, j.bereit.length);
  const meine = klassen.filter(k => k.rolle === 'team' || k.rolle === 'einsicht');
  if (!meine.length) {
    L.setzen(inhalt, el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Übersicht' })),
      el('div', { class: 'leer' }, 'Noch keine Klasse. ', el('a', { href: '#klassen', text: 'Erste Klasse anlegen' })));
    return;
  }
  const k = meine.find(x => x.id === kid) || meine[0];
  const m = await L.api('GET', '/api/klassen/' + k.id + '/matrix' + (pid ? '?paket=' + pid : ''));
  const tm = m.paket ? await L.api('GET', '/api/klassen/' + k.id + '/teams?paket=' + m.paket.id) : null;
  const kw = el('select', { onchange: ev => { location.hash = 'uebersicht/' + ev.target.value; } }, meine.map(x => el('option', { value: x.id, text: x.name })));
  kw.value = k.id;
  const pw = el('select', { onchange: ev => { location.hash = 'uebersicht/' + k.id + '/' + ev.target.value; } },
    m.pakete.map(p => el('option', { value: p.id, text: p.titel + (p.freigabe ? '' : ' (Entwurf)') })));
  if (m.paket) pw.value = m.paket.id;
  const zelle = (r, c) => {
    if (c.nachweis) {
      const z0 = el('span', { class: 'mz ' + c.status, text: c.text });
      if (!c.versuch_id) return el('td', {}, z0);
      if (['gn-bereit', 'gn-frei', 'gn-termin'].includes(c.status)) {
        return el('td', {}, el('button', { type: 'button', class: 'mz-knopf', title: 'bereit gemeldet: Ergebnis eintragen',
          onclick: () => Rueck.oeffnen({ schueler: r.id, versuch: c.versuch_id, danach: zeigen }) }, z0));
      }
      return el('td', {}, el('a', { class: 'mz-knopf', href: '#schueler/' + k.id + '/' + r.id + '/gn', title: c.status === 'gn-gelungen' ? 'gelungen' : 'noch nicht gelungen' }, z0));
    }
    const inhaltZ = el('span', { class: 'mz ' + c.status + (c.ueber_frist ? ' ueber' : ''), text: c.gruppe ? c.text : MZ[c.status] });
    if (c.status === 'fertig' && c.meldung_id) {
      return el('td', {}, el('button', { type: 'button', class: 'mz-knopf', title: 'fertig gemeldet: Rückmeldung öffnen',
        onclick: () => Rueck.oeffnen({ schueler: r.id, meldung: c.meldung_id, danach: zeigen }) }, inhaltZ));
    }
    if (c.status === 'angenommen' || c.status === 'ueberarbeiten') {
      return el('td', {}, el('a', { class: 'mz-knopf', href: '#schueler/' + k.id + '/' + r.id + '/rueck', title: MZ_TEXT[c.status] }, inhaltZ));
    }
    return el('td', { title: MZ_TEXT[c.status] || null }, inhaltZ);
  };
  const matrix = !m.paket ? el('div', { class: 'leer' }, 'Noch kein Paket für ' + k.name + '. ', el('a', { href: '#pakete/' + k.id, text: 'Paket anlegen' }))
    : el('div', { class: 'karte stapel' },
      el('div', { class: 'zeile' }, el('h3', { text: k.name + ' · ' + m.paket.titel })),
      el('div', { class: 'legende' }, Object.keys(MZ).map(s => el('span', {}, el('i', { class: 'mz ' + s, style: 'min-width:20px;height:16px', text: MZ[s] }), MZ_TEXT[s])),
        el('span', {}, el('i', { class: 'mz fehlt', style: 'min-width:20px;height:16px', text: '?' }), 'Wahl fehlt'),
        el('span', {}, el('i', { class: 'mz geplant ueber', style: 'min-width:20px;height:16px' }), 'Frist überschritten'),
        m.spalten.some(s => s.typ === 'nachweis') ? el('span', {}, el('i', { class: 'mz gn-bereit', style: 'min-width:20px;height:16px', text: 'B' }), 'GN bereit (M = in Moodle frei, T = Termin)') : null),
      el('div', { class: 'rollbar' }, el('table', { class: 'mx' },
        el('thead', {}, el('tr', {}, el('th', { class: 'links', text: 'Schüler' }),
          m.spalten.map(s => el('th', { title: s.titel }, el('span', { class: 'kz' + (s.typ === 'nachweis' ? ' gn' : ''), text: s.kuerzel }),
            s.typ === 'gruppe' ? 'Wahl ' + s.waehlen + '/' + s.anzahl : s.typ === 'nachweis' ? ({ moodle: 'Test', praxis: 'Praxis', fachgespraech: 'Gespräch' }[s.art])
              : (s.titel || '').slice(0, 12))),
          el('th', { text: 'Ampel' }), el('th', { text: 'Emp.' }), el('th', { class: 'links', text: 'Hinweis' }))),
        el('tbody', {}, m.zeilen.map(r => el('tr', {},
          el('td', { class: 'name' }, el('a', { href: '#schueler/' + k.id + '/' + r.id, text: r.name }),
            r.teams && r.teams.length ? el('div', { class: 'leise klein team-name', title: 'Zweierteam' }, L.symbol('klassen'), r.teams.join(' · ')) : null),
          r.zellen.map(c => zelle(r, c)),
          el('td', {}, r.ampel ? el('span', { class: 'ampel a-' + r.ampel }) : el('span', { class: 'ampel a-0' })),
          el('td', { class: 'mono klein', text: r.empfehlungen ? String(r.empfehlungen) : '–' }),
          el('td', { class: 'hin' + (r.hinweis && r.hinweis !== 'noch nichts geplant' ? ' w' : ''), text: r.hinweis || '–' })))))),
      el('p', { class: 'leise klein', text: '„Ampel“ zeigt die schlechteste Ampel der laufenden Aufgaben, „Emp.“ zählt offene Empfehlungen. Ein Klick auf ein „!“ öffnet die Rückmeldung, ein Klick auf den Namen die Schülerseite. Die Seite aktualisiert sich von selbst.' }));
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Übersicht' }), kw, m.pakete.length ? pw : null),
    el('div', { class: 'uebersicht-raster' }, jetztKarte(j), el('div', { class: 'stapel' }, matrix, tm && (tm.teams.length || tm.moeglich.length) ? teamKarte(k, tm) : null)));
}

function teamKarte(k, tm) {
  const status = t => t.status === 'aktiv' ? null : el('span', { class: 'chip gelb klein', text: 'Einladung offen' });
  return el('div', { class: 'karte stapel team-liste' },
    el('div', { class: 'zeile' }, el('h3', { text: 'Zweierteams' }),
      tm.darf && tm.moeglich.length ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => teamBilden(k, tm) }, L.symbol('plus'), 'Team bilden')) : null),
    tm.teams.length ? tm.teams.map(t => el('div', { class: 'jz' },
      el('div', {}, el('b', { text: t.a.name + ' + ' + t.b.name }), ' ', status(t), el('div', { class: 'leise klein', text: t.titel + (t.bestaetigt ? ' · seit ' + L.tag(t.bestaetigt) : '') })),
      tm.darf ? el('button', { type: 'button', class: 'klein warnen', onclick: () => teamAufloesen(t) }, 'auflösen') : null))
      : el('p', { class: 'leise klein', text: 'Noch kein Team. Zu zweit möglich: ' + tm.moeglich.map(x => x.titel).join(', ') + '.' }),
    el('p', { class: 'leise klein', text: 'Gemeinsam: Plan, Fertigmeldung, Rückmeldung. Je Person: Farben, Kann-Liste, Empfehlungen, Gelingensnachweis.' }));
}

async function teamBilden(k, tm) {
  const bereich = el('select', {}, tm.moeglich.map((x, i) => el('option', { value: i, text: x.titel })));
  const wahl = () => el('select', { required: true }, el('option', { value: '', text: 'Schüler wählen …' }), tm.schueler.map(x => el('option', { value: x.id, text: x.name })));
  const a = wahl(), b = wahl();
  const ok = await L.dialog({
    titel: 'Zweierteam bilden', knopf: 'Team bilden',
    inhalt: el('div', { class: 'felder' }, L.feld('Wofür', bereich), el('div', { class: 'felder zwei' }, L.feld('Schüler 1', a), L.feld('Schüler 2', b)),
      el('p', { class: 'leise klein', text: 'Das Team gilt sofort, ohne Bestätigung. Die Pläne der beiden werden für die Teamaufgaben zusammengelegt.' })),
    speichern: () => {
      const m = tm.moeglich[Number(bereich.value)];
      return L.api('POST', '/api/klassen/' + k.id + '/teams', { bereich: m.bereich, bezug_id: m.bezug_id, a_id: Number(a.value), b_id: Number(b.value) });
    },
  });
  if (ok) zeigen();
}

async function teamAufloesen(t) {
  const ok = await L.dialog({ titel: 'Team auflösen?', knopf: 'Auflösen', gefaehrlich: true,
    inhalt: el('p', { text: t.a.name + ' + ' + t.b.name + ' (' + t.titel + '). Beide behalten ihren bisherigen Plan und arbeiten danach einzeln weiter.' }),
    speichern: () => L.api('POST', '/api/teams/' + t.id + '/aufloesen', {}) });
  if (ok) zeigen();
}

// --- Zu pruefen: alle offenen Meldungen und eigene Entwuerfe ---

async function pruefenZeigen() {
  titelSetzen('Zu prüfen');
  const j = await L.api('GET', '/api/jetzt');
  navZahl(j.eingang.length);
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Zu prüfen' })),
    el('div', { class: 'karte stapel' }, el('p', { class: 'leise klein', text: 'Fertig gemeldete Aufgaben aller Ihrer Klassen, älteste zuerst. Nach dem Gespräch öffnen, Rückmeldung schreiben oder diktieren, entscheiden, freigeben.' }),
      j.eingang.length ? j.eingang.map(eingangZeile) : el('p', { class: 'leise', text: 'Nichts fertig gemeldet.' })),
    j.entwuerfe.length ? el('div', { class: 'karte stapel' }, el('h2', { text: 'Ihre Entwürfe' }),
      j.entwuerfe.map(e => el('div', { class: 'jz' }, el('span', { class: 'mono kz-blau', text: e.aufgabe ? e.aufgabe.kuerzel : '–' }),
        el('div', {}, el('b', { text: e.name }), el('div', { class: 'leise klein', text: 'zuletzt ' + L.wann(e.geaendert) })),
        el('button', { type: 'button', class: 'klein', onclick: () => Rueck.oeffnen({ schueler: e.schueler_id, rueckmeldung: e.id, danach: zeigen }) }, 'weiter')))) : null);
}

async function schuelerZeigen(kid, sid, reiter) {
  const [d, r] = await Promise.all([L.api('GET', '/api/klassen/' + kid + '/schueler/' + sid + '/plan'),
    L.api('GET', '/api/klassen/' + kid + '/schueler/' + sid + '/rueckmeldungen')]);
  const name = d.schueler.vorname + ' ' + d.schueler.nachname;
  titelSetzen(name);
  const basis = '#schueler/' + kid + '/' + sid;
  const REITER = [['plan', 'Plan und Verlauf'], ['kann', 'Kann-Liste'], ['rueck', 'Rückmeldungen und Empfehlungen'], ['gn', 'Gelingensnachweise']];
  const teile = [
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: name }),
      r.darf ? el('button', { type: 'button', class: 'haupt', onclick: () => Rueck.oeffnen({ schueler: sid, danach: zeigen }) }, L.symbol('rueck'), 'Rückmeldung schreiben') : null,
      r.darf ? el('button', { type: 'button', onclick: async () => { if (await Rueck.empfehlen(sid, d.schueler.vorname)) zeigen(); } }, L.symbol('stern'), 'Aufgabe empfehlen') : null,
      el('a', { class: 'knopf', href: '#uebersicht/' + kid, text: 'zur Übersicht' })),
    el('nav', { class: 'reiter' }, REITER.map(([a, t]) => el('a', { href: basis + '/' + a, class: a === reiter ? 'an' : null, text: t,
      'aria-current': a === reiter ? 'page' : null })))];
  if (reiter === 'kann') {
    const zahlen = d.einschaetzer === 'zahl';
    teile.push(d.plan.pakete.filter(p => p.kann.length).length ? d.plan.pakete.filter(p => p.kann.length).map(p => el('div', { class: 'karte stapel' },
      el('h2', { text: p.titel }),
      el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
        el('thead', {}, el('tr', {}, ['Kann-Aussage', 'vorher', 'nachher', 'Lehrkraft'].map(t => el('th', { text: t })))),
        el('tbody', {}, p.kann.map(k => el('tr', {}, el('td', {}, el('b', { class: 'mono', text: k.kuerzel + ' ' }), k.text,
          k.aufgaben_kuerzel.length ? el('div', { class: 'leise klein', text: 'erarbeitet in ' + k.aufgaben_kuerzel.join(', ') }) : null),
        el('td', { text: L.stufeText(k.vorher, zahlen) }), el('td', { text: L.stufeText(k.nachher, zahlen) }),
        el('td', { class: k.nachher && k.lehrkraft && Math.abs(k.nachher - k.lehrkraft) >= 2 ? 'abweichung' : null, text: L.stufeText(k.lehrkraft, zahlen) }))))))))
      : el('div', { class: 'leer', text: 'Noch keine Kann-Liste in den freigegebenen Paketen.' }));
  } else if (reiter === 'gn') {
    const g = await L.api('GET', '/api/klassen/' + kid + '/schueler/' + sid + '/nachweise');
    const ergebnis = (n, v) => (v.status === 'gelungen' ? 'gelungen' : 'noch nicht gelungen') +
      (v.punkte !== null && v.punkte !== undefined ? ' · ' + String(v.punkte).replace('.', ',') + (n.max_punkte ? '/' + n.max_punkte : '') + ' Punkte' : v.note ? ' · Note ' + v.note : '');
    teile.push(g.pakete.length ? g.pakete.map(p => el('div', { class: 'karte stapel' }, el('h2', { text: p.titel }),
      p.nachweise.map(n => el('div', { class: 'stapel gn-karte', style: 'gap:6px;padding-left:10px' },
        el('div', { class: 'zeile' }, el('b', { text: n.art_text + (n.titel ? ' · ' + n.titel : '') }),
          el('span', { class: 'leise klein', text: (n.wirksam ? 'Frist ' + L.tag(n.wirksam) + (n.eigene_frist ? ' (neu)' : '') : '') + ' · Kann-Liste ' + n.kann_nachher + '/' + n.kann_gesamt + ' nachher' }),
          el('span', { class: 'rechts' },
            n.aktuell ? el('span', { class: 'chip lila', text: n.aktuell.termin ? 'Termin ' + L.tag(n.aktuell.termin.datum) + ' ' + n.aktuell.termin.beginn
              : n.aktuell.status === 'frei' ? 'in Moodle frei' : 'bereit seit ' + L.wann(n.aktuell.bereit) }) : null,
            n.aktuell && g.darf && n.art === 'moodle' && n.aktuell.status === 'bereit' ? el('button', { type: 'button', class: 'klein', onclick: () => freischaltenFragen({
              versuch_id: n.aktuell.id, name: d.schueler.vorname + ' ' + d.schueler.nachname, moodle_link: n.moodle_link }) }, 'in Moodle frei') : null,
            n.aktuell ? el('button', { type: 'button', class: 'klein' + (g.darf ? ' haupt' : ''), onclick: () => Rueck.oeffnen({ schueler: sid, versuch: n.aktuell.id, danach: zeigen }) },
              g.darf ? 'Ergebnis' : 'ansehen') : null)),
        n.versuche.filter(v => v.status === 'gelungen' || v.status === 'nicht').map(v => el('div', { class: 'versuch ' + v.status },
          el('div', { class: 'zeile' }, el('b', { text: v.nr + '. Versuch' }), el('span', { class: 'sc ' + (v.status === 'gelungen' ? 'angenommen' : 'ueberarbeiten'), text: ergebnis(n, v) }),
            el('span', { class: 'leise klein', text: L.tag(v.ergebnis_zeit) + ' · ' + (v.ergebnis_von || '') + (v.status === 'nicht' && v.neue_frist ? ' · neue Frist ' + L.tag(v.neue_frist) : '') }),
            v.rueckmeldung_id ? el('button', { type: 'button', class: 'klein rechts', onclick: () => Rueck.oeffnen({ schueler: sid, rueckmeldung: v.rueckmeldung_id, danach: zeigen }) }, 'ansehen') : null),
          v.text ? el('p', { class: 'rm-text klein', text: v.text }) : null)),
        !n.versuche.length ? el('p', { class: 'leise klein', text: 'Noch nicht bereit gemeldet.' }) : null))))
      : el('div', { class: 'leer', text: 'In den freigegebenen Paketen gibt es keinen Gelingensnachweis.' }));
  } else if (reiter === 'rueck') {
    teile.push(el('div', { class: 'karte stapel' }, el('h2', { text: 'Empfehlungen' }),
      r.empfehlungen.length ? r.empfehlungen.map(e => el('div', { class: 'emp-zeile' + (e.erledigt ? ' erledigt' : '') },
        el('div', {}, el('b', { text: e.aufgabe ? e.aufgabe.kuerzel + ' ' + e.aufgabe.titel : '' }), ' · ', e.verbindlich ? 'verbindlich bis ' + L.tag(e.wirksam || e.frist) : 'freiwillig',
          el('div', { class: 'leise klein', text: [e.hinweis, 'von ' + e.verfasser + ' am ' + L.tag(e.freigegeben),
            e.erledigt ? 'erledigt ' + L.tag(e.erledigt) : e.eingeplant.length ? 'eingeplant ' + e.eingeplant.map(x => L.tag(x)).join(', ') : 'noch nicht eingeplant'].filter(Boolean).join(' · ') })),
        r.darf ? el('button', { type: 'button', class: 'leicht klein', title: 'Empfehlung entfernen', onclick: async () => {
          const ok = await L.dialog({ titel: 'Empfehlung entfernen?', knopf: 'Entfernen', gefaehrlich: true,
            inhalt: el('p', { text: (e.aufgabe ? e.aufgabe.kuerzel : 'Die Aufgabe') + ' verschwindet aus „Empfohlen“ bei ' + d.schueler.vorname + '.' }),
            speichern: () => L.api('POST', '/api/empfehlungen/' + e.id + '/entfernen', {}) });
          if (ok) zeigen();
        } }, L.symbol('zu')) : null))
        : el('p', { class: 'leise klein', text: 'Noch keine Empfehlung.' })),
    el('div', { class: 'stapel' }, r.rueckmeldungen.length ? r.rueckmeldungen.map(x => el('div', { class: 'karte stapel rm' },
      el('div', { class: 'zeile' }, el('b', { text: x.aufgabe ? x.aufgabe.kuerzel + ' ' + x.aufgabe.titel : x.paket ? 'Paket ' + x.paket : 'Feedback' }),
        x.freigegeben ? el('span', { class: 'leise klein', text: x.verfasser + ' · ' + L.wann(x.freigegeben) + (x.gelesen ? ' · gelesen' : ' · noch nicht gelesen') })
          : el('span', { class: 'chip gelb klein', text: 'Entwurf, nur für Sie' }),
        el('span', { class: 'rechts' }, x.entscheidung ? el('span', { class: 'sc ' + x.entscheidung, text: x.entscheidung === 'angenommen' ? 'angenommen' : 'überarbeiten bis ' + L.tag(x.neue_frist) }) : null,
          el('button', { type: 'button', class: 'klein', onclick: () => Rueck.oeffnen({ schueler: sid, rueckmeldung: x.id, danach: zeigen }) }, x.freigegeben ? 'ansehen' : 'weiter'))),
      x.text ? el('p', { class: 'rm-text', text: x.text }) : null,
      x.empfehlungen.length ? el('div', { class: 'leise klein', text: 'Empfohlen: ' + x.empfehlungen.map(e => (e.aufgabe ? e.aufgabe.kuerzel : '') + (e.verbindlich ? ' (verbindlich)' : '')).join(', ') }) : null))
      : el('div', { class: 'leer', text: 'Noch keine Rückmeldung.' })));
  } else {
    teile.push(d.plan.pakete.length ? Raster.zeichnen(d.plan, { bearbeitbar: false }) : el('div', { class: 'leer', text: 'Noch kein freigegebenes Paket.' }),
      el('div', { class: 'karte stapel' }, el('h2', { text: 'Entscheidungen' }),
        el('p', { class: 'leise klein', text: 'Die letzten Einträge. Vergleich mit früheren Ständen und Kennzahlen kommen mit Stufe F.' }),
        d.entscheidungen.length ? el('div', { class: 'liste-klein' }, d.entscheidungen.map(e => el('div', {},
          el('span', { class: 'dat', text: L.tag(e.zeit) + ' ' + e.zeit.slice(11, 16) }), Raster.ereignisText(e),
          e.wer_art === 'lehrkraft' ? el('span', { class: 'leise', text: ' (' + e.wer.toUpperCase() + ')' }) : null)))
          : el('p', { class: 'leise', text: 'Noch keine Einträge.' })));
  }
  L.setzen(inhalt, teile);
}

// --- Klassen ---

function klassenKarte(k) {
  return el('a', { class: 'karte klassenkarte', href: '#klasse/' + k.id },
    el('div', { class: 'zeile' }, el('h3', { text: k.name }), el('span', { class: 'rechts' }, rolleChip(k.rolle))),
    el('div', { class: 'leise klein', text: [k.schuljahr, k.anzahl_schueler + ' Schüler'].filter(Boolean).join(' · ') }),
    el('div', { class: 'klein' }, 'Team: ', k.team.map(t => t.kuerzel.toUpperCase()).join(', ') || '–',
      k.einsicht.length ? ' · Einsicht: ' + k.einsicht.map(t => t.kuerzel.toUpperCase()).join(', ') : ''));
}

async function klassenZeigen(archiv) {
  titelSetzen(archiv ? 'Archiv' : 'Klassen');
  const { klassen } = await L.api('GET', '/api/klassen' + (archiv ? '?archiv=1' : ''));
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: archiv ? 'Archivierte Klassen' : 'Klassen' }),
      archiv ? null : el('button', { class: 'haupt', type: 'button', onclick: klasseAnlegen }, L.symbol('plus'), 'Klasse')),
    klassen.length ? el('div', { class: 'raster' }, klassen.map(klassenKarte))
      : el('div', { class: 'leer', text: archiv ? 'Keine archivierten Klassen.' : 'Noch keine Klasse. Eine Klasse entspricht einem Moodle-Kurs.' }));
}

function klassenFelder(k) {
  const name = el('input', { value: k ? k.name : '', required: true, maxlength: 40, placeholder: 'BSMT 24a' });
  const schuljahr = el('input', { value: k ? k.schuljahr : vorschlagSchuljahr(), maxlength: 12, placeholder: '2026/27' });
  const kurs = el('input', { value: k ? k.moodle_kurs : '', maxlength: 80, placeholder: 'z. B. Mechatronik BSMT 24a' });
  return { name, schuljahr, kurs, block: el('div', { class: 'felder' }, L.feld('Name der Klasse', name),
    el('div', { class: 'felder zwei' }, L.feld('Schuljahr', schuljahr), L.feld('Moodle-Kurs', kurs, 'nur zur Erinnerung, 1 Kurs = 1 Klasse'))) };
}

function vorschlagSchuljahr() {
  const d = new Date(), j = d.getMonth() >= 7 ? d.getFullYear() : d.getFullYear() - 1;
  return j + '/' + String(j + 1).slice(2);
}

async function klasseAnlegen() {
  const f = klassenFelder(null);
  const ergebnis = await L.dialog({
    titel: 'Neue Klasse', knopf: 'Anlegen', inhalt: [f.block, el('p', { class: 'leise klein', text: 'Sie stehen danach im Team der Klasse und können weitere Lehrkräfte eintragen.' })],
    speichern: () => L.api('POST', '/api/klassen', { name: f.name.value, schuljahr: f.schuljahr.value, moodle_kurs: f.kurs.value }),
  });
  if (ergebnis) location.hash = 'klasse/' + ergebnis.klasse.id;
}

async function klasseZeigen(kid) {
  const { klasse: k } = await L.api('GET', '/api/klassen/' + kid);
  titelSetzen(k.name);
  const team = k.rolle === 'team';
  const zuordnen = team || k.rolle === 'admin';
  const kopf = el('div', { class: 'werkzeug' },
    el('h1', { class: 'dreieck', text: k.name }), rolleChip(k.rolle), k.archiviert ? el('span', { class: 'chip', text: 'archiviert' }) : null,
    team ? el('button', { type: 'button', onclick: () => moodleAssistent(k) }, L.symbol('hoch'), 'Moodle-Teilnehmerliste') : null,
    team ? el('button', { type: 'button', onclick: () => karten(k.id) }, L.symbol('laden'), 'QR-Karten (PDF)') : null,
    team ? el('button', { type: 'button', onclick: () => klasseBearbeiten(k) }, 'Bearbeiten') : null,
    k.rolle !== 'admin' ? el('a', { class: 'knopf', href: '#pakete/' + k.id }, L.symbol('pakete'), 'Pakete') : null);

  const personen = (liste, rolle) => el('div', { class: 'personen' }, liste.length ? liste.map(p =>
    el('span', { class: 'person' }, p.name + ' (' + p.kuerzel.toUpperCase() + ')',
      zuordnen ? el('button', { type: 'button', title: 'Entfernen', text: '×', onclick: () => lehrkraftSetzen(k, p, null) }) : null))
    : el('span', { class: 'leise klein', text: rolle === 'team' ? '–' : 'niemand' }));
  const lehrkraftKarte = el('div', { class: 'karte stapel' },
    el('h2', { text: 'Lehrkräfte der Klasse' }),
    el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Team · volle Rechte' }), personen(k.team, 'team')),
    el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Einsicht · nur lesen' }), personen(k.einsicht, 'einsicht')),
    zuordnen ? el('div', { class: 'zeile' }, el('button', { type: 'button', class: 'klein', onclick: () => lehrkraftHinzu(k) }, L.symbol('plus'), 'Lehrkraft eintragen')) : null);

  const teile = [kopf];
  if (k.rolle === 'admin') {
    teile.push(el('div', { class: 'banner', text: 'Sie sind hier nicht eingetragen. Als Admin sehen Sie nur die Lehrkräfte und können sie zuordnen.' }), lehrkraftKarte);
    L.setzen(inhalt, teile);
    return;
  }
  const darstellung = el('select', { disabled: !team, onchange: async ev => {
    try { await L.api('POST', '/api/klassen/' + k.id, { einschaetzer: ev.target.value }); L.meldung('Darstellung gespeichert.'); }
    catch (e) { L.meldung(e.message, true); }
  } }, el('option', { value: 'smiley', text: 'Smileys 😟 😐 🙂 😀' }), el('option', { value: 'zahl', text: 'Zahlen 1 bis 4' }));
  darstellung.value = k.einschaetzer;
  const einstellung = el('div', { class: 'karte stapel' }, el('h2', { text: 'Einstellungen der Klasse' }),
    el('div', { class: 'daten leise klein', text: [k.schuljahr && 'Schuljahr ' + k.schuljahr, k.moodle_kurs && 'Moodle-Kurs: ' + k.moodle_kurs].filter(Boolean).join(' · ') || 'Kein Schuljahr eingetragen.' }),
    L.feld('Einschätzer der Kann-Listen', darstellung, 'gilt für alle Schüler der Klasse, umschalten geht jederzeit'));

  teile.push(el('div', { class: 'zwei-spalten' }, lehrkraftKarte, einstellung), Tage.karte(k), schuelerKarte(k));
  L.setzen(inhalt, teile);
}

function schuelerKarte(k) {
  const team = k.rolle === 'team';
  const aktiv = k.schueler.filter(s => s.aktiv), alt = k.schueler.filter(s => !s.aktiv);
  const zeile = s => el('tr', { class: s.aktiv ? null : 'aus' },
    el('td', {}, el('a', { href: '#schueler/' + k.id + '/' + s.id, text: s.nachname + ', ' + s.vorname })),
    team ? el('td', { class: 'code-text', text: s.code }) : null,
    team ? el('td', { class: 'knoepfe' },
      s.aktiv ? el('button', { type: 'button', class: 'klein', onclick: () => qrZeigen(k, s) }, L.symbol('qr'), 'QR') : null, ' ',
      el('button', { type: 'button', class: 'klein', onclick: () => schuelerBearbeiten(k, s) }, 'Bearbeiten')) : null);
  return el('div', { class: 'karte stapel' },
    el('div', { class: 'zeile' }, el('h2', { text: 'Schülerinnen und Schüler (' + aktiv.length + ')' }),
      team ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => schuelerNeu(k) }, L.symbol('plus'), 'Schüler')) : null),
    k.schueler.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
      el('thead', {}, el('tr', {}, el('th', { text: 'Name' }), team ? el('th', { text: 'Zugangscode' }) : null, team ? el('th', {}) : null)),
      el('tbody', {}, aktiv.map(zeile), alt.length ? el('tr', {}, el('td', { colspan: 3, class: 'etikett', text: 'Archiviert' })) : null, alt.map(zeile))))
      : el('div', { class: 'leer', text: team ? 'Noch keine Schüler. Am einfachsten: „Moodle-Teilnehmerliste“ oben.' : 'Noch keine Schüler.' }),
    team ? null : el('p', { class: 'leise klein', text: 'Zugangscodes sieht nur das Team der Klasse.' }));
}

async function klasseBearbeiten(k) {
  const f = klassenFelder(k);
  const archiv = el('input', { type: 'checkbox', checked: k.archiviert });
  const ok = await L.dialog({
    titel: 'Klasse bearbeiten', inhalt: [f.block, el('label', { class: 'haken' }, archiv, 'Klasse archivieren (Zugangscodes gelten dann nicht mehr)')],
    speichern: () => L.api('POST', '/api/klassen/' + k.id, { name: f.name.value, schuljahr: f.schuljahr.value, moodle_kurs: f.kurs.value, archiviert: archiv.checked }),
  });
  if (ok) zeigen();
}

async function lehrkraftHinzu(k) {
  const liste = (await lehrkraefte(true)).filter(l => !l.gesperrt);
  const wahl = el('select', { required: true }, el('option', { value: '', text: 'Lehrkraft wählen …' }),
    liste.map(l => el('option', { value: l.id, text: l.name + ' (' + l.kuerzel.toUpperCase() + ')' })));
  const rolle = el('select', {}, el('option', { value: 'team', text: 'Team · volle Rechte' }), el('option', { value: 'einsicht', text: 'Einsicht · nur lesen' }));
  const ok = await L.dialog({
    titel: 'Lehrkraft eintragen', knopf: 'Eintragen',
    inhalt: el('div', { class: 'felder' }, L.feld('Lehrkraft', wahl), L.feld('Rolle in ' + k.name, rolle,
      'Einsicht passt z. B. für die Klassenleitung: sieht alles, ändert nichts, sieht keine Zugangscodes.')),
    speichern: () => L.api('POST', '/api/klassen/' + k.id + '/lehrkraft', { lehrkraft_id: Number(wahl.value), rolle: rolle.value }),
  });
  if (ok) zeigen();
}

async function lehrkraftSetzen(k, p, rolle) {
  const ok = await L.dialog({
    titel: p.name + ' austragen?', knopf: 'Austragen', gefaehrlich: true,
    inhalt: el('p', { text: p.id === S.konto.id ? 'Sie sehen die Klasse danach nicht mehr.' : p.name + ' sieht die Klasse danach nicht mehr.' }),
    speichern: () => L.api('POST', '/api/klassen/' + k.id + '/lehrkraft', { lehrkraft_id: p.id, rolle }),
  });
  if (ok) { if (p.id === S.konto.id && !ok.klasse) location.hash = 'klassen'; else zeigen(); }
}

async function schuelerNeu(k) {
  const vorname = el('input', { required: true, maxlength: 60 }), nachname = el('input', { required: true, maxlength: 60 });
  const ok = await L.dialog({
    titel: 'Schüler hinzufügen', knopf: 'Hinzufügen', inhalt: el('div', { class: 'felder zwei' }, L.feld('Vorname', vorname), L.feld('Nachname', nachname)),
    speichern: () => L.api('POST', '/api/klassen/' + k.id + '/schueler', { vorname: vorname.value, nachname: nachname.value }),
  });
  if (ok) zeigen();
}

async function schuelerBearbeiten(k, s) {
  const vorname = el('input', { required: true, maxlength: 60, value: s.vorname }), nachname = el('input', { required: true, maxlength: 60, value: s.nachname });
  const aktiv = el('input', { type: 'checkbox', checked: s.aktiv });
  const ok = await L.dialog({
    titel: s.vorname + ' ' + s.nachname, inhalt: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, L.feld('Vorname', vorname), L.feld('Nachname', nachname)),
      el('label', { class: 'haken' }, aktiv, 'aktiv (abwählen = archivieren, der Code gilt dann nicht mehr)')),
    speichern: () => L.api('POST', '/api/klassen/' + k.id + '/schueler/' + s.id, { vorname: vorname.value, nachname: nachname.value, aktiv: aktiv.checked }),
  });
  if (ok) zeigen();
}

async function qrZeigen(k, s) {
  const antwort = await fetch('/api/klassen/' + k.id + '/schueler/' + s.id + '/qr.svg', { credentials: 'same-origin' });
  if (!antwort.ok) { L.meldung('QR-Code ging nicht.', true); return; }
  const adresse = antwort.headers.get('X-Adresse') || '';
  const bild = el('img', { class: 'qr-bild', alt: 'QR-Code für ' + s.vorname, src: URL.createObjectURL(await antwort.blob()) });
  let neu = false;
  const ergebnis = await L.dialog({
    titel: s.vorname + ' ' + s.nachname, knopf: 'Karte drucken (PDF)', abbrechen: 'Schließen',
    inhalt: el('div', { class: 'stapel' },
      el('div', { class: 'zeile', style: 'align-items:flex-start;gap:16px' }, bild,
        el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Zugangscode' }), el('div', { class: 'code-text', style: 'font-size:1.4rem', text: s.code }),
          el('div', { class: 'leise klein', text: adresse.replace(/\/s\/.*/, '/s/…') }),
          el('button', { type: 'button', class: 'warnen klein', onclick: () => { neu = true; bild.closest('dialog').dispatchEvent(new Event('cancel')); } },
            'Neuen Code erzeugen …'))),
      el('p', { class: 'leise klein', text: 'Code verloren? Ein neuer Code macht den alten sofort ungültig.' })),
    speichern: () => karten(k.id, s.id),
  });
  URL.revokeObjectURL(bild.src);
  if (neu && !ergebnis) codeNeu(k, s);
}

async function codeNeu(k, s) {
  const ok = await L.dialog({
    titel: 'Neuen Code für ' + s.vorname + '?', knopf: 'Neuen Code erzeugen', gefaehrlich: true,
    inhalt: el('p', { text: 'Die alte Karte von ' + s.vorname + ' funktioniert danach nicht mehr. Drucken Sie anschließend eine neue Karte.' }),
    speichern: () => L.api('POST', '/api/klassen/' + k.id + '/schueler/' + s.id, { code_neu: true }),
  });
  if (ok) { L.meldung('Neuer Code: ' + ok.schueler.code); await zeigen(); }
}

async function karten(kid, sid) {
  try { await L.herunterladen('/api/klassen/' + kid + '/qr-karten.pdf' + (sid ? '?schueler=' + sid : '')); }
  catch (e) { L.meldung(e.message, true); }
}

// --- Moodle-Teilnehmerliste: Assistent mit Zuordnungstabelle vor dem Schreiben ---

function dateiLesen(datei) {
  // Moodle schreibt UTF-8; aeltere Exporte aus Excel kommen als Windows-1252: dann noch einmal so lesen
  const lesen = kodierung => new Promise((ok, fehler) => {
    const r = new FileReader();
    r.onload = () => ok(r.result);
    r.onerror = () => fehler(new Error('Die Datei ließ sich nicht lesen.'));
    r.readAsText(datei, kodierung);
  });
  return lesen('utf-8').then(text => text.includes('�') ? lesen('windows-1252') : text);
}

async function moodleAssistent(k) {
  let text = null, zeilen = null;
  const eingabe = el('input', { type: 'file', accept: '.csv,.json,.txt,text/csv,application/json' });
  const ergebnis = el('div', { class: 'stapel' });
  eingabe.addEventListener('change', async () => {
    L.setzen(ergebnis, el('p', { class: 'leise', text: 'Lese Datei …' }));
    try {
      text = await dateiLesen(eingabe.files[0]);
      const v = await L.api('POST', '/api/klassen/' + k.id + '/moodle/vorschau', { datei: text });
      zeilen = v.zeilen;
      tabelle(v);
    } catch (e) { text = null; zeilen = null; L.setzen(ergebnis, el('div', { class: 'banner warnung', text: e.message })); }
  });
  function tabelle(v) {
    const zahl = a => zeilen.filter(z => z.aktion === a).length;
    L.setzen(ergebnis,
      el('div', { class: 'banner' }, el('b', { text: eingabe.files[0].name }), ' gelesen: ', zeilen.filter(z => z.aktion !== 'fehlt').length, ' Einträge. ',
        zahl('neu') + ' neu, ' + (zahl('behalten') + zahl('reaktivieren')) + ' schon da, ' + zahl('lehrkraft') + ' Lehrkräfte übersprungen. ',
        'Gespeichert werden nur Vor- und Nachname.'),
      el('div', { class: 'rollbar', style: 'max-height:50vh' }, el('table', { class: 'liste' },
        el('thead', {}, el('tr', {}, el('th', { text: 'Name in der Datei' }), el('th', { text: 'Rolle' }), el('th', { text: 'Im Lernbüro' }))),
        el('tbody', {}, zeilen.map((z, i) => el('tr', {},
          el('td', { text: z.nachname + ', ' + z.vorname }),
          el('td', { class: 'leise klein', text: z.rolle || '' }),
          el('td', {}, el('span', { class: 'chip ' + AKTION[z.aktion][0], text: AKTION[z.aktion][1] }),
            z.hinweis ? el('span', { class: 'leise klein', text: ' ' + z.hinweis }) : null,
            z.aktion === 'fehlt' ? el('label', { class: 'haken klein', style: 'margin-top:4px' }, el('input', { type: 'checkbox', 'data-archiv': z.schueler_id }), 'archivieren') : null)))))));
  }
  const ok = await L.dialog({
    titel: 'Teilnehmerliste aus Moodle', knopf: 'Übernehmen', breit: true,
    inhalt: el('div', { class: 'stapel' },
      el('p', { class: 'leise', text: 'In Moodle: Kurs → Teilnehmer/innen → alle auswählen → „Herunterladen als CSV“ (oder JSON). Dasselbe Format wie im Lehrerkalender.' }),
      L.feld('Datei wählen', eingabe), ergebnis),
    speichern: async form => {
      if (!text || !zeilen) throw new Error('Bitte zuerst die Datei wählen.');
      const archivieren = Array.from(form.querySelectorAll('[data-archiv]:checked'), c => Number(c.dataset.archiv));
      return L.api('POST', '/api/klassen/' + k.id + '/moodle/uebernehmen', { datei: text, archivieren });
    },
  });
  if (ok) {
    const e = ok.ergebnis;
    L.meldung(e.neu + ' angelegt' + (e.reaktiviert ? ', ' + e.reaktiviert + ' wieder aktiv' : '') + (e.archiviert ? ', ' + e.archiviert + ' archiviert' : '') + '.');
    zeigen();
  }
}

// --- Lehrkraefte (Admin) ---

async function lehrkraefteZeigen() {
  titelSetzen('Lehrkräfte');
  const liste = await lehrkraefte(true);
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Lehrkräfte' }),
      el('button', { class: 'haupt', type: 'button', onclick: () => lehrkraftBearbeiten(null) }, L.symbol('plus'), 'Lehrkraft')),
    el('div', { class: 'karte rollbar' }, el('table', { class: 'liste' },
      el('thead', {}, el('tr', {}, ['Kürzel', 'Name', 'Rolle', 'Stand', ''].map(t => el('th', { text: t })))),
      el('tbody', {}, liste.map(l => el('tr', { class: l.gesperrt ? 'aus' : null },
        el('td', { class: 'mono', text: l.kuerzel.toUpperCase() }), el('td', { text: l.name }),
        el('td', { text: l.rolle === 'admin' ? 'Admin' : 'Lehrkraft' }),
        el('td', {}, l.gesperrt ? el('span', { class: 'chip rot', text: 'gesperrt' }) : l.pw_vorlaeufig ? el('span', { class: 'chip gelb', text: 'vorläufiges Passwort' }) : el('span', { class: 'chip gruen', text: 'aktiv' })),
        el('td', { class: 'knoepfe' }, el('button', { type: 'button', class: 'klein', onclick: () => lehrkraftBearbeiten(l) }, 'Bearbeiten'))))))),
    el('p', { class: 'leise klein', text: 'Welche Klassen eine Lehrkraft sieht, legt das Team der Klasse fest (Team oder Einsicht).' }));
}

async function lehrkraftBearbeiten(l) {
  const kuerzel = el('input', { required: true, maxlength: 8, value: l ? l.kuerzel : '', readonly: !!l, autocapitalize: 'none' });
  const name = el('input', { required: true, maxlength: 80, value: l ? l.name : '' });
  const rolle = el('select', {}, el('option', { value: 'lehrkraft', text: 'Lehrkraft' }), el('option', { value: 'admin', text: 'Admin' }));
  rolle.value = l ? l.rolle : 'lehrkraft';
  const pw = el('input', { value: l ? '' : passwortVorschlag(), minlength: 8, placeholder: l ? 'leer lassen = unverändert' : '' });
  const gesperrt = el('input', { type: 'checkbox', checked: l && l.gesperrt });
  const ok = await L.dialog({
    titel: l ? l.name : 'Neue Lehrkraft', knopf: l ? 'Speichern' : 'Anlegen',
    inhalt: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, L.feld('Kürzel', kuerzel), L.feld('Rolle', rolle)), L.feld('Name', name),
      L.feld(l ? 'Neues vorläufiges Passwort' : 'Vorläufiges Passwort', pw, 'muss bei der ersten Anmeldung geändert werden'),
      l ? el('label', { class: 'haken' }, gesperrt, 'Konto gesperrt') : null),
    speichern: () => l
      ? L.api('POST', '/api/lehrkraefte/' + l.id, { name: name.value, rolle: rolle.value, gesperrt: gesperrt.checked, passwort: pw.value || undefined })
      : L.api('POST', '/api/lehrkraefte', { kuerzel: kuerzel.value, name: name.value, rolle: rolle.value, passwort: pw.value }),
  });
  if (ok) { if (!l || pw.value) L.meldung('Vorläufiges Passwort: ' + pw.value); lehrkraefteZeigen(); }
}

// --- Einstellungen (Admin): Schueleradresse, Update, Sicherung ---

async function einstellungenZeigen() {
  titelSetzen('Einstellungen');
  const [e, u] = await Promise.all([L.api('GET', '/api/einstellungen'), L.api('GET', '/api/update')]);
  const adresse = el('input', { value: e.schueler_adresse, placeholder: e.vorschlag });
  const pruefung = u.pruefung || {};
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Einstellungen' })),
    el('div', { class: 'zwei-spalten' },
      el('form', { class: 'karte stapel', onsubmit: async ev => {
        ev.preventDefault();
        try { await L.api('POST', '/api/einstellungen', { schueler_adresse: adresse.value }); L.meldung('Gespeichert.'); }
        catch (f) { L.meldung(f.message, true); }
      } },
        el('h2', { text: 'Adresse für die QR-Codes' }),
        el('p', { class: 'leise klein', text: 'Unter dieser Adresse öffnen die Schülergeräte ihren Plan (über HTTP, ohne Zertifikat). Leer lassen = die Adresse, unter der Sie gerade angemeldet sind: ' + e.vorschlag }),
        L.feld('Adresse', adresse), el('div', {}, el('button', { class: 'haupt', type: 'submit', text: 'Speichern' }))),
      el('div', { class: 'karte stapel' },
        el('h2', { text: 'Version und Update' }),
        el('p', {}, 'Installiert: ', el('b', { text: u.version }),
          pruefung.verfuegbar && pruefung.neu ? el('span', { class: 'chip gelb', style: 'margin-left:8px', text: 'neu: ' + (pruefung.verfuegbar.version || pruefung.verfuegbar.stand) }) : null),
        u.eingerichtet ? el('div', { class: 'zeile' },
          el('button', { type: 'button', onclick: () => updateAnfordern('pruefen') }, 'Jetzt prüfen'),
          el('button', { type: 'button', class: 'haupt', disabled: !pruefung.neu || u.laeuft, onclick: () => updateAnfordern('ausfuehren') }, 'Jetzt aktualisieren'))
          : el('p', { class: 'leise klein', text: 'Update über die Seite geht nur im Container.' }),
        u.laeuft ? el('div', { class: 'banner', text: 'Update läuft …' }) : null,
        u.protokoll ? el('details', {}, el('summary', { text: 'Protokoll des letzten Updates' }), el('pre', { class: 'mono klein', style: 'white-space:pre-wrap', text: u.protokoll })) : null),
      el('div', { class: 'karte stapel' },
        el('h2', { text: 'Sicherung' }),
        el('p', { class: 'leise klein', text: 'Die ganze Datenbank als ZIP. Vor jedem Update legt der Container zusätzlich selbst eine Sicherung an (die letzten fünf bleiben).' }),
        el('div', {}, el('button', { type: 'button', onclick: () => L.herunterladen('/api/sicherung.zip').catch(f => L.meldung(f.message, true)) }, L.symbol('laden'), 'Sicherung herunterladen')),
        u.sicherungen.length ? el('div', { class: 'stapel', style: 'gap:4px' }, u.sicherungen.map(s =>
          el('a', { href: '/api/update/sicherung/' + s.name, class: 'klein', text: s.name + ' (' + Math.round(s.groesse / 1024) + ' KB)' }))) : null),
      Tage.ferienKarte()));
}

async function updateAnfordern(art) {
  const ok = art === 'pruefen' ? true : await L.dialog({
    titel: 'Jetzt aktualisieren?', knopf: 'Aktualisieren',
    inhalt: el('p', { text: 'Vorher wird eine Sicherung angelegt. Die Seite ist während des Updates etwa eine Minute nicht erreichbar.' }),
  });
  if (!ok) return;
  try { await L.api('POST', '/api/update', { art }); L.meldung(art === 'pruefen' ? 'Prüfung läuft.' : 'Update gestartet.'); setTimeout(zeigen, 3000); }
  catch (e) { L.meldung(e.message, true); }
}

// --- Mein Konto ---

function kontoZeigen() {
  titelSetzen('Mein Konto');
  const alt = el('input', { type: 'password', autocomplete: 'current-password', required: true });
  const neu = el('input', { type: 'password', autocomplete: 'new-password', minlength: 8, required: true });
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Mein Konto' })),
    el('form', { class: 'karte stapel', style: 'max-width:480px', onsubmit: async ev => {
      ev.preventDefault();
      try { await L.api('POST', '/api/passwort', { alt: alt.value, neu: neu.value }); alt.value = neu.value = ''; L.meldung('Passwort geändert.'); }
      catch (f) { L.meldung(f.message, true); }
    } },
      el('p', {}, el('b', { text: S.konto.name }), ' · ', S.konto.kuerzel.toUpperCase(), ' · ', S.konto.rolle === 'admin' ? 'Admin' : 'Lehrkraft'),
      el('h2', { text: 'Passwort ändern' }), L.feld('Bisheriges Passwort', alt), L.feld('Neues Passwort', neu, 'mindestens 8 Zeichen'),
      el('div', {}, el('button', { class: 'haupt', type: 'submit', text: 'Passwort ändern' }))));
}

start();
