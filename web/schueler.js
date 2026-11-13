// Schülerseite (/s/<Code>): Leiste mit den fünf Bereichen (feste Farbe und Symbol, am PC links, am Handy unten).
// Stufe C: Mein Plan (Raster), Heute mit „Tag abschließen“, Kann-Liste vorher.
// Stufe D: Aufgabe öffnen und fertig melden (mit Kann-Aussagen „nachher“), Hilfe-Knopf live mit Platz in der Reihe,
// Feedbacktermin buchen und absagen, Rückmeldungen und Empfehlungen. Jede Entscheidung läuft über ein Overlay,
// nur der Hilfe-Knopf wirkt mit einem Tipp.
// Stufe E: Gelingensnachweise: bereit melden (ganze Kann-Liste „nachher“), Prüfungstermin buchen, Ergebnisse und Versuche.
'use strict';
const { el } = L;
const CODE = location.pathname.split('/')[2].toUpperCase().replace(/[^A-Z0-9]/g, '');
const inhalt = document.getElementById('inhalt');
const BEREICHE = [
  { s: 'plan', lang: 'Mein Plan', kurz: 'Plan' },
  { s: 'heute', lang: 'Heute', kurz: 'Heute' },
  { s: 'kann', lang: 'Kann-Liste', kurz: 'Kann ich' },
  { s: 'rueck', lang: 'Rückmeldungen', kurz: 'Rückmeld.' },
  { s: 'gn', lang: 'Gelingensnachweise', kurz: 'Nachweise' },
];
const AMPELN = [['g', 'im Zeitplan'], ['y', 'knapp, schaffe ich bis zur Frist'], ['r', 'nicht im Zeitplan, brauche Hilfe']];
let ich = null, z = null, gefragt = false, modus = 'markieren';

const api = (pfad, daten) => L.api(daten === undefined ? 'GET' : 'POST', '/api/s/' + CODE + pfad, daten);
const zahlen = () => ich.einschaetzer === 'zahl';

function merken() {
  try { localStorage.setItem('lernbuero-code', CODE); } catch (e) { /* privat: dann eben nicht */ }
}

// --- Hilfe-Knopf: ein Tipp genügt, kein Overlay ---

async function hilfeRufen() {
  if (!z.hilfe.erlaubt) { L.meldung('Der Hilfe-Knopf geht nur im Lernbüro mit Lehrkraft (' + z.hilfe.grund + ').', true); return; }
  if (z.hilfe.offen) { L.meldung('Du bist Nr. ' + z.hilfe.platz + ' in der Reihe.'); return; }
  try { z = await api('/hilfe', { aktion: 'rufen' }); hilfeAnzeigen(); leisteZahlen(); }
  catch (e) { L.meldung(e.message, true); }
}

async function hilfeZurueck() {
  try { z = await api('/hilfe', { aktion: 'zurueck' }); hilfeAnzeigen(); }
  catch (e) { L.meldung(e.message, true); }
}

function hilfeBlock(gross) {
  const h = z ? z.hilfe : { erlaubt: true, offen: false };
  const knopf = el('button', { type: 'button', class: (gross ? 'hilfe-gross' : 'hilfe-knopf schiene-hilfe') + (h.offen ? ' an' : '') + (h.erlaubt ? '' : ' gesperrt'),
    onclick: hilfeRufen, 'aria-live': 'polite' }, L.symbol('hilfe'),
  h.offen ? (gross ? 'Du bist Nr. ' + h.platz + ' in der Reihe' : 'Du bist Nr. ' + h.platz) : !h.erlaubt && gross ? 'Hilfe: ' + h.grund : 'Ich brauche Hilfe');
  if (!h.offen) return el('div', { class: 'hilfe-ort' + (gross ? ' gross' : ''), 'data-hilfe': gross ? 'gross' : 'schiene' }, knopf);
  return el('div', { class: 'hilfe-ort' + (gross ? ' gross' : ''), 'data-hilfe': gross ? 'gross' : 'schiene' }, knopf,
    el('button', { type: 'button', class: 'leicht klein hilfe-zurueck', onclick: hilfeZurueck, text: 'zurückziehen' }));
}

function hilfeAnzeigen() {
  document.querySelectorAll('[data-hilfe]').forEach(e => e.replaceWith(hilfeBlock(e.dataset.hilfe === 'gross')));
}

// --- Leiste ---

function leiste() {
  L.setzen(document.getElementById('schiene'), BEREICHE.map(b => el('a', { href: '#' + b.s, 'data-bereich': b.s, title: b.lang },
    el('b', { class: 'ik ' + b.s }, L.symbol(b.s)), el('span', { class: 'lang', text: b.lang === 'Gelingensnachweise' ? 'Nachweise' : b.lang }),
    el('span', { class: 'kurz', text: b.kurz }))), hilfeBlock(false));
}

function leisteZahlen() {
  const setzen = (bereich, n) => {
    const ik = document.querySelector('#schiene a[data-bereich=' + bereich + '] .ik');
    if (!ik) return;
    const alt = ik.querySelector('.zahl');
    if (alt) alt.remove();
    if (n) ik.appendChild(el('span', { class: 'zahl', text: String(n) }));
  };
  setzen('rueck', z ? z.ungelesen + (z.nachrichten_ungelesen || 0) : 0);
  setzen('kann', z ? alleZeilen().filter(r => r.gewaehlt && r.kann_stand === 'nachher').length : 0);
}

async function laden() {
  z = await api('/plan');
  return z;
}

async function schritt(pfad, daten) {
  z = await api(pfad, daten);
  zeigen();
  return z;
}

function alleZeilen() {
  return [].concat(...z.pakete.map(p => p.zeilen.filter(r => r.typ === 'aufgabe').map(r => Object.assign({ paket: p.titel, paket_id: p.id }, r))));
}

function paketVon(r) {
  return z.pakete.find(p => p.zeilen.some(x => x.typ === 'aufgabe' && x.id === r.id));
}

const meldbar = r => r.gewaehlt && !['fertig', 'angenommen'].includes(r.status);

// --- Bereiche ---

