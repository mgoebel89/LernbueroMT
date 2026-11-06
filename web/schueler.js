// Schuelerseite (/s/<Code>): Leiste mit den fuenf Bereichen (feste Farbe und Symbol, am PC links, am Handy unten) und
// der Hilfe-Knopf. Stufe A zeigt noch Platzhalter; Plan, Heute und Kann-Liste kommen mit Stufe C.
'use strict';
const { el } = L;
const CODE = location.pathname.split('/')[2].toUpperCase().replace(/[^A-Z0-9]/g, '');
const inhalt = document.getElementById('inhalt');
const BEREICHE = [
  { s: 'plan', lang: 'Mein Plan', kurz: 'Plan', text: 'Hier planst du deine Aufgaben über die Unterrichtstage: Balken ziehen, Wahlaufgaben wählen, Fristen im Blick.', stufe: 'C' },
  { s: 'heute', lang: 'Heute', kurz: 'Heute', text: 'Was heute dran ist, mit Link zur Aufgabe in Moodle, „Fertig melden“ und „Tag abschließen“.', stufe: 'C' },
  { s: 'kann', lang: 'Kann-Liste', kurz: 'Kann ich', text: 'Hier schätzt du ein, was du schon kannst: vorher und nachher.', stufe: 'C' },
  { s: 'rueck', lang: 'Rückmeldungen', kurz: 'Rückmeld.', text: 'Rückmeldungen und Empfehlungen deiner Lehrkräfte nach dem Gespräch.', stufe: 'D' },
  { s: 'gn', lang: 'Gelingensnachweise', kurz: 'Nachweise', text: 'Bereit melden, Termin buchen, Ergebnis ansehen.', stufe: 'E' },
];
let ich = null;

function merken() {
  try { localStorage.setItem('lernbuero-code', CODE); } catch (e) { /* privat: dann eben nicht */ }
}

function hilfe() {
  L.dialog({
    titel: 'Ich brauche Hilfe',
    inhalt: el('p', { text: 'Der Hilfe-Knopf wird mit Stufe D freigeschaltet. Bis dahin melde dich bitte wie gewohnt.' }),
    knopf: 'OK', abbrechen: null,
  });
}

function leiste() {
  const nav = document.getElementById('schiene');
  L.setzen(nav, BEREICHE.map(b => el('a', { href: '#' + b.s, 'data-bereich': b.s, title: b.lang },
    el('b', { class: 'ik ' + b.s }, L.symbol(b.s)), el('span', { class: 'lang', text: b.lang === 'Gelingensnachweise' ? 'Nachweise' : b.lang }),
    el('span', { class: 'kurz', text: b.kurz }))),
    el('button', { type: 'button', class: 'hilfe-knopf schiene-hilfe', onclick: hilfe }, L.symbol('hilfe'), 'Ich brauche Hilfe'));
}

function zeigen() {
  const s = (location.hash.slice(1) || 'plan');
  const b = BEREICHE.find(x => x.s === s) || BEREICHE[0];
  document.querySelectorAll('#schiene a').forEach(a => {
    a.classList.toggle('an', a.dataset.bereich === b.s);
    if (a.dataset.bereich === b.s) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  L.titel(b.lang);
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: b.lang }),
    b.s === 'heute' ? el('button', { type: 'button', class: 'hilfe-gross', onclick: hilfe }, L.symbol('hilfe'), 'Ich brauche Hilfe') : null,
    el('div', { class: 'karte platzhalter' },
      el('b', { class: 'ik ' + b.s }, L.symbol(b.s)),
      el('p', { text: b.text }),
      el('p', { class: 'leise', text: 'Dieser Bereich wird gerade gebaut und kommt mit Stufe ' + b.stufe + '.' })),
    b.s === 'plan' ? el('p', { class: 'leise klein' }, 'Nicht du? ', el('a', { href: '/?neu', text: 'Anderen Code eingeben' })) : null);
}

(async () => {
  leiste();
  try {
    ich = await L.api('GET', '/api/s/' + CODE);
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
})();
