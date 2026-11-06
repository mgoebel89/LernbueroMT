// Schülerseite (/s/<Code>): Leiste mit den fünf Bereichen (feste Farbe und Symbol, am PC links, am Handy unten).
// Stufe C: Mein Plan (Raster), Heute mit „Tag abschließen“, Kann-Liste vorher. Jede Entscheidung läuft über ein Overlay.
// Rückmeldungen (Stufe D) und Gelingensnachweise (Stufe E) folgen.
'use strict';
const { el } = L;
const CODE = location.pathname.split('/')[2].toUpperCase().replace(/[^A-Z0-9]/g, '');
const inhalt = document.getElementById('inhalt');
const BEREICHE = [
  { s: 'plan', lang: 'Mein Plan', kurz: 'Plan' },
  { s: 'heute', lang: 'Heute', kurz: 'Heute' },
  { s: 'kann', lang: 'Kann-Liste', kurz: 'Kann ich' },
  { s: 'rueck', lang: 'Rückmeldungen', kurz: 'Rückmeld.', text: 'Rückmeldungen und Empfehlungen deiner Lehrkräfte nach dem Gespräch.', stufe: 'D' },
  { s: 'gn', lang: 'Gelingensnachweise', kurz: 'Nachweise', text: 'Bereit melden, Termin buchen, Ergebnis ansehen.', stufe: 'E' },
];
const STUFEN = [['😟', 'muss viel üben'], ['😐', 'brauche Hilfe'], ['🙂', 'meist allein'], ['😀', 'kann es perfekt']];
const AMPELN = [['g', 'im Plan'], ['y', 'Probleme, schaffe ich wohl'], ['r', 'ohne Hilfe nicht weiter']];
let ich = null, z = null, gefragt = false;

const api = (pfad, daten) => L.api(daten === undefined ? 'GET' : 'POST', '/api/s/' + CODE + pfad, daten);

function merken() {
  try { localStorage.setItem('lernbuero-code', CODE); } catch (e) { /* privat: dann eben nicht */ }
}

function hilfe() {
  L.dialog({ titel: 'Ich brauche Hilfe', knopf: 'OK', abbrechen: null,
    inhalt: el('p', { text: 'Der Hilfe-Knopf wird mit Stufe D freigeschaltet. Bis dahin melde dich bitte wie gewohnt.' }) });
}

function leiste() {
  L.setzen(document.getElementById('schiene'), BEREICHE.map(b => el('a', { href: '#' + b.s, 'data-bereich': b.s, title: b.lang },
    el('b', { class: 'ik ' + b.s }, L.symbol(b.s)), el('span', { class: 'lang', text: b.lang === 'Gelingensnachweise' ? 'Nachweise' : b.lang }),
    el('span', { class: 'kurz', text: b.kurz }))),
    el('button', { type: 'button', class: 'hilfe-knopf schiene-hilfe', onclick: hilfe }, L.symbol('hilfe'), 'Ich brauche Hilfe'));
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
  return [].concat(...z.pakete.map(p => p.zeilen.filter(r => r.typ === 'aufgabe').map(r => Object.assign({ paket: p.titel }, r))));
}

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
  else L.setzen(inhalt, el('h1', { class: 'dreieck', text: b.lang }),
    el('div', { class: 'karte platzhalter' }, el('b', { class: 'ik ' + b.s }, L.symbol(b.s)), el('p', { text: b.text }),
      el('p', { class: 'leise', text: 'Dieser Bereich kommt mit Stufe ' + b.stufe + '.' })));
  if (!gefragt) { gefragt = true; nachfragen(); }
}

function naechsteFrist() {
  const offen = alleZeilen().filter(r => r.gewaehlt && r.wirksam && r.wirksam >= z.heute).sort((a, b) => a.wirksam.localeCompare(b.wirksam));
  return offen[0];
}

function planZeigen() {
  const n = naechsteFrist();
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Mein Plan' }),
    n ? el('div', { class: 'banner' }, 'Nächste Frist: ', el('b', { text: n.kuerzel + ' ' + n.titel }), ' am ' + L.tag(n.wirksam) + '.') : null,
    z.pakete.length ? Raster.zeichnen(z, { bearbeitbar: true, planen, waehlen: wahlFragen })
      : el('div', { class: 'leer', text: 'Noch ist kein Lernpaket für dich freigegeben.' }),
    el('p', { class: 'leise klein' }, 'Nicht du? ', el('a', { href: '/?neu', text: 'Anderen Code eingeben' })));
}