function zeigen() {
  const s = location.hash.slice(1) || 'plan';
  const b = BEREICHE.find(x => x.s === s) || BEREICHE[0];
  document.querySelectorAll('#schiene a').forEach(a => {
    a.classList.toggle('an', a.dataset.bereich === b.s);
    if (a.dataset.bereich === b.s) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  L.titel(b.lang);
  if (b.s === 'plan') planZeigen();
  else if (b.s === 'heute') heuteZeigen();
  else if (b.s === 'kann') kannZeigen();
  else if (b.s === 'rueck') rueckZeigen();
  else gnZeigen();
  hilfeAnzeigen();
  leisteZahlen();
  if (!gefragt) { gefragt = true; nachfragen(); }
}

function naechsteFrist() {
  const offen = alleZeilen().filter(r => r.gewaehlt && r.wirksam && r.wirksam >= z.heute && meldbar(r)).sort((a, b) => a.wirksam.localeCompare(b.wirksam));
  return offen[0];
}

function planZeigen() {
  const n = naechsteFrist();
  const alt = inhalt.querySelector('.r-scroll');
  const links = alt ? alt.scrollLeft : null;
  const planen_ = modus === 'planen';
  L.setzen(inhalt,
    el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Mein Plan' }),
      z.pakete.length ? el('button', { type: 'button', class: planen_ ? 'haupt' : null, onclick: () => { modus = planen_ ? 'markieren' : 'planen'; planZeigen(); } },
        L.symbol(planen_ ? 'haken' : 'plan'), planen_ ? 'Planen beenden' : 'Plan bearbeiten') : null),
    n ? el('div', { class: 'banner' }, 'Nächste Frist: ', el('b', { text: n.kuerzel + ' ' + n.titel }), ' am ' + L.tag(n.wirksam) + '.') : null,
    Object.values(z.einheiten || {}).filter(e => e.selbst && e.modus === 'pflicht' && !e.team).map(e => el('div', { class: 'banner team-banner zeile' },
      el('span', {}, L.symbol('klassen'), ' ', el('b', { text: e.titel }), ' bearbeitet ihr im Team' + (e.stichtag ? '. Findet euer Team bis ' + L.tag(e.stichtag) : '.')),
      el('button', { type: 'button', class: 'klein haupt rechts', onclick: () => teamBlatt(e) }, 'Team finden'))),
    z.pakete.length ? Raster.zeichnen(z, { bearbeitbar: true, modus, planen, markieren, waehlen: wahlFragen, oeffnen: aufgabeOeffnen, team: teamBlatt,
      nachweis: () => { location.hash = 'gn'; } })
      : el('div', { class: 'leer', text: 'Noch ist kein Lernpaket für dich freigegeben.' }),
    z.pakete.length ? el('p', { class: 'leise klein', text: 'Kürzel antippen: Aufgabe öffnen, fertig melden. Name antippen: Aufgabe in Moodle.' }) : null,
    el('p', { class: 'leise klein' }, 'Nicht du? ', el('a', { href: '/?neu', text: 'Anderen Code eingeben' })));
  // Scrollstand behalten; beim ersten Zeichnen den heutigen Tag in die Mitte holen
  const neu = inhalt.querySelector('.r-scroll');
  if (neu && links !== null) neu.scrollLeft = links;
  else if (neu) {
    const h = neu.querySelector('th.heute');
    if (h) neu.scrollLeft = Math.max(0, h.offsetLeft - neu.clientWidth / 2);
  }
}

// --- Nicht im Zeitplan: bei Rot fragt ein Overlay nach dem Grund und der Hilfe ---

const GRUENDE = [['schwer', 'schwerer als gedacht'], ['verstehe', 'ich verstehe etwas nicht'], ['gefehlt', 'ich habe gefehlt'],
  ['verplant', 'verplant, zu wenig geschafft'], ['technik', 'Problem mit Material, Technik oder Moodle'], ['team', 'Problem im Team']];
const HILFEN = [['jetzt', 'Erklärung jetzt'], ['feedback', 'Feedbackgespräch'], ['frist', 'neue Frist'], ['material', 'Material oder Unterlage'],
  ['keine', 'keine Hilfe, ich plane neu']];

function auswahlChips(liste, gewaehlt) {
  const wahl = new Set(gewaehlt || []);
  const ort = el('div', { class: 'chips-wahl' }, liste.map(([w, t]) => el('button', { type: 'button', class: wahl.has(w) ? 'an' : null,
    'aria-pressed': wahl.has(w) ? 'true' : 'false', onclick: ev => {
      if (wahl.has(w)) wahl.delete(w); else wahl.add(w);
      ev.currentTarget.classList.toggle('an', wahl.has(w));
      ev.currentTarget.setAttribute('aria-pressed', wahl.has(w) ? 'true' : 'false');
    } }, t)));
  return { ort, werte: () => Array.from(wahl) };
}

// p: vorhandene Angabe (oder nichts); Rückgabe { ort, lesen() } mit lesen() -> { gruende, grund_text, hilfe, hilfe_text }
function problemFelder(p) {
  p = p || {};
  const g = auswahlChips(GRUENDE, p.gruende), h = auswahlChips(HILFEN, p.hilfe);
  const gt = el('input', { maxlength: 400, placeholder: 'oder in eigenen Worten', value: p.grund_text || '' });
  const ht = el('input', { maxlength: 400, placeholder: 'oder in eigenen Worten', value: p.hilfe_text || '' });
  const ort = el('div', { class: 'stapel problem-felder', style: 'gap:8px' },
    el('div', { class: 'etikett', text: 'Warum bist du nicht im Zeitplan?' }), g.ort, gt,
    el('div', { class: 'etikett', text: 'Welche Hilfe brauchst du?' }), h.ort, ht);
  return { ort, lesen: () => ({ gruende: g.werte(), grund_text: gt.value, hilfe: h.werte(), hilfe_text: ht.value }) };
}

function problemPruefen(p) {
  if (!p.gruende.length && !p.grund_text.trim()) throw new Error('Bitte sag kurz, warum du nicht im Zeitplan bist.');
  if (!p.hilfe.length && !p.hilfe_text.trim()) throw new Error('Bitte wähle, welche Hilfe du brauchst (oder „keine Hilfe, ich plane neu“).');
  return p;
}

function nachProblem(p) {
  if (p.hilfe.includes('jetzt')) {
    L.meldung(z.hilfe.offen ? 'Du stehst in der Hilfe-Reihe (Nr. ' + z.hilfe.platz + ').' : 'Die Hilfe-Reihe geht nur im Lernbüro mit Lehrkraft. Deine Lehrkraft sieht deine Angabe.');
    hilfeAnzeigen();
  }
  if (p.hilfe.includes('feedback')) terminBuchen();
}

let markLaeuft = 0, markUhr = null;
async function markieren(aufgabeId, datum, ampel) {
  // die Zelle ist schon eingefärbt; neu gezeichnet wird erst, wenn eine Weile nicht mehr getippt wurde (Status, Scrollstand bleibt)
  const r = alleZeilen().find(x => x.id === aufgabeId);
  if (ampel && r && r.kann_stand === 'vorher' && !(await kannVorherFragen(r, 'arbeiten'))) { zeigen(); return; }
  if (ampel === 'r') { await rotFragen(aufgabeId, datum); return; }
  markLaeuft += 1;
  clearTimeout(markUhr);
  try { z = await api('/markieren', { aufgabe_id: aufgabeId, datum, ampel }); }
  catch (e) { L.meldung(e.message, true); markLaeuft -= 1; planZeigen(); return; }
  markLaeuft -= 1;
  markUhr = setTimeout(() => { if (!markLaeuft && (location.hash || '#plan') === '#plan' && !document.querySelector('dialog')) planZeigen(); }, 1500);
}

async function rotFragen(aufgabeId, datum) {
  const r = alleZeilen().find(x => x.id === aufgabeId);
  const f = problemFelder(r && r.probleme ? r.probleme[datum] : null);
  let problem = null;
  const ok = await L.dialog({
    titel: (r ? r.kuerzel + ' ' : '') + 'nicht im Zeitplan · ' + L.tag(datum), knopf: 'Speichern',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, f.ort,
      el('p', { class: 'leise klein', text: 'Deine Lehrkraft sieht deine Angaben. „Erklärung jetzt“ stellt dich in die Hilfe-Reihe, „Feedbackgespräch“ öffnet danach die Terminbuchung.' })),
    speichern: async () => {
      problem = problemPruefen(f.lesen());
      z = await api('/markieren', { aufgabe_id: aufgabeId, datum, ampel: 'r', problem });
      return true;
    },
  });
  zeigen();   // bei Abbrechen die schon eingefärbte Zelle zurücksetzen, sonst den neuen Stand zeigen
  if (ok) nachProblem(problem);
}

async function planen(aufgabeId, hinzu, weg) {
  const r = alleZeilen().find(x => x.id === aufgabeId);
  if (r && hinzu.length && r.kann_stand === 'vorher') {   // vor dem Planen: Kann-Liste vorher (auch für später dazugekommene Aussagen)
    if (!(await kannVorherFragen(r, 'planen'))) { zeigen(); return; }
  }
  try { await schritt('/plan', { aufgabe_id: aufgabeId, hinzu, weg }); }
  catch (e) { L.meldung(e.message, true); zeigen(); }
}

// Kann-Liste „vorher“ einer Aufgabe; Rückgabe true, wenn gespeichert. Pflicht, bevor eine Aufgabe angefangen wird:
// zweck 'planen' | 'arbeiten' (Farbe, Tagesabschluss) | 'melden' (Fertigmelden) | 'pflicht' (beim Öffnen der Seite)
async function kannVorherFragen(r, zweck) {
  const werte = {};
  r.kann_liste.forEach(k => { if (k.vorher) werte[k.id] = k.vorher; });
  const frage = {
    planen: 'Bevor du ' + r.kuerzel + ' ' + r.titel + ' planst: Wie gut kannst du das jetzt schon?',
    arbeiten: 'Bevor du mit ' + r.kuerzel + ' ' + r.titel + ' anfängst: Wie gut kannst du das jetzt schon?',
    melden: 'Bevor du ' + r.kuerzel + ' ' + r.titel + ' fertig meldest, fehlt noch „vorher“: Wie gut konntest du das, bevor du angefangen hast?',
    pflicht: 'Für ' + r.kuerzel + ' ' + r.titel + ' fehlt noch deine Einschätzung „vorher“: Wie gut konntest du das, bevor du angefangen hast?',
  }[zweck || 'planen'];
  const ok = await L.dialog({
    titel: 'Kann-Liste ' + r.kuerzel + ' · vorher', knopf: zweck === 'planen' || !zweck ? 'Speichern und planen' : 'Speichern',
    abbrechen: zweck === 'pflicht' ? 'Später' : 'Abbrechen',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('p', { text: frage }),
      zahlen() ? el('div', { class: 'leise klein', text: '1 = muss noch viel üben · 4 = kann es perfekt' }) : null,
      r.kann_liste.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text), L.skala(werte[k.id], stufe => { werte[k.id] = stufe; }, zahlen())))),
    speichern: async () => {
      if (r.kann_liste.some(k => !werte[k.id])) throw new Error('Bitte schätze jede Kann-Aussage ein.');
      for (const k of r.kann_liste) z = await api('/kann', { kann_id: k.id, aufgabe_id: r.id, stufe: werte[k.id] });
      return true;
    },
  });
  return !!ok;
}

function heuteZeigen() {
  const t = z.heute_tag;
  const heute = alleZeilen().filter(r => r.gewaehlt && r.plan.includes(z.heute));
  const unterricht = t && (t.status === 'unterricht' || t.status === 'ohne');
  const fristen = alleZeilen().filter(r => r.gewaehlt && r.wirksam && r.wirksam >= z.heute && meldbar(r))
    .sort((a, b) => a.wirksam.localeCompare(b.wirksam)).slice(0, 4);
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Heute · ' + L.tag(z.heute) }),
    !t ? el('div', { class: 'banner', text: 'Heute ist kein Lernbüro.' })
      : t.status === 'ohne' ? el('div', { class: 'banner', text: 'Heute ohne Lehrkraft (' + t.grund + '). Arbeite nach deinem Plan. Hilfe-Knopf und Termine sind heute gesperrt.' })
        : !unterricht ? el('div', { class: 'banner warnung', text: (t.status === 'ferien' ? 'Ferien: ' : 'Fällt aus: ') + t.grund }) : null,
    z.ungelesen ? el('a', { class: 'karte neu-rueck', href: '#rueck' }, el('b', { class: 'ik rueck' }, L.symbol('rueck')),
      el('div', {}, el('b', { text: z.ungelesen === 1 ? 'Neue Rückmeldung' : z.ungelesen + ' neue Rückmeldungen' }), el('div', { class: 'leise klein', text: 'antippen zum Lesen' }))) : null,
    unterricht && t.status !== 'ohne' ? hilfeBlock(true) : null,
    alleNachweise().filter(n => n.aktuell && n.aktuell.status === 'frei').map(n => el('a', { class: 'karte neu-rueck gn-frei', href: '#gn' },
      el('b', { class: 'ik gn' }, L.symbol('gn')), el('div', {}, el('b', { text: n.art_text + ' ist in Moodle freigeschaltet' }),
        el('div', { class: 'leise klein', text: n.paket + ' · antippen' })))),
    el('div', { class: 'karte stapel' }, el('div', { class: 'etikett', text: 'Für heute geplant' }),
      heute.length ? heute.map(r => el('div', { class: 'heute-zeile' },
        el('button', { type: 'button', class: 'kz', text: r.kuerzel, onclick: () => aufgabeOeffnen(r) }),
        el('div', { class: 'h-titel' }, r.moodle_link ? el('a', { class: 'alink', href: r.moodle_link, target: '_blank', rel: 'noopener', text: r.titel }) : r.titel,
          el('div', {}, Raster.statusChip(r), r.ampel ? el('span', { class: 'ampel a-' + r.ampel, style: 'margin-left:6px' }) : null)),
        meldbar(r) ? el('button', { type: 'button', class: 'haupt klein', onclick: () => fertigMelden(r) }, L.symbol('haken'), 'Fertig melden') : null))
        : el('p', { class: 'leise', text: unterricht ? 'Für heute hast du nichts geplant. Plane in „Mein Plan“.' : 'Nichts geplant.' })),
    unterricht ? el('button', { type: 'button', class: z.abgeschlossen ? 'knopf' : 'haupt', style: 'width:100%;padding:12px', onclick: abschliessen },
      L.symbol('kann'), z.abgeschlossen ? 'Tag abgeschlossen um ' + z.abgeschlossen.slice(11, 16) + ' · ändern' : 'Tag abschließen') : null,
    z.hinweise.ampel_alt.length ? el('div', { class: 'banner warnung', text: 'Farbe fehlt seit über einer Woche: ' +
      z.hinweise.ampel_alt.map(h => h.kuerzel).join(', ') + '. Bitte im Plan oder beim Tagesabschluss markieren.' }) : null,
    termineKarte(),
    fristen.length ? el('div', { class: 'karte stapel' }, el('div', { class: 'etikett', text: 'Demnächst fällig' }),
      el('div', { class: 'liste-klein' }, fristen.map(r => el('div', {}, el('span', { class: 'dat', text: L.tag(r.wirksam) }), r.kuerzel + ' ' + r.titel)))) : null);
}

