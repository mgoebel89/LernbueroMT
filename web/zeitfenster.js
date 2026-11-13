// Sprech- und Prüfungszeiten je Klasse (Stufe D, Skizze H): Anlegen im Overlay (Art, Beginn, Ende, Termindauer x,
// Puffer y, wöchentlich oder einzelne Tage), Liste der eigenen Fenster, Belegung der nächsten drei Wochen.
'use strict';
const Zeiten = (() => {
  const el = L.el;
  const ART = { sprech: ['Sprechzeit', 'Feedbackgespräche'], pruefung: ['Prüfungszeit', 'Fachgespräch, praktische Prüfung'] };
  const TERMINART = { feedback: 'Feedback', fachgespraech: 'Fachgespräch', praxis: 'Praktische Prüfung' };

  const minuten = t => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));

  function anzahl(von, bis, dauer, puffer) {
    if (!/^\d\d:\d\d$/.test(von) || !/^\d\d:\d\d$/.test(bis) || !(dauer > 0)) return 0;
    let n = 0, t = minuten(von);
    while (t + dauer <= minuten(bis)) { n += 1; t += dauer + (puffer || 0); }
    return n;
  }

  async function seite(kid) {
    titelSetzen('Zeitfenster');
    const { klassen } = await L.api('GET', '/api/klassen');
    const meine = klassen.filter(k => k.rolle === 'team' || k.rolle === 'einsicht');
    if (!meine.length) {
      L.setzen(inhalt, el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Zeitfenster' })),
        el('div', { class: 'leer' }, 'Sie sind noch in keiner Klasse eingetragen. ', el('a', { href: '#klassen', text: 'Zu den Klassen' })));
      return;
    }
    const k = meine.find(x => x.id === kid) || meine[0];
    const d = await L.api('GET', '/api/klassen/' + k.id + '/zeitfenster');
    const team = d.rolle === 'team';
    const wahl = el('select', { onchange: ev => { location.hash = 'zeitfenster/' + ev.target.value; } }, meine.map(x => el('option', { value: x.id, text: x.name })));
    wahl.value = k.id;
    const fensterText = z => (z.woechentlich ? 'jeden ' + z.tag + ' bis ' + L.tag(z.gueltig_bis) + (z.gueltig_von > L.heute() ? ' (ab ' + L.tag(z.gueltig_von) + ')' : '')
      : 'nur ' + z.tage.map(t => L.tag(t)).join(', ')) + ' · ' + z.dauer + ' min + ' + z.puffer + ' min Puffer · ' + z.plaetze_je_tag + ' Termine je Tag';
    L.setzen(inhalt,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Sprech- und Prüfungszeiten' }), wahl,
        team ? el('button', { type: 'button', class: 'haupt', onclick: () => anlegen(k) }, L.symbol('plus'), 'Anlegen') : null),
      el('div', { class: 'karte stapel' }, el('h2', { text: 'Zeitfenster ' + k.name }),
        d.zeitfenster.length ? el('div', { class: 'stapel', style: 'gap:6px' }, d.zeitfenster.map(z => el('div', { class: 'zf-zeile ' + z.art },
          el('div', {}, el('b', { text: ART[z.art][0] }), ' · ' + z.von + '–' + z.bis + ' · ' + z.lehrkraft,
            el('div', { class: 'leise klein', text: fensterText(z) + ' · nur ' + ART[z.art][1] })),
          team && z.lehrkraft_id === S.konto.id ? el('button', { type: 'button', class: 'klein warnen', onclick: () => entfernen(z) }, 'Entfernen') : null)))
          : el('p', { class: 'leise', text: 'Noch keine Sprech- oder Prüfungszeit für ' + k.name + '.' }),
        el('p', { class: 'leise klein', text: 'Feedbackgespräche gibt es nur in Sprechzeiten, Fachgespräch und praktische Prüfung nur in Prüfungszeiten (Buchung mit Stufe E). An Tagen mit Ausfall, Ferien oder „ohne Lehrkraft“ entstehen keine Termine.' })),
      el('h2', { class: 'dreieck', text: 'Belegung der nächsten drei Wochen' }),
      d.belegung.length ? el('div', { class: 'raster belegung' }, d.belegung.map(b => tagKarte(b, team)))
        : el('div', { class: 'leer', text: 'In den nächsten drei Wochen gibt es keine Termine.' }));
  }

  function tagKarte(b, team) {
    const z = b.zeitfenster;
    const gesperrt = b.status !== 'unterricht';
    return el('div', { class: 'karte stapel bel ' + z.art },
      el('div', { class: 'zeile' }, el('b', { text: L.tag(b.datum) }), el('span', { class: 'leise klein', text: ART[z.art][0] + ' ' + z.von + '–' + z.bis + ' · ' + z.kuerzel.toUpperCase() })),
      gesperrt ? el('div', { class: 'banner warnung klein', text: (b.status === 'ohne' ? 'ohne Lehrkraft: ' : b.status === 'ferien' ? 'Ferien: ' : 'fällt aus: ') + b.grund + ' · keine Termine' }) : null,
      gesperrt ? null : el('div', { class: 'slot-liste' }, b.plaetze.map(p => p.puffer
        ? el('div', { class: 'slot puffer' }, el('span', { class: 'mono', text: p.beginn + '–' + p.ende }), el('span', { text: 'Puffer' }))
        : el('div', { class: 'slot' + (p.termin ? ' gebucht' : p.dienst ? ' dienst' : '') }, el('span', { class: 'mono', text: p.beginn + '–' + p.ende }),
          p.termin ? el('span', {}, el('b', { text: p.termin.name }), el('span', { class: 'leise klein', text: ' ' + TERMINART[p.termin.art] + ' · ' + p.termin.anlass }),
            p.dienst ? el('span', { class: 'chip gelb klein', style: 'margin-left:6px', title: 'Überschneidung mit dem Dienstkalender', text: 'überschneidet sich: ' + p.dienst }) : null)
            : p.dienst ? el('span', { class: 'leise', text: 'nicht buchbar · ' + (p.dienst === 'Dienstkalender' ? 'Dienstkalender' : 'Dienstkalender: ' + p.dienst) })
              : el('span', { class: 'leise', text: 'frei' }),
          p.termin && team ? el('span', { class: 'rechts' },
            el('button', { type: 'button', class: 'klein', onclick: () => Rueck.oeffnen({ schueler: p.termin.schueler_id, termin: p.termin.id, danach: zeigen }) }, 'öffnen'),
            el('button', { type: 'button', class: 'klein warnen', onclick: () => absagen(p.termin, b) }, 'absagen')) : null))));
  }

  async function anlegen(k) {
    const n = 'a' + Math.random().toString(36).slice(2);
    const sprech = el('input', { type: 'radio', name: n, value: 'sprech', checked: true });
    const pruef = el('input', { type: 'radio', name: n, value: 'pruefung' });
    const tag = el('input', { type: 'date', required: true, value: L.heute() });
    const von = el('input', { type: 'time', required: true, value: '09:30' });
    const bis = el('input', { type: 'time', required: true, value: '10:30' });
    const dauer = el('input', { type: 'number', min: 5, max: 120, step: 5, required: true, value: 10 });
    const puffer = el('input', { type: 'number', min: 0, max: 60, step: 5, value: 5 });
    const m = 'm' + Math.random().toString(36).slice(2);
    const woech = el('input', { type: 'radio', name: m, checked: true });
    const einzeln = el('input', { type: 'radio', name: m });
    const bisTag = el('input', { type: 'date', value: (() => { const d = new Date(); d.setDate(d.getDate() + 42); return d.toISOString().slice(0, 10); })() });
    const tage = [];
    const tagChips = el('div', { class: 'personen' });
    const neuerTag = el('input', { type: 'date' });
    const chips = () => L.setzen(tagChips, tage.sort().map(t => el('span', { class: 'person' }, L.tag(t),
      el('button', { type: 'button', text: '×', onclick: () => { tage.splice(tage.indexOf(t), 1); chips(); } }))));
    const einzelBlock = el('div', { class: 'zeile' }, neuerTag, el('button', { type: 'button', class: 'klein', onclick: () => {
      if (neuerTag.value && !tage.includes(neuerTag.value)) { tage.push(neuerTag.value); chips(); }
    } }, L.symbol('plus'), 'Tag'), tagChips);
    const ergebnis = el('div', { class: 'banner klein' });
    const aktualisieren = () => {
      einzelBlock.hidden = !einzeln.checked;
      bisTag.disabled = einzeln.checked;
      const anz = anzahl(von.value, bis.value, Number(dauer.value), Number(puffer.value));
      const wt = tag.value ? L.tag(tag.value).slice(0, 2) : '';
      ergebnis.textContent = 'ergibt ' + anz + ' Termin' + (anz === 1 ? '' : 'e') + ' je Tag' +
        (woech.checked && wt ? ' · jeden ' + wt + ' bis ' + L.tag(bisTag.value) : einzeln.checked ? ' · an ' + tage.length + ' einzelnen Tagen' : '');
    };
    [sprech, pruef, tag, von, bis, dauer, puffer, woech, einzeln, bisTag].forEach(x => x.addEventListener('input', aktualisieren));
    tagChips.addEventListener('click', () => setTimeout(aktualisieren, 0));
    einzelBlock.addEventListener('click', () => setTimeout(aktualisieren, 0));
    aktualisieren();
    const ok = await L.dialog({
      titel: 'Zeitfenster für ' + k.name, knopf: 'Anlegen',
      inhalt: el('div', { class: 'felder' },
        el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Art' }),
          el('label', { class: 'haken' }, sprech, el('span', {}, el('b', { text: 'Sprechzeit' }), ' · Feedbackgespräche')),
          el('label', { class: 'haken' }, pruef, el('span', {}, el('b', { text: 'Prüfungszeit' }), ' · Fachgespräch, praktische Prüfung'))),
        el('div', { class: 'felder zwei' }, L.feld('Erster Tag', tag), L.feld('von', von), L.feld('bis', bis)),
        el('div', { class: 'felder zwei' }, L.feld('Termin (x) in Minuten', dauer), L.feld('Puffer (y) in Minuten', puffer)),
        el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Tage' }),
          el('label', { class: 'haken' }, woech, 'wöchentlich bis', bisTag),
          el('label', { class: 'haken' }, einzeln, 'nur an einzelnen Tagen (z. B. Prüfungstage vor den Fristen)'), einzelBlock),
        ergebnis),
      speichern: () => L.api('POST', '/api/klassen/' + k.id + '/zeitfenster', {
        art: pruef.checked ? 'pruefung' : 'sprech', von: von.value, bis: bis.value, dauer: Number(dauer.value), puffer: Number(puffer.value || 0),
        woechentlich: woech.checked, gueltig_von: tag.value, gueltig_bis: bisTag.value, tage: einzeln.checked ? tage.concat(tag.value ? [tag.value] : []) : [],
      }),
    });
    if (!ok) return;
    if (ok.warnungen.length) {
      await L.dialog({ titel: 'Angelegt, bitte prüfen', knopf: 'OK', abbrechen: null,
        inhalt: el('div', { class: 'stapel', style: 'gap:6px' }, ok.warnungen.map(w => el('div', { class: 'banner warnung', text: w }))) });
    } else L.meldung('Zeitfenster angelegt.');
    zeigen();
  }

  async function entfernen(z) {
    const ok = await L.dialog({ titel: ART[z.art][0] + ' ' + z.von + '–' + z.bis + ' entfernen?', knopf: 'Entfernen', gefaehrlich: true,
      inhalt: el('p', { text: 'Schon gebuchte künftige Termine werden abgesagt. Die Schüler sehen „abgesagt von der Lehrkraft“.' }),
      speichern: () => L.api('POST', '/api/zeitfenster/' + z.id + '/entfernen', {}) });
    if (ok) { L.meldung(ok.abgesagt ? ok.abgesagt + ' Termin(e) abgesagt.' : 'Entfernt.'); zeigen(); }
  }

  async function absagen(t, b) {
    const ok = await L.dialog({ titel: 'Termin absagen?', knopf: 'Absagen', gefaehrlich: true,
      inhalt: el('p', { text: t.name + ' · ' + L.tag(b.datum) + ' · ' + t.anlass + '. Der Schüler sieht „abgesagt von der Lehrkraft“ und kann neu buchen.' }),
      speichern: () => L.api('POST', '/api/termine/' + t.id + '/absagen', {}) });
    if (ok) zeigen();
  }

  return { seite, TERMINART };
})();