async function planen(aufgabeId, hinzu, weg) {
  try { await schritt('/plan', { aufgabe_id: aufgabeId, hinzu, weg }); }
  catch (e) { L.meldung(e.message, true); zeigen(); }
}

function heuteZeigen() {
  const t = z.heute_tag;
  const heute = alleZeilen().filter(r => r.gewaehlt && r.plan.includes(z.heute));
  const unterricht = t && (t.status === 'unterricht' || t.status === 'ohne');
  const fristen = alleZeilen().filter(r => r.gewaehlt && r.wirksam && r.wirksam >= z.heute).sort((a, b) => a.wirksam.localeCompare(b.wirksam)).slice(0, 4);
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Heute · ' + L.tag(z.heute) }),
    !t ? el('div', { class: 'banner', text: 'Heute ist kein Lernbüro.' })
      : t.status === 'ohne' ? el('div', { class: 'banner', text: 'Heute ohne Lehrkraft (' + t.grund + '). Arbeite nach deinem Plan.' })
        : !unterricht ? el('div', { class: 'banner warnung', text: (t.status === 'ferien' ? 'Ferien: ' : 'Fällt aus: ') + t.grund }) : null,
    unterricht && t.status !== 'ohne' ? el('button', { type: 'button', class: 'hilfe-gross', onclick: hilfe }, L.symbol('hilfe'), 'Ich brauche Hilfe') : null,
    el('div', { class: 'karte stapel' }, el('div', { class: 'etikett', text: 'Für heute geplant' }),
      heute.length ? heute.map(r => el('div', { class: 'zeile' }, el('b', { class: 'mono', style: 'color:var(--blau)', text: r.kuerzel }),
        r.moodle_link ? el('a', { class: 'alink', href: r.moodle_link, target: '_blank', rel: 'noopener', text: r.titel }) : r.titel,
        el('span', { class: 'rechts' }, r.ampel ? el('span', { class: 'ampel a-' + r.ampel }) : null)))
        : el('p', { class: 'leise', text: unterricht ? 'Für heute hast du nichts geplant. Plane in „Mein Plan“.' : 'Nichts geplant.' })),
    unterricht ? el('button', { type: 'button', class: z.abgeschlossen ? 'knopf' : 'haupt', style: 'width:100%;padding:12px', onclick: abschliessen },
      L.symbol('kann'), z.abgeschlossen ? 'Tag abgeschlossen um ' + z.abgeschlossen.slice(11, 16) + ' · ändern' : 'Tag abschließen') : null,
    z.hinweise.ampel_alt.length ? el('div', { class: 'banner warnung', text: 'Ampel fehlt seit über einer Woche: ' +
      z.hinweise.ampel_alt.map(h => h.kuerzel).join(', ') + '. Bitte beim Tagesabschluss einschätzen.' }) : null,
    fristen.length ? el('div', { class: 'karte stapel' }, el('div', { class: 'etikett', text: 'Demnächst fällig' }),
      el('div', { class: 'liste-klein' }, fristen.map(r => el('div', {}, el('span', { class: 'dat', text: L.tag(r.wirksam) }), r.kuerzel + ' ' + r.titel)))) : null);
}