function alleNachweise() {
  return [].concat(...z.pakete.map(p => p.nachweise.map(n => Object.assign({ paket: p.titel, paket_id: p.id }, n))));
}

const TERMINART = { feedback: 'Feedback', fachgespraech: 'Fachgespräch', praxis: 'Praktische Prüfung' };

function termineKarte() {
  const offen = z.termine.filter(t => !t.abgesagt && t.art === 'feedback' && !t.pflicht);
  return el('div', { class: 'karte stapel' }, el('div', { class: 'etikett', text: 'Termine' }),
    z.termine.length ? el('div', { class: 'stapel', style: 'gap:6px' }, z.termine.map(t => el('div', { class: 'termin-zeile' + (t.abgesagt ? ' abgesagt' : '') + (t.pflicht ? ' pflicht' : '') },
      el('div', {}, t.pflicht && !t.abgesagt ? el('div', { class: 'pflicht-titel', text: 'Deine Lehrkraft möchte mit dir sprechen' }) : null,
        el('b', { text: L.tag(t.datum) + ' · ' + t.beginn }), ' · ' + (t.art === 'feedback' ? t.anlass : TERMINART[t.art] + ' · ' + t.anlass),
        t.hinweis && !t.abgesagt ? el('div', { class: 'klein', text: '„' + t.hinweis + '“' }) : null,
        el('div', { class: 'leise klein', text: t.abgesagt ? (t.pflicht ? 'abgesagt von der Lehrkraft' : 'abgesagt von der Lehrkraft, bitte neu buchen') : 'bei ' + t.lehrkraft +
          (t.pflicht ? ' · Pflichttermin, absagen nur über deine Lehrkraft' : t.darf_absagen ? ' · absagen bis ' + L.tag(t.absagen_bis) : ' · absagen nur noch bei der Lehrkraft') })),
      t.darf_absagen ? el('button', { type: 'button', class: 'klein', onclick: () => absagen(t), text: 'absagen' }) : null)))
      : el('p', { class: 'leise klein', text: 'Kein Termin gebucht.' }),
    offen.length ? null : el('button', { type: 'button', style: 'justify-self:start', onclick: () => terminBuchen() }, L.symbol('uhr'), 'Feedbacktermin buchen'));
}

async function abschliessen() {
  // erst die Kann-Liste „vorher“ der heute bearbeiteten Aufgaben, dann der Tagesabschluss (kein Fenster über dem Fenster)
  for (const r of alleZeilen().filter(x => x.gewaehlt && x.kann_stand === 'vorher' && (x.plan.includes(z.heute) || x.ist[z.heute]))) {
    if (!(await kannVorherFragen(r, 'arbeiten'))) { zeigen(); return; }
  }
  const alle = alleZeilen().filter(r => r.gewaehlt && r.status !== 'angenommen');
  const wahl = {};
  const geplant = alle.filter(r => r.plan.includes(z.heute) || r.ist[z.heute]);
  const andere = alle.filter(r => !geplant.includes(r));
  const probleme = {};
  const zeile = r => {
    const ampel = r.ist[z.heute] || r.ampel || 'g';
    const box = el('input', { type: 'checkbox', checked: r.plan.includes(z.heute) || !!r.ist[z.heute] });
    const felder = problemFelder(r.probleme ? r.probleme[z.heute] : null);
    felder.ort.classList.add('abschluss-problem');
    probleme[r.id] = felder;
    const knoepfe = el('div', { class: 'ampel-wahl' }, AMPELN.map(([w, t]) => el('button', { type: 'button', class: w === ampel ? 'an' : null,
      onclick: ev => { wahl[r.id] = w; knoepfe.querySelectorAll('button').forEach(b => b.classList.toggle('an', b === ev.currentTarget)); sichtbar(); } },
      el('i', { class: 'ampel a-' + w }), t)));
    wahl[r.id] = ampel;
    const sichtbar = () => { knoepfe.hidden = !box.checked; felder.ort.hidden = !box.checked || wahl[r.id] !== 'r'; };
    box.addEventListener('change', sichtbar); sichtbar();
    return el('div', { class: 'abschluss-zeile', 'data-aufgabe': r.id }, el('label', { class: 'haken' }, box, el('b', { text: r.kuerzel }), r.titel + ' heute bearbeitet'), knoepfe, felder.ort);
  };
  const weitere = el('div', { hidden: true }, andere.map(zeile));
  await L.dialog({
    titel: 'Tag abschließen', knopf: 'Tag abschließen', abbrechen: 'Später',
    inhalt: el('div', { class: 'stapel', style: 'gap:4px' }, geplant.map(zeile),
      andere.length ? el('button', { type: 'button', class: 'leicht', style: 'justify-self:start', onclick: ev => { weitere.hidden = false; ev.currentTarget.remove(); } },
        'andere Aufgabe bearbeitet …') : null, weitere,
      el('p', { class: 'leise klein', text: 'Jede laufende Aufgabe braucht mindestens einmal pro Woche eine Farbe. Nachtragen geht im Plan.' })),
    speichern: async form => {
      const rot = [];
      const eintraege = Array.from(form.querySelectorAll('.abschluss-zeile'))
        .filter(d => d.querySelector('input[type=checkbox]').checked).map(d => {
          const e = { aufgabe_id: Number(d.dataset.aufgabe), ampel: wahl[d.dataset.aufgabe] };
          if (e.ampel === 'r') {
            const kz = d.querySelector('b').textContent;
            try { e.problem = problemPruefen(probleme[d.dataset.aufgabe].lesen()); } catch (f) { throw new Error(kz + ': ' + f.message); }
            rot.push(e.problem);
          }
          return e;
        });
      await schritt('/abschluss', { eintraege });
      rot.forEach(nachProblem);
      return true;
    },
  });
}

// --- Aufgabe öffnen, fertig melden ---

async function aufgabeOeffnen(r, g) {
  const p = paketVon(r);
  const gruppe = g || (p && r.wahlgruppe_id ? p.zeilen.find(x => x.typ === 'gruppe' && x.id === r.wahlgruppe_id) : null);
  const tage = l => l.length ? l.map(d => L.tag(d)).join(', ') : '–';
  const ist = Object.keys(r.ist).sort();
  const emp = (r.empfehlungen || []);
  let folge = null;
  const weitere = [];
  if (r.status === 'fertig' && r.meldung) weitere.push({ text: 'Meldung zurückziehen', speichern: () => (folge = 'zurueck') });
  const einheit = r.einheit && z.einheiten ? z.einheiten[r.einheit] : null;
  if (einheit && meldbar(r)) weitere.push({ text: einheit.team ? 'Team' : einheit.selbst ? 'Team finden' : 'Team', speichern: () => (folge = 'team') });
  if (r.art === 'wahl' && !['fertig', 'angenommen'].includes(r.status)) weitere.push({ text: r.gewaehlt ? 'abwählen' : 'wählen', speichern: () => (folge = 'wahl') });
  const blatt = r.gewaehlt && meldbar(r) ? planKacheln(r) : null;
  const ok = await L.dialog({
    titel: r.kuerzel + ' ' + r.titel,
    knopf: meldbar(r) ? 'Fertig melden' : null, abbrechen: 'Schließen', weitere,
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('div', { class: 'zeile' }, r.gewaehlt ? Raster.statusChip(r) : el('span', { class: 'chip', text: 'nicht gewählt' }),
        el('span', { class: 'leise klein', text: [p ? p.titel : '', r.art === 'pflicht' ? 'Pflicht' : r.art === 'wahl' ? 'Wahl' + (gruppe ? ' ' + gruppe.buchstabe : '') : 'Zusatzaufgabe'].filter(Boolean).join(' · ') })),
      el('div', { class: 'daten-liste' },
        el('div', {}, el('span', { text: 'Frist' }), el('b', { text: r.wirksam ? L.tag(r.wirksam) + (r.eigene_frist ? ' (deine neue Frist)' : '') : 'keine' })),
        el('div', {}, el('span', { text: 'Geplant' }), el('b', { text: tage(r.plan) })),
        el('div', {}, el('span', { text: 'Bearbeitet' }), el('b', {}, ist.length ? ist.map(d => el('span', { class: 'ist-tag' }, el('i', { class: 'ampel a-' + r.ist[d] }), L.tag(d))) : '–')),
        r.meldung ? el('div', {}, el('span', { text: 'Fertig gemeldet' }), el('b', { text: L.wann(r.meldung.zeit) })) : null),
      blatt ? blatt.ort : null,
      emp.length ? el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Empfohlen' }),
        emp.map(e => el('div', { class: 'emp-zeile' + (e.erledigt ? ' erledigt' : '') },
          el('div', {}, el('b', { text: e.verbindlich ? 'verbindlich' + (e.wirksam ? ' bis ' + L.tag(e.wirksam) : '') : 'freiwillig' }),
            e.hinweis ? ' · ' + e.hinweis : '', el('div', { class: 'leise klein', text: 'von ' + e.verfasser })),
          el('button', { type: 'button', class: 'klein', onclick: async ev => {
            try { z = await api('/empfehlung', { empfehlung_id: e.id, erledigt: !e.erledigt }); ev.currentTarget.closest('dialog').dispatchEvent(new Event('cancel')); zeigen(); }
            catch (f) { L.meldung(f.message, true); }
          } }, e.erledigt ? 'wieder offen' : 'erledigt')))) : null,
      r.team ? el('div', { class: 'banner team-banner' }, L.symbol('klassen'), ' ' + r.team.name + ': Ihr bearbeitet ' + r.kuerzel + ' gemeinsam' + (r.team.partner ? ' mit ' + r.team.partner : '')
        + '. Plan und Fertigmeldung gelten für alle, deine Farben und deine Kann-Liste bleiben deine.') : null,
      r.moodle_link ? el('a', { class: 'knopf', style: 'justify-self:start', href: r.moodle_link, target: '_blank', rel: 'noopener' }, L.symbol('extern'), 'Aufgabe in Moodle öffnen') : null,
      r.status === 'angenommen' ? el('p', { class: 'leise klein', text: 'Diese Aufgabe ist angenommen.' }) : null),
    speichern: () => (folge = folge || 'fertig'),
  });
  if (blatt && blatt.geaendert()) zeigen();
  if (!ok) return;
  if (folge === 'team') teamBlatt(einheit);
  else if (folge === 'fertig') fertigMelden(r);
  else if (folge === 'wahl') wahlFragen(r, gruppe);
  else if (folge === 'zurueck') {
    const ja = await L.dialog({ titel: 'Meldung zurückziehen?', knopf: 'Zurückziehen',
      inhalt: el('p', { text: r.kuerzel + ' steht dann wieder „in Arbeit“. Melde dich wieder fertig, wenn du so weit bist.' }),
      speichern: () => schritt('/fertig/zurueck', { meldung_id: r.meldung.id }) });
    if (ja) L.meldung('Zurückgezogen.');
  }
}

