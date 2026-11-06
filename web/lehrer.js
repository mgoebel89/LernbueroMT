// Lehrerbereich, Stufe A: Klassen mit Team und Einsicht, Schueler, Moodle-Teilnehmerliste (Assistent), QR-Karten,
// Lehrkraefte (Admin), Einstellungen mit Update und Sicherung, eigenes Konto. Jede Entscheidung laeuft ueber ein Overlay.
'use strict';
const { el } = L;
const S = { konto: null, lehrkraefte: null, update: null };
const inhalt = document.getElementById('inhalt');
const NAV = [
  { a: 'uebersicht', text: 'Übersicht', s: 'uebersicht' },
  { a: 'klassen', text: 'Klassen', s: 'klassen' },
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
  } catch (e) {
    if (e.status === 401) { location.replace('/anmelden'); return; }
    fehlerZeigen(e);
    return;
  }
  document.getElementById('wer').textContent = S.konto.name + ' · ' + S.konto.kuerzel.toUpperCase();
  L.setzen(document.getElementById('navigation'), NAV.filter(n => !n.admin || S.konto.rolle === 'admin').map(n =>
    el('a', { href: '#' + n.a, 'data-ansicht': n.a }, L.symbol(n.s), n.text,
      n.a === 'einstellungen' && S.update ? el('span', { class: 'chip gelb klein', text: 'Update' }) : null)));
  document.getElementById('abmelden').addEventListener('click', async () => {
    try { await L.api('POST', '/api/abmelden', {}); } finally { location.href = '/anmelden'; }
  });
  if (S.konto.pw_vorlaeufig) await passwortPflicht();
  window.addEventListener('hashchange', zeigen);
  zeigen();
}

async function zeigen() {
  const [ansicht, id] = (location.hash.slice(1) || 'uebersicht').split('/');
  const nav = ansicht === 'klasse' ? 'klassen' : ansicht;
  document.querySelectorAll('nav.seite a').forEach(a => a.classList.toggle('an', a.dataset.ansicht === nav));
  try {
    if (ansicht === 'uebersicht') await uebersichtZeigen();
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

// --- Uebersicht (Stufe C/D) ---

async function uebersichtZeigen() {
  titelSetzen('Übersicht');
  const { klassen } = await L.api('GET', '/api/klassen');
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Übersicht' })),
    el('div', { class: 'banner' }, 'Hilfe-Reihe, „Zu prüfen“, Bereit-Liste und Klassenmatrix kommen mit den Stufen C und D. ',
      'Jetzt in Stufe A: Klassen anlegen, Teilnehmerliste aus Moodle übernehmen und QR-Karten drucken.'),
    klassen.length ? el('div', { class: 'raster' }, klassen.map(klassenKarte))
      : el('div', { class: 'leer' }, 'Noch keine Klasse. ', el('a', { href: '#klassen', text: 'Erste Klasse anlegen' })));
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
    team ? el('button', { type: 'button', onclick: () => klasseBearbeiten(k) }, 'Bearbeiten') : null);

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

  teile.push(el('div', { class: 'zwei-spalten' }, lehrkraftKarte, einstellung), schuelerKarte(k));
  L.setzen(inhalt, teile);
}

function schuelerKarte(k) {
  const team = k.rolle === 'team';
  const aktiv = k.schueler.filter(s => s.aktiv), alt = k.schueler.filter(s => !s.aktiv);
  const zeile = s => el('tr', { class: s.aktiv ? null : 'aus' },
    el('td', { text: s.nachname + ', ' + s.vorname }),
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
          el('a', { href: '/api/update/sicherung/' + s.name, class: 'klein', text: s.name + ' (' + Math.round(s.groesse / 1024) + ' KB)' }))) : null)));
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