async function abschliessen() {
  const alle = alleZeilen().filter(r => r.gewaehlt);
  const wahl = {};
  const geplant = alle.filter(r => r.plan.includes(z.heute) || r.ist[z.heute]);
  const andere = alle.filter(r => !geplant.includes(r));
  const zeile = r => {
    const ampel = r.ist[z.heute] || r.ampel || 'g';
    const box = el('input', { type: 'checkbox', checked: r.plan.includes(z.heute) || !!r.ist[z.heute] });
    const knoepfe = el('div', { class: 'ampel-wahl' }, AMPELN.map(([w, t]) => el('button', { type: 'button', class: w === ampel ? 'an' : null,
      onclick: ev => { wahl[r.id] = w; knoepfe.querySelectorAll('button').forEach(b => b.classList.toggle('an', b === ev.currentTarget)); } },
      el('i', { class: 'ampel a-' + w }), t)));
    wahl[r.id] = ampel;
    const sichtbar = () => { knoepfe.hidden = !box.checked; };
    box.addEventListener('change', sichtbar); sichtbar();
    return el('div', { class: 'abschluss-zeile', 'data-aufgabe': r.id }, el('label', { class: 'haken' }, box, el('b', { text: r.kuerzel }), r.titel + ' heute bearbeitet'), knoepfe);
  };
  const weitere = el('div', { hidden: true }, andere.map(zeile));
  await L.dialog({
    titel: 'Tag abschließen', knopf: 'Tag abschließen', abbrechen: 'Später',
    inhalt: el('div', { class: 'stapel', style: 'gap:4px' }, geplant.map(zeile),
      andere.length ? el('button', { type: 'button', class: 'leicht', style: 'justify-self:start', onclick: ev => { weitere.hidden = false; ev.currentTarget.remove(); } },
        'andere Aufgabe bearbeitet …') : null, weitere,
      el('p', { class: 'leise klein', text: 'Jede laufende Aufgabe braucht mindestens einmal pro Woche eine Ampel.' })),
    speichern: async form => {
      const eintraege = Array.from(form.querySelectorAll('.abschluss-zeile'))
        .filter(d => d.querySelector('input[type=checkbox]').checked).map(d => ({ aufgabe_id: Number(d.dataset.aufgabe), ampel: wahl[d.dataset.aufgabe] }));
      return schritt('/abschluss', { eintraege });
    },
  });
}

function skala(k, aktiv, wert, aendern) {
  const zahlen = ich.einschaetzer === 'zahl';
  return el('div', { class: 'skala' }, STUFEN.map(([smiley, text], i) => el('button', { type: 'button', class: wert === i + 1 ? 'an' : null, disabled: !aktiv,
    onclick: () => aendern(i + 1) }, el('b', { text: zahlen ? String(i + 1) : smiley }), text)));
}

function kannZeigen() {
  L.setzen(inhalt,
    el('h1', { class: 'dreieck', text: 'Kann-Liste' }),
    ich.einschaetzer === 'zahl' ? el('div', { class: 'banner', text: '1 = Ich muss noch viel üben · 2 = Ich brauche noch Hilfe · 3 = Ich kann es meistens allein · 4 = Ich kann es perfekt' }) : null,
    z.pakete.filter(p => p.kann.length).length ? z.pakete.filter(p => p.kann.length).map(p => el('div', { class: 'karte stapel' },
      el('h2', { text: p.titel }),
      el('p', { class: 'leise klein', text: 'Vorher: wie gut kannst du das jetzt schon? Nachher schätzt du dich beim Fertigmelden der Aufgaben ein.' }),
      p.kann.map(k => el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text),
        k.aufgaben_kuerzel.length ? el('div', { class: 'leise klein', text: 'erarbeitet in ' + k.aufgaben_kuerzel.join(', ') }) : null,
        el('div', { class: 'etikett', text: 'Vorher' }),
        skala(k, true, k.vorher, async stufe => { try { await schritt('/kann', { kann_id: k.id, stufe }); } catch (e) { L.meldung(e.message, true); } }),
        k.nachher ? el('div', { class: 'leise klein', text: 'Nachher: ' + STUFEN[k.nachher - 1][1] }) : null))))
      : el('div', { class: 'leer', text: 'Für deine Pakete gibt es noch keine Kann-Liste.' }));
}

// --- Fragen beim Öffnen: Ausfall, Kann-Liste vorher ---

async function nachfragen() {
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
  const offen = z.hinweise.kann_vorher[0];
  if (offen) {
    const p = z.pakete.find(x => x.id === offen.paket_id);
    const werte = {};
    await L.dialog({
      titel: 'Neues Paket: ' + p.titel, knopf: 'Speichern', abbrechen: 'Später',
      inhalt: el('div', { class: 'stapel' }, el('p', { text: 'Bevor du planst: Wie gut kannst du das jetzt schon?' }),
        p.kann.filter(k => !k.vorher).map(k => {
          let ort;
          const neu = () => skala(k, true, werte[k.id], stufe => { werte[k.id] = stufe; ort.replaceWith(ort = neu()); });
          ort = neu();
          return el('div', { class: 'ka' }, el('p', {}, 'Ich kann ' + k.text), ort);
        })),
      speichern: async () => {
        for (const [kid, stufe] of Object.entries(werte)) z = await api('/kann', { kann_id: Number(kid), stufe });
        zeigen();
        return true;
      },
    });
  }
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
  setInterval(async () => { if (!document.querySelector('dialog')) { try { await laden(); } catch (e) { /* still */ } } }, 120000);
})();