// Planungsblatt: alle kommenden Unterrichtstage als Kacheln, ein Tipp plant oder entfernt den Tag sofort
function planKacheln(r) {
  let geaendert = false;
  const tage = z.spalten.filter(t => t.datum >= z.heute && t.status !== 'ferien');
  const vorherFehlt = r.kann_stand === 'vorher';
  const werte = {};
  r.kann_liste.forEach(k => { if (k.vorher) werte[k.id] = k.vorher; });
  const kachel = t => {
    const frei = t.status === 'unterricht' || t.status === 'ohne';
    const k = el('button', { type: 'button', disabled: !frei,
      class: 'tk' + (r.plan.includes(t.datum) ? ' an' : '') + (t.status === 'ohne' ? ' ohne' : '') + (frei ? '' : ' aus') + (r.wirksam === t.datum ? ' tk-frist' : ''),
      title: frei ? null : t.grund, onclick: async () => {
        const an = k.classList.toggle('an');
        try {
          z = await api('/plan', { aufgabe_id: r.id, hinzu: an ? [t.datum] : [], weg: an ? [] : [t.datum] });
          geaendert = true;
          const neu = alleZeilen().find(x => x.id === r.id);
          if (neu) r.plan = neu.plan;
        } catch (e) { k.classList.toggle('an'); L.meldung(e.message, true); }
      } },
    el('span', { text: t.tag }), el('b', { text: t.datum.slice(8, 10) + '.' + t.datum.slice(5, 7) + '.' }),
    r.wirksam === t.datum ? el('i', { text: 'Frist' }) : !frei ? el('i', { text: 'fällt aus' }) : null);
    return k;
  };
  const kachelOrt = tage.length ? el('div', { class: 'kacheln' + (vorherFehlt ? ' gesperrt' : '') }, tage.map(kachel))
    : el('p', { class: 'leise klein', text: 'Keine kommenden Unterrichtstage.' });
  let vorherOrt = null;
  if (vorherFehlt) {
    const fertig = el('button', { type: 'button', class: 'haupt klein', style: 'justify-self:start', onclick: async () => {
      if (r.kann_liste.some(k => !werte[k.id])) { L.meldung('Bitte schätze jede Kann-Aussage ein.', true); return; }
      try {
        for (const k of r.kann_liste) z = await api('/kann', { kann_id: k.id, aufgabe_id: r.id, stufe: werte[k.id] });
        geaendert = true;
        vorherOrt.remove();
        kachelOrt.classList.remove('gesperrt');
        const neu = alleZeilen().find(x => x.id === r.id);
        if (neu) r.kann_stand = neu.kann_stand;
      } catch (e) { L.meldung(e.message, true); }
    } }, 'Speichern, dann Tage wählen');
    vorherOrt = el('div', { class: 'stapel vorher-block', style: 'gap:8px' }, el('div', { class: 'etikett', text: 'Erst die Kann-Liste vorher: wie gut kannst du das jetzt schon?' }),
      r.kann_liste.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text), L.skala(werte[k.id], stufe => { werte[k.id] = stufe; }, zahlen()))), fertig);
  }
  const ort = el('div', { class: 'stapel', style: 'gap:6px' }, vorherOrt, el('div', { class: 'etikett', text: 'Planen: Tage antippen' }), kachelOrt);
  return { ort, geaendert: () => geaendert };
}

async function fertigMelden(r) {
  if (r.kann_stand === 'vorher') {
    if (!(await kannVorherFragen(r, 'melden'))) { zeigen(); return; }
    r = alleZeilen().find(x => x.id === r.id) || r;   // mit den gerade gespeicherten Werten „vorher“
  }
  const kann = r.kann_liste || [];
  const werte = {};
  kann.forEach(k => { if (k.nachher) werte[k.id] = k.nachher; });
  const hochgeladen = el('input', { type: 'checkbox', required: !!r.moodle_link });
  const ok = await L.dialog({
    titel: r.kuerzel + ' ' + r.titel + ' fertig melden', knopf: 'Fertig melden',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      r.team ? el('div', { class: 'banner team-banner', text: 'Ihr meldet als Team. ' + (r.team.partner || 'Die anderen') + ' bestätigen danach selbst mit ihrer Kann-Liste; erst dann sieht eure Lehrkraft die Meldung.' }) : null,
      r.moodle_link ? el('label', { class: 'haken' }, hochgeladen, r.team ? 'Unsere Abgabe ist in Moodle hochgeladen' : 'Meine Abgabe ist in Moodle hochgeladen') : null,
      kann.length ? el('div', { class: 'stapel', style: 'gap:8px' }, el('div', { class: 'etikett', text: 'Wie sicher bist du jetzt?' }),
        zahlen() ? el('div', { class: 'leise klein', text: '1 = muss noch viel üben · 4 = kann es perfekt' }) : null,
        kann.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text),
          k.vorher ? el('div', { class: 'leise klein', text: 'Vorher: ' + L.stufeText(k.vorher, zahlen()) }) : null,
          L.skala(werte[k.id], stufe => { werte[k.id] = stufe; }, zahlen()))))
        : el('p', { class: 'leise', text: 'Deine Lehrkraft sieht die Meldung sofort und bespricht die Aufgabe mit dir.' })),
    speichern: () => {
      if (kann.some(k => !werte[k.id])) throw new Error('Bitte schätze jede Kann-Aussage ein.');
      return schritt('/fertig', { aufgabe_id: r.id, kann: werte });
    },
  });
  if (ok) L.meldung(r.kuerzel + ' ist fertig gemeldet. Deine Lehrkraft meldet sich.');
}

// --- Zweierteams ---

// --- Lernteams ---

const TEAM_HINWEIS = 'Ihr plant gemeinsam und meldet gemeinsam fertig. Deine Farben, deine Kann-Liste und dein Gelingensnachweis bleiben deine.';

function groesseText(e) {
  return e.min && e.max ? (e.min === e.max ? e.min + ' Personen' : e.min + ' bis ' + e.max + ' Personen') : '';
}

function mitgliedChip(m) {
  return el('span', { class: 'mg' + (m.status === 'eingeladen' ? ' wartet' : '') }, el('i', { class: 'av', text: m.name.split(' ').map(x => x[0]).join('').slice(0, 2) }),
    m.name + (m.status === 'eingeladen' ? ' · eingeladen' : ''));
}

// e: Einheit aus z.einheiten (Paket, Wahlgruppe, Aufgabe oder Stammteams)
async function teamBlatt(e) {
  if (!e) return;
  if (e.team) { await teamZeigen(e); return; }
  if (!e.selbst) {
    await L.dialog({ titel: 'Team · ' + e.titel, knopf: 'OK', abbrechen: null,
      inhalt: el('p', { text: 'Für ' + e.titel + ' bildet deine Lehrkraft die Teams. Du siehst dein Team hier, sobald sie es eingetragen hat.' }) });
    return;
  }
  let f;
  try { f = await api('/team?einheit=' + encodeURIComponent(e.schluessel)); } catch (x) { L.meldung(x.message, true); return; }
  const name = 'art' + Math.random().toString(36).slice(2);
  const nurEinladung = el('input', { type: 'radio', name, checked: true }), offen = el('input', { type: 'radio', name });
  const kaesten = f.frei.map(m => el('label', { class: 'haken klein' }, el('input', { type: 'checkbox', value: m.id }), m.name));
  const ok = await L.dialog({
    titel: 'Team finden · ' + e.titel, knopf: 'Team gründen',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('div', { class: 'banner team-banner', text: (e.modus === 'pflicht' ? 'Ihr arbeitet hier im Team' + (groesseText(e) ? ' (' + groesseText(e) + ')' : '') + '. '
        + (e.stichtag ? 'Findet euer Team bis ' + L.tag(e.stichtag) + ' ' : '') : 'Ihr dürft hier im Team arbeiten' + (groesseText(e) ? ' (' + groesseText(e) + ')' : '') + '. Allein geht auch. ')
        + TEAM_HINWEIS }),
      f.offen.length ? el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Offene Teams zum Beitreten' }),
        f.offen.map(t => el('div', { class: 'team-k offen-t' }, el('div', { class: 'zeile' }, el('b', { text: t.name }),
          el('span', { class: 'leise klein', text: (e.max - t.anzahl) + (e.max - t.anzahl === 1 ? ' Platz frei' : ' Plätze frei') }),
          el('span', { class: 'rechts' }, L.nebenknopf('beitreten', async () => {
            try { await schritt('/team/beitreten', { team_id: t.id }); L.meldung('Du bist jetzt in ' + t.name + '.'); } catch (x) { L.meldung(x.message, true); }
          }, 'klein haupt'))),
          el('div', { class: 'mitglieder' }, t.mitglieder.map(mitgliedChip))))) : null,
      el('div', { class: 'etikett', text: f.offen.length ? 'Oder ein eigenes Team gründen' : 'Ein eigenes Team gründen' }),
      el('label', { class: 'haken' }, nurEinladung, 'nur auf Einladung (du lädst ein, jeder bestätigt selbst)'),
      el('label', { class: 'haken' }, offen, 'offen zum Beitreten (jeder aus der Klasse kann beitreten, bis das Team voll ist)'),
      el('div', { class: 'etikett', text: 'Einladen' + (e.max ? ' (höchstens ' + (e.max - 1) + ')' : '') }),
      kaesten.length ? el('div', { class: 'stapel', style: 'gap:4px;max-height:34vh;overflow:auto' }, kaesten) : el('p', { class: 'leise klein', text: 'Alle anderen sind schon in einem Team.' })),
    speichern: form => {
      const ids = Array.from(form.querySelectorAll('input[type=checkbox]:checked'), c => Number(c.value));
      if (e.max && ids.length > e.max - 1) throw new Error('Ein Team hat hier höchstens ' + e.max + ' Personen.');
      return schritt('/team/gruenden', { bereich: e.bereich, bezug_id: e.bezug_id, offen: offen.checked, einladen: ids });
    },
  });
  if (ok) L.meldung('Team gegründet. Eingeladene sind dabei, sobald sie annehmen.');
}

