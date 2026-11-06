// Unterrichtstage (Stufe B): Karte auf der Klassenseite mit Regeln, besonderen Tagen (fällt aus / ohne Sie) und den
// nächsten Unterrichtstagen; Karte „Ferien und Schulkalender“ in den Einstellungen (Admin).
'use strict';
const Tage = (() => {
  const el = L.el;
  const TAGNAMEN = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];
  const RHYTHMUS = { jede: 'jede Woche', gerade: 'gerade KW', ungerade: 'ungerade KW' };
  const STATUS = { unterricht: ['blau', 'Unterricht'], ohne: ['gelb', 'ohne Lehrkraft'], ausfall: ['rot', 'fällt aus'], ferien: ['', 'Ferien'] };

  function karte(k) {
    const ort = el('div', { class: 'karte stapel' }, el('h2', { text: 'Unterrichtstage' }), el('p', { class: 'leise', text: 'Lädt …' }));
    laden();
    return ort;

    async function laden() {
      let t;
      try { t = await L.api('GET', '/api/klassen/' + k.id + '/tage'); } catch (e) { L.setzen(ort, el('div', { class: 'leer', text: e.message })); return; }
      const team = k.rolle === 'team';
      const kuenftig = t.tage.filter(x => x.datum >= t.heute).slice(0, 16);
      L.setzen(ort,
        el('div', { class: 'zeile' }, el('h2', { text: 'Unterrichtstage' }),
          team ? el('span', { class: 'rechts' },
            el('button', { type: 'button', class: 'klein', onclick: () => regelDialog(k, null, t, laden) }, L.symbol('plus'), 'Regel'),
            el('button', { type: 'button', class: 'klein', onclick: () => besondersDialog(k, t, laden) }, 'Ausfall oder „ohne Sie“')) : null),
        t.regeln.length ? el('div', { class: 'stapel', style: 'gap:4px' }, t.regeln.map(r => el('div', { class: 'zeile klein' },
          el('b', { text: TAGNAMEN[r.wochentag] }), r.von + '–' + r.bis + ' · ' + RHYTHMUS[r.rhythmus],
          el('span', { class: 'leise', text: '· ' + L.tag(r.gueltig_von, true) + ' bis ' + L.tag(r.gueltig_bis, true) }),
          team ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => regelDialog(k, r, t, laden) }, 'Bearbeiten')) : null)))
          : el('div', { class: 'leer', text: team ? 'Noch keine Regel. Zum Beispiel: montags 07:45 bis 13:00, jede Woche.' : 'Noch keine Unterrichtstage.' }),
        kuenftig.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
          el('thead', {}, el('tr', {}, el('th', { text: 'Nächste Tage' }), el('th', { text: 'Zeit' }), el('th', { text: 'Stand' }), el('th', {}))),
          el('tbody', {}, kuenftig.map(x => el('tr', { class: x.status === 'unterricht' || x.status === 'ohne' ? null : 'aus' },
            el('td', { text: L.tag(x.datum) + ' · KW ' + x.kw }), el('td', { class: 'leise', text: x.von + '–' + x.bis }),
            el('td', {}, el('span', { class: 'chip ' + STATUS[x.status][0], text: STATUS[x.status][1] }), x.grund ? el('span', { class: 'leise klein', text: ' ' + x.grund }) : null),
            el('td', { class: 'knoepfe' }, team && x.besonders_id ? el('button', { type: 'button', class: 'klein', onclick: () => besondersEntfernen(k, x, laden) }, 'Zurücknehmen') : null))))))
          : null,
        t.besondere.some(b => b.von !== b.bis) ? el('p', { class: 'leise klein', text: 'Mehrtägige Einträge: ' + t.besondere.filter(b => b.von !== b.bis)
          .map(b => (b.art === 'ausfall' ? 'fällt aus ' : 'ohne Sie ') + L.tag(b.von) + '–' + L.tag(b.bis) + ' (' + b.grund + ')').join('; ') }) : null,
        el('p', { class: 'leise klein', text: 'Ferien kommen aus dem Schulkalender (Einstellungen). „Ohne Sie“: das Lernbüro findet statt, Hilfe-Knopf und Termine sind gesperrt.' }));
    }
  }

  async function regelDialog(k, r, t, fertig) {
    const tag = el('select', {}, TAGNAMEN.slice(0, 6).map((n, i) => el('option', { value: i, text: n })));
    tag.value = r ? r.wochentag : 0;
    const rhythmus = el('select', {}, Object.entries(RHYTHMUS).map(([w, n]) => el('option', { value: w, text: n })));
    rhythmus.value = r ? r.rhythmus : 'jede';
    const von = el('input', { type: 'time', value: r ? r.von : '07:45', required: true });
    const bis = el('input', { type: 'time', value: r ? r.bis : '13:00', required: true });
    const gv = el('input', { type: 'date', value: r ? r.gueltig_von : t.schuljahr[0], required: true });
    const gb = el('input', { type: 'date', value: r ? r.gueltig_bis : t.schuljahr[1], required: true });
    const ok = await L.dialog({
      titel: r ? 'Regel bearbeiten' : 'Neue Regel für ' + k.name,
      inhalt: el('div', { class: 'felder' },
        el('div', { class: 'felder zwei' }, L.feld('Wochentag', tag), L.feld('Rhythmus', rhythmus, 'Kalenderwoche nach ISO')),
        el('div', { class: 'felder zwei' }, L.feld('Beginn', von), L.feld('Ende', bis)),
        el('div', { class: 'felder zwei' }, L.feld('gültig von', gv), L.feld('gültig bis', gb)),
        r ? el('div', {}, L.nebenknopf('Regel entfernen …', async () => {
          const weg = await L.dialog({ titel: 'Regel entfernen?', knopf: 'Entfernen', gefaehrlich: true,
            inhalt: el('p', { text: TAGNAMEN[r.wochentag] + ' ' + r.von + '–' + r.bis + ' gilt danach nicht mehr.' }),
            speichern: () => L.api('POST', '/api/klassen/' + k.id + '/regeln/' + r.id, { aktiv: false }) });
          if (weg) fertig();
        })) : null),
      speichern: () => L.api('POST', '/api/klassen/' + k.id + '/regeln' + (r ? '/' + r.id : ''), {
        wochentag: Number(tag.value), rhythmus: rhythmus.value, von: von.value, bis: bis.value, gueltig_von: gv.value, gueltig_bis: gb.value }),
    });
    if (ok) fertig();
  }

  async function besondersDialog(k, t, fertig) {
    const naechster = (t.tage.find(x => x.datum >= t.heute && (x.status === 'unterricht' || x.status === 'ohne')) || {}).datum || t.heute;
    const art = el('div', { class: 'stapel', style: 'gap:6px' },
      el('label', { class: 'haken' }, el('input', { type: 'radio', name: 'art', value: 'ausfall', checked: true }), 'Fällt aus (Plan muss umgeplant werden, Fristen wandern mit)'),
      el('label', { class: 'haken' }, el('input', { type: 'radio', name: 'art', value: 'ohne' }), 'Findet statt, ohne Sie (Plan gilt, Hilfe-Knopf und Termine gesperrt)'));
    const von = el('input', { type: 'date', value: naechster, required: true });
    const bis = el('input', { type: 'date', value: naechster });
    const grund = el('input', { required: true, maxlength: 80, placeholder: 'z. B. Zwischenprüfung, Fortbildung' });
    const ok = await L.dialog({
      titel: 'Besonderer Tag · ' + k.name, knopf: 'Eintragen',
      inhalt: el('div', { class: 'felder' }, art, el('div', { class: 'felder zwei' }, L.feld('Erster Tag', von), L.feld('Letzter Tag', bis, 'leer = nur ein Tag')), L.feld('Grund', grund),
        el('p', { class: 'leise klein', text: 'Geht auch kurzfristig oder nachträglich. Ein nachträglicher Ausfall zählt nicht als „Plan nicht eingehalten“.' })),
      speichern: form => L.api('POST', '/api/klassen/' + k.id + '/besonders', {
        art: form.querySelector('input[name=art]:checked').value, von: von.value, bis: bis.value || von.value, grund: grund.value }),
    });
    if (ok) fertig();
  }

  async function besondersEntfernen(k, x, fertig) {
    const ok = await L.dialog({
      titel: 'Eintrag zurücknehmen?', knopf: 'Zurücknehmen',
      inhalt: el('p', { text: (x.status === 'ausfall' ? 'Fällt aus' : 'Ohne Lehrkraft') + ': ' + x.grund + '. Der Tag gilt danach wieder als normaler Unterrichtstag.' }),
      speichern: () => L.api('POST', '/api/klassen/' + k.id + '/besonders/' + x.besonders_id + '/entfernen', {}),
    });
    if (ok) fertig();
  }

  // --- Einstellungen: Ferien und Schulkalender (Admin) ---

  function ferienKarte() {
    const ort = el('div', { class: 'karte stapel' }, el('h2', { text: 'Ferien und Schulkalender' }));
    laden();
    return ort;

    async function laden() {
      let f;
      try { f = await L.api('GET', '/api/ferien'); } catch (e) { L.setzen(ort, el('div', { class: 'leer', text: e.message })); return; }
      const abo = f.schulkalender;
      const url = el('input', { placeholder: 'https://… oder webcal://… (ICS-Link des Schulkalenders)' });
      const woerter = el('input', { value: f.stichwoerter });
      L.setzen(ort,
        el('h2', { text: 'Ferien und Schulkalender' }),
        el('p', { class: 'leise klein', text: 'Aus dem Schulkalender werden ganztägige Einträge mit einem der Stichwörter als Ferien übernommen, alle 30 Minuten neu. Die Adresse bleibt auf dem Server.' }),
        abo ? el('div', { class: 'banner' + (abo.fehler ? ' warnung' : '') }, 'Abo: ', el('span', { class: 'mono', text: abo.adresse }), ' · ',
          abo.fehler ? 'Fehler: ' + abo.fehler : abo.stand ? abo.anzahl + ' Einträge, Stand ' + abo.stand.replace('T', ' ').slice(0, 16) : 'noch nicht abgerufen') : null,
        !f.pakete_da ? el('div', { class: 'banner warnung', text: 'Für Kalender-Abos fehlen im Container die Pakete python3-icalendar und python3-recurring-ical-events (das nächste Update installiert sie).' }) : null,
        el('form', { class: 'felder', onsubmit: async ev => {
          ev.preventDefault();
          try { await L.api('POST', '/api/schulkalender', { url: url.value || undefined, stichwoerter: woerter.value }); L.meldung('Gespeichert.'); laden(); }
          catch (e) { L.meldung(e.message, true); }
        } }, L.feld(abo ? 'Neue Adresse (leer = bleibt)' : 'Adresse des Schulkalenders', url), L.feld('Stichwörter für Ferien', woerter, 'durch Komma getrennt'),
          el('div', { class: 'zeile' }, el('button', { class: 'haupt', type: 'submit', text: 'Speichern' }),
            abo ? el('button', { type: 'button', onclick: async () => { try { await L.api('POST', '/api/schulkalender', { abrufen: true }); laden(); } catch (e) { L.meldung(e.message, true); } } }, 'Jetzt abrufen') : null,
            abo ? el('button', { type: 'button', class: 'warnen', onclick: async () => {
              const ok = await L.dialog({ titel: 'Schulkalender entfernen?', knopf: 'Entfernen', gefaehrlich: true,
                inhalt: el('p', { text: 'Die daraus übernommenen Ferien fallen weg. Von Hand eingetragene bleiben.' }),
                speichern: () => L.api('POST', '/api/schulkalender/entfernen', {}) });
              if (ok) laden();
            } }, 'Entfernen') : null)),
        el('div', { class: 'zeile' }, el('h3', { text: 'Ferien' }), el('span', { class: 'rechts' },
          el('button', { type: 'button', class: 'klein', onclick: async () => {
            const von = el('input', { type: 'date', required: true }), bis = el('input', { type: 'date' }), name = el('input', { required: true, maxlength: 80, placeholder: 'z. B. Herbstferien' });
            const ok = await L.dialog({ titel: 'Ferien von Hand', knopf: 'Eintragen',
              inhalt: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, L.feld('Erster Tag', von), L.feld('Letzter Tag', bis, 'leer = nur ein Tag')), L.feld('Name', name)),
              speichern: () => L.api('POST', '/api/ferien', { von: von.value, bis: bis.value || von.value, name: name.value }) });
            if (ok) laden();
          } }, L.symbol('plus'), 'Von Hand'))),
        f.ferien.length ? el('div', { class: 'stapel', style: 'gap:4px' }, f.ferien.map(x => el('div', { class: 'zeile klein' },
          el('span', { text: L.tag(x.von, true) + (x.bis !== x.von ? ' – ' + L.tag(x.bis, true) : '') }), el('b', { text: x.name }),
          el('span', { class: 'chip', text: x.quelle === 'abo' ? 'Schulkalender' : 'von Hand' }),
          x.quelle === 'hand' ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: async () => {
            try { await L.api('POST', '/api/ferien/' + x.id + '/entfernen', {}); laden(); } catch (e) { L.meldung(e.message, true); }
          } }, 'Entfernen')) : null))) : el('p', { class: 'leise klein', text: 'Keine Ferien eingetragen.' }));
    }
  }

  return { karte, ferienKarte };
})();