async function teamZeigen(e) {
  const t = e.team;
  const selbst = e.selbst && t.quelle === 'schueler';
  let frei = [];
  if (selbst) { try { frei = (await api('/team?einheit=' + encodeURIComponent(e.schluessel))).frei; } catch (x) { frei = []; } }
  const platz = e.max ? e.max - t.mitglieder.length : 0;
  const kaesten = platz > 0 ? frei.map(m => el('label', { class: 'haken klein' }, el('input', { type: 'checkbox', value: m.id }), m.name)) : [];
  const ich = t.mitglieder.find(m => m.austritt);
  const offen = el('input', { type: 'checkbox', checked: t.offen, onchange: async ev => {
    try { await api('/team/offen', { team_id: t.id, offen: ev.target.checked }); } catch (x) { L.meldung(x.message, true); }
  } });
  const ok = await L.dialog({
    titel: t.name + ' · ' + e.titel, knopf: kaesten.length ? 'Einladen' : null, abbrechen: 'Schließen',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('div', { class: 'mitglieder' }, t.mitglieder.map(mitgliedChip)),
      el('p', { class: 'leise klein', text: TEAM_HINWEIS }),
      selbst ? el('label', { class: 'haken' }, offen, 'offen zum Beitreten') : null,
      kaesten.length ? el('div', { class: 'stapel', style: 'gap:4px' }, el('div', { class: 'etikett', text: 'Weitere einladen (' + platz + (platz === 1 ? ' Platz frei)' : ' Plätze frei)') }),
        el('div', { class: 'stapel', style: 'gap:4px;max-height:30vh;overflow:auto' }, kaesten)) : null,
      el('div', { class: 'zeile' },
        L.nebenknopf('Nachricht ans Team', () => { location.hash = 'rueck'; }, 'klein'),
        selbst && !ich ? L.nebenknopf('Team verlassen …', () => austrittFragen(t), 'klein warnen') : null),
      ich ? el('div', { class: 'banner zeile' }, el('span', { text: 'Du hast angefragt, das Team zu verlassen: „' + ich.austritt + '“. Deine Lehrkraft entscheidet.' }),
        L.nebenknopf('Anfrage zurückziehen', async () => { try { await schritt('/team/austritt', { team_id: t.id, zurueck: true }); } catch (x) { L.meldung(x.message, true); } }, 'klein rechts')) : null,
      selbst ? null : el('p', { class: 'leise klein', text: 'Dieses Team hat deine Lehrkraft gebildet. Wechseln geht nur über sie.' })),
    speichern: form => {
      const ids = Array.from(form.querySelectorAll('input[type=checkbox][value]:checked'), c => Number(c.value));
      if (!ids.length) throw new Error('Bitte jemanden zum Einladen wählen.');
      return schritt('/team/einladen', { team_id: t.id, einladen: ids });
    },
  });
  if (ok) L.meldung('Eingeladen.');
  else zeigen();
}

async function austrittFragen(t) {
  const grund = el('textarea', { rows: 2, maxlength: 300, required: true, placeholder: 'Warum möchtest du das Team verlassen?' });
  const ok = await L.dialog({ titel: t.name + ' verlassen?', knopf: 'Anfrage schicken',
    inhalt: el('div', { class: 'stapel', style: 'gap:8px' }, el('p', { text: 'Deine Lehrkraft entscheidet. Bis dahin bleibst du im Team. Dein bisheriger Plan bleibt dir.' }), grund),
    speichern: () => schritt('/team/austritt', { team_id: t.id, grund: grund.value }) });
  if (ok) L.meldung('Anfrage geschickt.');
}

async function einladungFragen(t) {
  const andere = t.mitglieder.filter(m => m.status === 'aktiv').map(m => m.name).join(', ');
  const ok = await L.dialog({
    titel: 'Einladung ins ' + t.name, knopf: 'Team beitreten', abbrechen: 'Ablehnen',
    inhalt: el('div', { class: 'stapel', style: 'gap:8px' }, el('p', {}, el('b', { text: andere }), ' möchte' + (andere.includes(',') ? 'n' : '') + ' ' + t.titel + ' mit dir im Team bearbeiten.'),
      el('div', { class: 'mitglieder' }, t.mitglieder.map(mitgliedChip)),
      el('p', { class: 'leise klein', text: 'Eure Pläne werden zusammengelegt. ' + TEAM_HINWEIS })),
    speichern: () => schritt('/team/antwort', { team_id: t.id, annehmen: true }),
  });
  if (ok) L.meldung('Du bist jetzt in ' + t.name + '.');
  else { try { await schritt('/team/antwort', { team_id: t.id, annehmen: false }); } catch (e) { L.meldung(e.message, true); } }
}

// Fertigmeldung des Teams bestätigen (mit der eigenen Kann-Liste „nachher“); Rückgabe false bei „Später“
async function bestaetigenFragen(b) {
  let r = alleZeilen().find(x => x.id === b.aufgabe_id);
  if (r && r.kann_liste.some(k => !k.vorher)) {
    if (!(await kannVorherFragen(r, 'melden'))) return false;
    r = alleZeilen().find(x => x.id === b.aufgabe_id) || r;
  }
  const kann = r ? r.kann_liste : [];
  const werte = {};
  kann.forEach(k => { if (k.nachher) werte[k.id] = k.nachher; });
  const ok = await L.dialog({
    titel: b.von + ' hat ' + b.kuerzel + ' fertig gemeldet', knopf: 'Bestätigen', abbrechen: 'Später',
    weitere: [{ text: 'Noch nicht fertig', speichern: () => 'nicht' }],
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('p', { text: 'Bestätigst du, dass ihr mit ' + b.kuerzel + ' ' + b.titel + ' fertig seid? Erst wenn alle bestätigt haben, sieht eure Lehrkraft die Meldung.' }),
      el('div', { class: 'mitglieder' }, b.mitglieder.map(m => el('span', { class: 'mg' + (m.bestaetigt ? '' : ' wartet') }, m.ich ? 'du' : m.name, m.bestaetigt ? ' ✓' : ''))),
      kann.length ? el('div', { class: 'stapel', style: 'gap:8px' }, el('div', { class: 'etikett', text: 'Wie sicher bist du jetzt?' }),
        kann.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text),
          k.vorher ? el('div', { class: 'leise klein', text: 'Vorher: ' + L.stufeText(k.vorher, zahlen()) }) : null,
          L.skala(werte[k.id], stufe => { werte[k.id] = stufe; }, zahlen())))) : null),
    speichern: () => {
      if (kann.some(k => !werte[k.id])) throw new Error('Bitte schätze jede Kann-Aussage ein.');
      return schritt('/fertig/bestaetigen', { meldung_id: b.meldung_id, kann: werte });
    },
  });
  if (ok === 'nicht') {
    const text = el('textarea', { rows: 2, maxlength: 400, placeholder: 'Was fehlt noch? (wahlweise)' });
    const gesendet = await L.dialog({ titel: 'Noch nicht fertig', knopf: 'An das Team schicken',
      inhalt: el('div', { class: 'stapel', style: 'gap:8px' }, el('p', { text: 'Dein Team bekommt eine Nachricht. Die Meldung wartet weiter, bis alle bestätigen oder sie zurückgezogen wird.' }), text),
      speichern: () => schritt('/fertig/nochnicht', { meldung_id: b.meldung_id, text: text.value }) });
    if (gesendet) L.meldung('Nachricht an dein Team geschickt.');
    return true;
  }
  if (ok) L.meldung('Bestätigt.');
  return !!ok;
}

// --- Feedbacktermine ---

// n: Gelingensnachweis (Fachgespräch / praktische Prüfung) mit aktuellem Versuch; ohne n: Feedbacktermin
async function terminBuchen(n) {
  const art = n ? n.art : 'feedback';
  let plaetze;
  try { plaetze = (await api('/plaetze?art=' + art)).plaetze; }
  catch (e) { L.meldung(e.message, true); return; }
  if (!plaetze.length) {
    await L.dialog({ titel: n ? n.art_text + ' buchen' : 'Feedbacktermin', knopf: 'OK', abbrechen: null,
      inhalt: el('p', { text: 'Gerade gibt es keine freien ' + (n ? 'Prüfungszeiten' : 'Sprechzeiten') + '. Schau später noch einmal oder sprich deine Lehrkraft an.' }) });
    return;
  }
  const meineTeams = Object.values(z.einheiten || {}).filter(e => e.team);
  const anlass = el('select', { required: true }, el('option', { value: '', text: 'Worum geht es?' }),
    meineTeams.length ? el('optgroup', { label: 'Mit meinem Team' }, meineTeams.map(e => el('option', { value: 'team' + e.team.id,
      text: e.team.name + ' (' + e.titel + ')' }))) : null,
    z.pakete.map(p => el('optgroup', { label: p.titel },
      p.zeilen.filter(r => r.typ === 'aufgabe' && r.gewaehlt).map(r => el('option', { value: 'a' + r.id, text: r.kuerzel + ' ' + r.titel })),
      el('option', { value: 'p' + p.id, text: 'das ganze Paket' }))),
    el('option', { value: 't', text: 'etwas anderes …' }));
  const text = el('input', { maxlength: 200, placeholder: 'kurz, worum es geht' });
  const textFeld = L.feld('Anlass', text);
  textFeld.hidden = true;
  const anlassFeld = n ? null : L.feld('Anlass', anlass);
  anlass.addEventListener('change', () => { textFeld.hidden = anlass.value !== 't'; });
  let wahl = null;
  const ok = el('span');
  const tage = el('div', { class: 'stapel', style: 'gap:10px' }, plaetze.map(t => el('div', { class: 'stapel', style: 'gap:4px' },
    el('div', { class: 'etikett', text: L.tag(t.datum) + ' · bei ' + t.lehrkraft + ' · ' + t.dauer + ' min' }),
    el('div', { class: 'slots' }, t.plaetze.map(b => el('button', { type: 'button', text: b, onclick: ev => {
      wahl = { zeitfenster_id: t.zeitfenster_id, datum: t.datum, beginn: b };
      tage.querySelectorAll('.slots button').forEach(x => x.classList.toggle('an', x === ev.currentTarget));
      ok.textContent = L.tag(t.datum) + ' · ' + b;
    } }))))));
  const erfolg = await L.dialog({
    titel: n ? n.art_text + (n.titel ? ' ' + n.titel : '') + ' buchen' : 'Feedbacktermin buchen', knopf: 'Buchen',
    inhalt: el('div', { class: 'stapel', style: 'gap:12px' }, anlassFeld, n ? null : textFeld,
      el('p', { class: 'leise klein', text: n ? 'Nur in der Prüfungszeit, nur freie Zeiten. Absagen kannst du bis zum Vortag.'
        : 'Nur freie Zeiten in der Sprechzeit. Ein offener Termin zur Zeit, absagen kannst du bis zum Vortag.' }),
      tage, el('div', { class: 'zeile' }, el('span', { class: 'leise klein', text: 'gewählt: ' }), ok)),
    speichern: () => {
      if (!wahl) throw new Error('Bitte eine Uhrzeit wählen.');
      if (n) return schritt('/termin', Object.assign({ art, anlass: { versuch_id: n.aktuell.id } }, wahl));
      const v = anlass.value;
      if (!v) throw new Error('Bitte den Anlass wählen.');
      const a = v.startsWith('team') ? { team_id: Number(v.slice(4)) } : v.startsWith('a') ? { aufgabe_id: Number(v.slice(1)) }
        : v.startsWith('p') ? { paket_id: Number(v.slice(1)) } : { text: text.value };
      return schritt('/termin', Object.assign({ art: 'feedback', anlass: a }, wahl));
    },
  });
  if (erfolg) L.meldung('Termin gebucht: ' + ok.textContent);
}

async function absagen(t) {
  await L.dialog({ titel: 'Termin absagen?', knopf: 'Absagen', gefaehrlich: true,
    inhalt: el('p', { text: L.tag(t.datum) + ' · ' + t.beginn + ' · ' + t.anlass + '. Der Platz wird für andere frei.' }),
    speichern: () => schritt('/termin/absagen', { termin_id: t.id }) });
}

// --- Gelingensnachweise ---

function ergebnisText(n, v) {
  const wert = v.punkte !== null && v.punkte !== undefined ? String(v.punkte).replace('.', ',') + (n.max_punkte ? ' von ' + n.max_punkte + ' Punkten' : ' Punkte')
    : v.note ? 'Note ' + v.note : '';
  return (v.status === 'gelungen' ? 'gelungen' : 'noch nicht gelungen') + (wert ? ' · ' + wert : '');
}

function gnZeigen() {
  const liste = alleNachweise();
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Gelingensnachweise' }),
    liste.length ? null : el('div', { class: 'leer', text: 'Für deine Pakete gibt es noch keinen Gelingensnachweis.' }),
    liste.map(n => {
      const v = n.aktuell;
      const p = z.pakete.find(x => x.id === n.paket_id);
      let stand;
      if (n.gelungen) {
        const g = n.versuche.find(x => x.status === 'gelungen');
        stand = el('div', { class: 'banner gruen', text: 'Gelungen am ' + L.tag(g.ergebnis_zeit) + (ergebnisText(n, g).includes('·') ? ' · ' + ergebnisText(n, g).split(' · ')[1] : '') });
      } else if (v && v.termin) {
        stand = el('div', { class: 'termin-zeile' }, el('div', {}, el('b', { text: L.tag(v.termin.datum) + ' · ' + v.termin.beginn }), ' · ' + n.art_text,
          el('div', { class: 'leise klein', text: 'bei ' + v.termin.lehrkraft + (v.termin.datum > z.heute ? ' · absagen bis ' + L.tag(prevTag(v.termin.datum)) : '') })),
        v.termin.datum > z.heute ? el('button', { type: 'button', class: 'klein', text: 'absagen',
          onclick: () => absagen({ id: v.termin.id, datum: v.termin.datum, beginn: v.termin.beginn, anlass: n.art_text }) }) : null);
      } else if (v && v.status === 'frei') {
        stand = el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'banner', text: 'Der Test ist in Moodle freigeschaltet. Viel Erfolg!' }),
          n.moodle_link ? el('a', { class: 'knopf haupt', style: 'justify-self:start', href: n.moodle_link, target: '_blank', rel: 'noopener' }, L.symbol('extern'), 'Test in Moodle öffnen') : null);
      } else if (v) {
        stand = n.art === 'moodle'
          ? el('div', { class: 'banner', text: 'Du bist bereit gemeldet (' + L.wann(v.bereit) + '). Deine Lehrkraft schaltet den Test in Moodle frei.' })
          : el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'banner', text: 'Du bist bereit gemeldet. Buche jetzt einen Termin in der Prüfungszeit.' }),
            el('button', { type: 'button', class: 'haupt', style: 'justify-self:start', onclick: () => terminBuchen(n) }, L.symbol('uhr'), n.art_text + ' buchen'));
      } else {
        stand = el('div', { class: 'stapel', style: 'gap:6px' },
          n.kann_gesamt ? el('div', { class: 'leise klein', text: 'Kann-Liste: ' + n.kann_nachher + ' von ' + n.kann_gesamt + ' „nachher“ eingeschätzt. Beim Bereitmelden schätzt du alle ein.' }) : null,
          el('button', { type: 'button', class: 'haupt', style: 'justify-self:start', onclick: () => bereitMelden(n, p) }, L.symbol('haken'),
            n.versuche.length ? 'Wieder bereit melden' : 'Ich bin bereit'));
      }
      return el('div', { class: 'karte stapel gn-karte' },
        el('div', { class: 'zeile' }, el('b', { class: 'ik gn klein-ik' }, L.symbol('gn')),
          el('div', {}, el('b', { text: n.art_text + (n.titel ? ' · ' + n.titel : '') }), el('div', { class: 'leise klein', text: n.paket })),
          el('span', { class: 'rechts' }, n.wirksam && !n.gelungen ? el('span', { class: 'chip' + (n.ueber_frist ? ' rot' : ''),
            text: 'bis ' + L.tag(n.wirksam) + (n.eigene_frist ? ' (neue Frist)' : '') }) : null)),
        stand,
        v && !v.termin && !n.gelungen ? el('button', { type: 'button', class: 'leicht klein', style: 'justify-self:start', onclick: () => bereitZurueck(n) }, 'Bereitmeldung zurückziehen') : null,
        n.versuche.filter(x => x.status === 'gelungen' || x.status === 'nicht').length ? el('div', { class: 'stapel', style: 'gap:6px' },
          el('div', { class: 'etikett', text: 'Deine Versuche' }),
          n.versuche.filter(x => x.status === 'gelungen' || x.status === 'nicht').map(x => el('div', { class: 'versuch ' + x.status },
            el('div', { class: 'zeile' }, el('b', { text: x.nr + '. Versuch' }), el('span', { class: 'sc ' + (x.status === 'gelungen' ? 'angenommen' : 'ueberarbeiten'), text: ergebnisText(n, x) }),
              el('span', { class: 'leise klein', text: L.tag(x.ergebnis_zeit) + (x.ergebnis_von ? ' · ' + x.ergebnis_von : '') })),
            x.text ? el('p', { class: 'rm-text klein', text: x.text }) : null,
            x.status === 'nicht' && x.neue_frist ? el('div', { class: 'leise klein', text: 'Neue Frist: ' + L.tag(x.neue_frist) + '. Schau dir deine Empfehlungen unter „Rückmeldungen“ an.' }) : null))) : null);
    }));
}

function prevTag(iso) {
  const d = new Date(iso + 'T12:00:00');
  d.setDate(d.getDate() - 1);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

async function bereitMelden(n, p) {
  const kann = p ? p.kann : [];
  const werte = {};
  kann.forEach(k => { if (k.nachher) werte[k.id] = k.nachher; });
  const ok = await L.dialog({
    titel: 'Bereit für ' + n.art_text + (n.titel ? ' ' + n.titel : '') + '?', knopf: 'Ich bin bereit',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('p', { class: 'leise klein', text: n.art === 'moodle' ? 'Deine Lehrkraft schaltet danach den Test in Moodle frei.'
        : 'Danach buchst du einen Termin in der Prüfungszeit.' }),
      kann.length ? el('div', { class: 'stapel', style: 'gap:8px' }, el('div', { class: 'etikett', text: 'Wie sicher bist du jetzt? (alle Aussagen)' }),
        zahlen() ? el('div', { class: 'leise klein', text: '1 = muss noch viel üben · 4 = kann es perfekt' }) : null,
        kann.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text),
          k.vorher ? el('div', { class: 'leise klein', text: 'Vorher: ' + L.stufeText(k.vorher, zahlen()) }) : null,
          L.skala(werte[k.id], stufe => { werte[k.id] = stufe; }, zahlen())))) : null),
    speichern: () => {
      if (kann.some(k => !werte[k.id])) throw new Error('Bitte schätze jede Kann-Aussage ein.');
      return schritt('/bereit', { nachweis_id: n.id, kann: werte });
    },
  });
  if (!ok) return;
  L.meldung('Du bist bereit gemeldet.');
  const neu = alleNachweise().find(x => x.id === n.id);
  if (neu && neu.art !== 'moodle' && neu.aktuell && !neu.aktuell.termin) terminBuchen(neu);
}

async function bereitZurueck(n) {
  await L.dialog({ titel: 'Bereitmeldung zurückziehen?', knopf: 'Zurückziehen',
    inhalt: el('p', { text: 'Du kannst dich jederzeit wieder bereit melden.' }),
    speichern: () => schritt('/bereit/zurueck', { versuch_id: n.aktuell.id }) });
}

// --- Rückmeldungen ---

function nachrichtenKarte(v) {
  const text = el('textarea', { rows: 2, maxlength: 2000, placeholder: v.team_id ? 'Antwort an Team und Lehrkraft …' : 'Nachricht an deine Lehrkraft …' });
  const fluss = el('div', { class: 'nachrichten' }, v.nachrichten.length ? v.nachrichten.map(n => el('div', { class: 'nachricht' + (n.ich ? ' ich' : '') },
    el('small', { text: (n.ich ? 'du' : n.von) + ' · ' + L.wann(n.zeit) }), el('span', { class: 'nl', text: n.text })))
    : el('p', { class: 'leise klein', text: v.team_id ? 'Noch keine Nachricht im Team.' : 'Noch keine Nachricht. Hier kannst du deiner Lehrkraft schreiben.' }));
  setTimeout(() => { fluss.scrollTop = fluss.scrollHeight; }, 0);
  return el('div', { class: 'karte stapel nachrichten-karte' + (v.ungelesen ? ' neu' : '') },
    el('div', { class: 'zeile' }, v.team_id ? el('b', { class: 'ik rueck klein-ik' }, L.symbol('klassen')) : el('b', { class: 'ik rueck klein-ik' }, L.symbol('rueck')),
      el('div', {}, el('b', { text: v.titel }), el('div', { class: 'leise klein', text: v.unter })),
      v.ungelesen ? el('span', { class: 'chip rot rechts', text: v.ungelesen === 1 ? 'neu' : v.ungelesen + ' neu' }) : null),
    fluss,
    el('form', { class: 'zeile', onsubmit: async ev => {
      ev.preventDefault();
      if (!text.value.trim()) return;
      try { await api('/nachrichten', { text: text.value, team_id: v.team_id || undefined }); rueckZeigen(); } catch (x) { L.meldung(x.message, true); }
    } }, text, el('button', { type: 'submit', class: 'haupt' }, 'Senden')));
}

async function rueckZeigen() {
  L.setzen(inhalt, el('h1', { class: 'dreieck', text: 'Rückmeldungen' }), el('p', { class: 'leise', text: 'Lade …' }));
  let d, nd;
  try { [d, nd] = await Promise.all([api('/rueckmeldungen'), api('/nachrichten')]); } catch (e) { L.setzen(inhalt, el('div', { class: 'leer', text: e.message })); return; }
  const empZeile = e => el('div', { class: 'emp-zeile' + (e.erledigt ? ' erledigt' : '') },
    el('div', {}, el('span', { class: 'chip ' + (e.verbindlich ? 'lila' : 'lila-hell') + ' klein' }, L.symbol('stern'),
      e.verbindlich ? 'verbindlich' + (e.wirksam ? ' bis ' + L.tag(e.wirksam) : '') : 'freiwillig'), ' ',
    e.aufgabe ? (e.aufgabe.moodle_link ? el('a', { class: 'alink', href: e.aufgabe.moodle_link, target: '_blank', rel: 'noopener', text: e.aufgabe.kuerzel + ' ' + e.aufgabe.titel })
      : e.aufgabe.kuerzel + ' ' + e.aufgabe.titel) : '',
    e.hinweis ? el('div', { class: 'leise klein', text: e.hinweis }) : null,
    el('div', { class: 'leise klein', text: e.erledigt ? 'erledigt' : e.aufgabe && e.aufgabe.art === 'zusatz' ? 'steht in deinem Plan unter „Empfohlen für dich“' : 'plane sie in deinem Plan ein' })),
  el('button', { type: 'button', class: 'klein', onclick: async () => {
    try { z = await api('/empfehlung', { empfehlung_id: e.id, erledigt: !e.erledigt }); rueckZeigen(); } catch (f) { L.meldung(f.message, true); }
  } }, e.erledigt ? 'wieder offen' : 'erledigt'));
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Rückmeldungen' }),
    el('div', { class: 'stapel' }, el('h2', { text: 'Nachrichten' }), nd.verlaeufe.map(nachrichtenKarte)),
    el('h2', { text: 'Rückmeldungen' }),
    !d.rueckmeldungen.length && !d.empfehlungen.length ? el('div', { class: 'leer', text: 'Noch keine Rückmeldung. Melde eine Aufgabe fertig oder buche einen Feedbacktermin.' }) : null,
    d.empfehlungen.length ? el('div', { class: 'karte stapel' }, el('h2', { text: 'Empfohlen für dich' }), d.empfehlungen.map(empZeile)) : null,
    d.rueckmeldungen.map(r => el('div', { class: 'karte stapel rm' + (r.gelesen ? '' : ' neu') },
      el('div', { class: 'zeile' }, el('b', { class: 'ik rueck klein-ik' }, L.symbol('rueck')),
        el('div', {}, el('b', { text: r.nachweis ? r.nachweis.titel : r.aufgabe ? r.aufgabe.kuerzel + ' ' + r.aufgabe.titel : r.paket ? 'Paket ' + r.paket : 'Feedback' }),
          el('div', { class: 'leise klein', text: r.verfasser + ' · ' + L.wann(r.freigegeben) })),
        el('span', { class: 'rechts' }, r.gelesen ? null : el('span', { class: 'chip rot', text: 'neu' }),
          r.ergebnis ? el('span', { class: 'sc ' + (r.ergebnis === 'gelungen' ? 'angenommen' : 'ueberarbeiten'), text: r.ergebnis === 'gelungen' ? 'gelungen' : 'noch nicht gelungen' })
            : r.entscheidung === 'angenommen' ? el('span', { class: 'sc angenommen', text: 'angenommen' })
            : r.entscheidung === 'ueberarbeiten' ? el('span', { class: 'sc ueberarbeiten', text: 'überarbeiten bis ' + L.tag(r.neue_frist) }) : null)),
      r.team_text ? el('div', { class: 'stapel', style: 'gap:4px' }, el('div', { class: 'etikett', text: 'An euer Team' }), el('p', { class: 'rm-text', text: r.team_text })) : null,
      r.text ? el('div', { class: 'stapel', style: 'gap:4px' }, r.team_text ? el('div', { class: 'etikett', text: 'Nur für dich' }) : null, el('p', { class: 'rm-text', text: r.text })) : null,
      r.kann.length ? el('div', { class: 'stapel', style: 'gap:4px' }, el('div', { class: 'etikett', text: 'Einschätzung deiner Lehrkraft' }),
        r.kann.map(k => el('div', { class: 'kann-vergleich' }, el('span', { text: 'Ich kann ' + k.text }), el('b', { text: L.stufeText(k.stufe, zahlen()) })))) : null,
      r.empfehlungen.length ? el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Empfehlungen' }), r.empfehlungen.map(empZeile)) : null)));
  if (d.ungelesen) {
    try { z = await api('/rueckmeldungen/gelesen', {}); leisteZahlen(); } catch (e) { /* beim nächsten Mal */ }
  }
  if (nd.ungelesen) {
    try { z = await api('/nachrichten/gelesen', {}); leisteZahlen(); } catch (e) { /* beim nächsten Mal */ }
  }
}

// --- Kann-Liste ---

const KANN_STAND = { vorher: ['vorher', 'vorher ausfüllen'], arbeit: ['arbeit', 'in Arbeit'], nachher: ['nachher', 'nachher ausfüllen'],
  fertig: ['fertig', 'ausgefüllt'], bewertet: ['bewertet', 'Einschätzung der Lehrkraft da'] };
let kannAuswahl = null;

function kannZeigen() {
  const pakete = z.pakete.map(p => ({ p, zeilen: p.zeilen.filter(r => r.typ === 'aufgabe' && r.gewaehlt && r.kann_liste && r.kann_liste.length) }))
    .filter(x => x.zeilen.length);
  const alle = [].concat(...pakete.map(x => x.zeilen));
  let r = alle.find(x => x.id === kannAuswahl);
  if (!r) r = alle.find(x => x.kann_stand === 'nachher') || alle.find(x => x.kann_stand === 'vorher' && x.plan.length) || alle[0];
  kannAuswahl = r ? r.id : null;
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Kann-Liste' }),
    zahlen() ? el('div', { class: 'banner', text: '1 = Ich muss noch viel üben · 2 = Ich brauche noch Hilfe · 3 = Ich kann es meistens allein · 4 = Ich kann es perfekt' }) : null,
    pakete.length ? pakete.map(({ p, zeilen }) => el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: p.titel }),
      el('div', { class: 'kann-kacheln' }, zeilen.map(x => el('button', { type: 'button', class: 'kk' + (x.id === kannAuswahl ? ' an' : ''),
        onclick: () => { kannAuswahl = x.id; kannZeigen(); } },
        el('b', { class: 'mono', text: x.kuerzel }), el('span', { class: 'kk-titel', text: x.titel }),
        el('span', { class: 'ks ' + KANN_STAND[x.kann_stand][0], text: KANN_STAND[x.kann_stand][1] })))))) : null,
    r ? kannKarte(r) : el('div', { class: 'leer', text: 'Für deine Aufgaben gibt es noch keine Kann-Liste.' }));
}

function kannKarte(r) {
  const nachherOffen = ['fertig', 'angenommen'].includes(r.status);
  const vorherOffen = !nachherOffen && r.status !== 'ueberarbeiten' || !r.plan.length;
  const speichern = (k, art) => async stufe => {
    try { z = await api('/kann', { kann_id: k.id, aufgabe_id: r.id, stufe, art }); leisteZahlen(); }
    catch (e) { L.meldung(e.message, true); }
  };
  const hinweis = { vorher: 'Fülle „vorher“ aus, bevor du ' + r.kuerzel + ' planst.', arbeit: '„Nachher“ schätzt du beim Fertigmelden ein.',
    nachher: 'Die Aufgabe ist fertig gemeldet: schätze jetzt „nachher“ ein.', fertig: 'Ausgefüllt. Die Einschätzung deiner Lehrkraft kommt mit der Rückmeldung.',
    bewertet: 'Vergleiche deine Einschätzung mit der deiner Lehrkraft.' }[r.kann_stand];
  return el('div', { class: 'karte stapel' },
    el('div', { class: 'zeile' }, el('h2', { text: r.kuerzel + ' ' + r.titel }), el('span', { class: 'rechts ks ' + KANN_STAND[r.kann_stand][0], text: KANN_STAND[r.kann_stand][1] })),
    el('p', { class: 'leise klein', text: hinweis }),
    r.kann_liste.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text),
      el('div', { class: 'etikett', text: 'Vorher' }),
      vorherOffen ? L.skala(k.vorher, speichern(k, 'vorher'), zahlen()) : el('div', { class: 'klein', text: L.stufeText(k.vorher, zahlen()) }),
      el('div', { class: 'etikett', text: 'Nachher' }),
      nachherOffen ? L.skala(k.nachher, speichern(k, 'nachher'), zahlen())
        : el('div', { class: 'leise klein', text: k.nachher ? L.stufeText(k.nachher, zahlen()) : 'beim Fertigmelden' }),
      el('div', { class: 'etikett', text: 'Deine Lehrkraft' }),
      el('div', { class: k.lehrkraft ? 'klein' : 'leise klein' }, k.lehrkraft ? el('b', { text: L.stufeText(k.lehrkraft, zahlen()) }) : 'noch keine Einschätzung'))));
}

// --- Fragen beim Öffnen: Einladung, Ausfall ---

// Kann-Liste „nachher“ für eine fertig gemeldete Aufgabe, z. B. wenn der Teampartner für beide gemeldet hat
async function kannNachherFragen(r) {
  const werte = {};
  r.kann_liste.forEach(k => { if (k.nachher) werte[k.id] = k.nachher; });
  const ok = await L.dialog({
    titel: 'Kann-Liste ' + r.kuerzel + ' · nachher', knopf: 'Speichern', abbrechen: 'Später',
    inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
      el('p', { text: r.kuerzel + ' ' + r.titel + ' ist fertig gemeldet' + (r.team && r.team.partner ? ' (von euch beiden)' : '') + '. Wie sicher bist du jetzt?' }),
      zahlen() ? el('div', { class: 'leise klein', text: '1 = muss noch viel üben · 4 = kann es perfekt' }) : null,
      r.kann_liste.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text),
        k.vorher ? el('div', { class: 'leise klein', text: 'Vorher: ' + L.stufeText(k.vorher, zahlen()) }) : null,
        L.skala(werte[k.id], stufe => { werte[k.id] = stufe; }, zahlen())))),
    speichern: async () => {
      if (r.kann_liste.some(k => !werte[k.id])) throw new Error('Bitte schätze jede Kann-Aussage ein.');
      for (const k of r.kann_liste) z = await api('/kann', { kann_id: k.id, aufgabe_id: r.id, stufe: werte[k.id], art: 'nachher' });
      return true;
    },
  });
  return !!ok;
}

// Beim Öffnen: fehlende Pflicht-Einschätzungen nachholen (angefangen ohne „vorher“, fertig gemeldet ohne „nachher“)
const kannGefragt = new Set();
async function kannPflichtFragen() {
  const warten = new Set((z.bestaetigen || []).map(b => b.aufgabe_id));
  const offen = alleZeilen().filter(r => r.gewaehlt && !kannGefragt.has(r.id) && !warten.has(r.id) && r.kann_liste && r.kann_liste.length &&
    (r.kann_stand === 'nachher' || (r.kann_stand === 'vorher' && (r.plan.length || Object.keys(r.ist).length))));
  for (const r of offen) {
    kannGefragt.add(r.id);
    const ok = r.kann_stand === 'nachher' ? await kannNachherFragen(r) : await kannVorherFragen(r, 'pflicht');
    if (!ok) break;   // „Später“: in dieser Sitzung nicht weiter fragen
  }
  if (offen.length) zeigen();
}

async function nachfragen() {
  for (const t of (z.einladungen || []).slice()) await einladungFragen(t);
  for (const b of (z.bestaetigen || []).slice()) { if (!(await bestaetigenFragen(b))) break; }
  if (z.hinweise.ausfall.length) {
    const h = z.hinweise.ausfall;
    await L.dialog({
      titel: h.length === 1 ? L.tag(h[0].datum) + (h[0].status === 'ferien' ? ': Ferien' : ' fällt aus') : 'Tage fallen aus',
      knopf: 'Auf den nächsten Unterrichtstag schieben', abbrechen: 'Selbst planen',
      inhalt: el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Dafür hattest du geplant' }),
        h.map(x => el('div', {}, el('b', { text: x.kuerzel }), ' ' + x.titel + ' · ' + L.tag(x.datum) + ' (' + x.grund + ')')),
        el('p', { class: 'leise klein', text: 'Das zählt nicht als deine Verschiebung.' })),
      speichern: () => schritt('/ausfall', { aktion: 'verschieben' }),
    }).then(async r => { if (r === null) { try { await schritt('/ausfall', { aktion: 'selbst' }); location.hash = 'plan'; } catch (e) { L.meldung(e.message, true); } } });
    return;
  }
  if (z.ungelesen && location.hash !== '#rueck') L.meldung(z.ungelesen === 1 ? 'Du hast eine neue Rückmeldung.' : 'Du hast ' + z.ungelesen + ' neue Rückmeldungen.');
  await kannPflichtFragen();
}

async function wahlFragen(r, g) {
  const bisher = g ? z.pakete.flatMap(p => p.zeilen).filter(x => x.typ === 'aufgabe' && x.wahlgruppe_id === g.id && x.gewaehlt && x.id !== r.id) : [];
  if (r.gewaehlt) {
    await L.dialog({
      titel: r.kuerzel + ' abwählen?', knopf: 'Abwählen',
      inhalt: el('p', { text: 'Deine Planung für ' + r.kuerzel + ' ab heute fällt weg. Du kannst danach eine andere Aufgabe der Gruppe wählen.' }),
      speichern: () => schritt('/wahl', { aufgabe_id: r.id, gewaehlt: false }),
    });
    return;
  }
  await L.dialog({
    titel: r.kuerzel + ' ' + r.titel + ' wählen?', knopf: r.kuerzel + ' wählen',
    inhalt: el('div', { class: 'stapel', style: 'gap:8px' },
      g ? el('div', { class: 'leise klein', text: 'Wahlgruppe ' + g.buchstabe + (g.titel ? ' · ' + g.titel : '') + (g.wirksam ? ' · Frist ' + L.tag(g.wirksam) : '') }) : null,
      r.moodle_link ? el('a', { class: 'knopf', style: 'justify-self:start', href: r.moodle_link, target: '_blank', rel: 'noopener' }, L.symbol('extern'), 'Aufgabe erst in Moodle ansehen') : null,
      el('p', { class: 'leise klein', text: bisher.length && g.waehlen === 1
        ? bisher[0].kuerzel + ' wird dafür abgewählt, deine Planung dafür ab heute fällt weg.'
        : 'Die anderen Aufgaben der Gruppe werden blass. Wechseln geht, bis du die Aufgabe fertig meldest.' })),
    speichern: () => schritt('/wahl', { aufgabe_id: r.id, gewaehlt: true }),
  });
}

(async () => {
  leiste();
  try {
    ich = await L.api('GET', '/api/s/' + CODE);
    await laden();
  } catch (e) {
    try { if (localStorage.getItem('lernbuero-code') === CODE) localStorage.removeItem('lernbuero-code'); } catch (f) { /* leer */ }
    document.getElementById('schiene').hidden = true;
    L.setzen(inhalt, el('div', { class: 'karte stapel' }, el('h1', { class: 'dreieck', text: 'Code ungültig' }),
      el('p', { text: e.message }), el('a', { class: 'knopf haupt', href: '/?neu', text: 'Code eingeben' })));
    return;
  }
  merken();
  document.getElementById('wer').textContent = ich.vorname + ' ' + ich.nachname + ' · ' + ich.klasse;
  window.addEventListener('hashchange', zeigen);
  zeigen();
  // zwischen Handy-/Tablet-Ansicht und breitem Raster wechseln, wenn das Gerät gedreht wird
  if (window.matchMedia) {
    const mq = window.matchMedia('(max-width: 800px)');
    const neu = () => { if (document.querySelector('dialog')) setTimeout(neu, 800); else zeigen(); };   // nach dem Overlay neu zeichnen
    let war = mq.matches, uhr = null;
    window.addEventListener('resize', () => {   // beim Drehen oder Ändern der Fenstergröße
      clearTimeout(uhr);
      uhr = setTimeout(() => { if (mq.matches !== war) { war = mq.matches; neu(); } }, 250);
    });
  }
  // Hilfe live: solange der Schüler in der Reihe steht, alle 10 Sekunden den Platz holen
  setInterval(async () => {
    if (!z || !z.hilfe.offen || document.hidden) return;
    try {
      const h = await api('/hilfe');
      if (h.offen !== z.hilfe.offen || h.platz !== z.hilfe.platz) {
        z.hilfe = h;
        hilfeAnzeigen();
        if (!h.offen) L.meldung('Deine Hilfe-Meldung ist erledigt.');
      }
    } catch (e) { /* still */ }
  }, 10000);
  setInterval(async () => {
    if (document.querySelector('dialog') || document.hidden) return;
    try { const alt = z.ungelesen; await laden(); if (z.ungelesen !== alt && location.hash !== '#rueck') zeigen(); else { leisteZahlen(); hilfeAnzeigen(); } } catch (e) { /* still */ }
  }, 120000);
})();
