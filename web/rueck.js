// Rückmeldung und Empfehlungen (Stufe D, Skizze F): aus „Zu prüfen“, aus einem Termin, aus der Matrix oder von der
// Schülerseite geöffnet. Kann-Aussagen mit der Einschätzung des Schülers und Ihrer daneben, Entscheidung (angenommen /
// überarbeiten bis), Text (getippt oder diktiert), Empfehlungen freiwillig oder verbindlich mit Frist.
// Bis „Freigeben“ ist alles ein Entwurf, den nur Sie sehen.
'use strict';
const Rueck = (() => {
  const el = L.el;
  const ZUSATZ = { vertiefung: 'Vertiefung', wiederholung: 'Wiederholung' };

  async function vorlage(o) {
    const q = new URLSearchParams({ schueler: o.schueler });
    ['meldung', 'termin', 'rueckmeldung', 'aufgabe'].forEach(n => { if (o[n]) q.set(n, o[n]); });
    return L.api('GET', '/api/rueckmeldung/vorlage?' + q.toString());
  }

  // o: { schueler, meldung?, termin?, rueckmeldung?, aufgabe? } -> Promise (true, wenn gespeichert)
  async function oeffnen(o) {
    let v;
    try { v = await vorlage(o); } catch (e) { L.meldung(e.message, true); return null; }
    return fenster(v, o);
  }

  function aufgabeText(a) {
    return a.kuerzel + ' ' + a.titel + (a.art === 'zusatz' ? ' (Zusatz · ' + (ZUSATZ[a.zusatz_art] || '') + (a.kann && a.kann.length ? ' · zu ' + a.kann.join(', ') : '') + ')' : '');
  }

  function aufgabenWahl(auswahl, wert) {
    const pakete = [];
    auswahl.forEach(a => { if (!pakete.includes(a.paket)) pakete.push(a.paket); });
    const w = el('select', { required: true }, el('option', { value: '', text: 'Aufgabe wählen …' }),
      pakete.map(p => el('optgroup', { label: p }, auswahl.filter(a => a.paket === p).map(a => el('option', { value: a.id, text: aufgabeText(a) })))));
    if (wert) w.value = wert;
    return w;
  }

  // Eine Zeile "Empfehlung": Aufgabe, freiwillig/verbindlich, Frist, Hinweis
  function empfehlungZeile(auswahl, e, vorschlag, entfernen) {
    const wahl = aufgabenWahl(auswahl, e && e.aufgabe ? e.aufgabe.id : e && e.aufgabe_id);
    const name = 'v' + Math.random().toString(36).slice(2);
    const frei = el('input', { type: 'radio', name, value: '0', checked: !e || !e.verbindlich });
    const verb = el('input', { type: 'radio', name, value: '1', checked: !!(e && e.verbindlich) });
    const frist = el('input', { type: 'date', value: e && e.frist ? e.frist : vorschlag });
    const hinweis = el('input', { maxlength: 160, value: e ? e.hinweis || '' : '', placeholder: 'Hinweis, z. B. Seite 3 noch einmal' });
    const sichtbar = () => { frist.hidden = !verb.checked; };
    frei.addEventListener('change', sichtbar); verb.addEventListener('change', sichtbar); sichtbar();
    const zeile = el('div', { class: 'emp-bau' }, wahl,
      el('div', { class: 'zeile' }, el('label', { class: 'haken klein' }, frei, 'freiwillig'), el('label', { class: 'haken klein' }, verb, 'verbindlich bis'), frist,
        entfernen ? el('button', { type: 'button', class: 'leicht klein', title: 'Empfehlung entfernen', onclick: () => zeile.remove() }, L.symbol('zu')) : null),
      hinweis);
    zeile.lesen = () => ({ aufgabe_id: Number(wahl.value), verbindlich: verb.checked, frist: verb.checked ? frist.value : null, hinweis: hinweis.value });
    return zeile;
  }

  function fuellwoerter(text) {
    return text.replace(/(^|[\s,])(äh+m?|öh+m?|ähm|hm+|mhm)(?=[\s,.!?]|$)[,]?/gi, '$1').replace(/[ \t]{2,}/g, ' ').replace(/ ([,.!?])/g, '$1')
      .replace(/,\s*([.!?])/g, '$1').replace(/^[\s,]+/gm, '').trim()
      .replace(/(^|[.!?]\s+)([a-zäöüß])/g, (m, a, b) => a + b.toUpperCase());   // Satzanfang wieder gross
  }

  function fenster(v, o) {
    const e = v.entwurf;
    const lesen = !v.darf || !!(e && e.freigegeben);
    const zahlen = v.einschaetzer === 'zahl';
    const name = v.schueler.vorname + ' ' + v.schueler.nachname;
    const offen = v.meldung && v.meldung.status === 'offen';
    const kannWerte = {};
    v.kann.forEach(k => { if (k.lehrkraft) kannWerte[k.kann_id] = k.lehrkraft; });
    if (e && e.kann) e.kann.forEach(k => { kannWerte[k.kann_id] = k.stufe; });

    const kopf = el('div', { class: 'leise klein' }, name + ' · ' + v.schueler.klasse,
      v.meldung ? ' · fertig gemeldet ' + L.wann(v.meldung.zeit) + (offen ? '' : ' (' + ({ angenommen: 'angenommen', ueberarbeiten: 'überarbeiten', zurueckgezogen: 'zurückgezogen' }[v.meldung.status] || '') + ')') : '',
      v.termin ? ' · Termin ' + L.tag(v.termin.datum) + ' ' + v.termin.beginn : '',
      e && e.freigegeben ? ' · freigegeben ' + L.wann(e.freigegeben) + ' von ' + e.verfasser : e ? ' · Entwurf vom ' + L.wann(e.geaendert) : '');

    // Anlass waehlen, wenn die Rueckmeldung frei (ohne Meldung, Termin, Aufgabe) geoeffnet wurde
    let anlass = null;
    if (!e && !v.meldung && !v.termin && !lesen) {
      anlass = aufgabenWahl(v.auswahl, v.aufgabe ? v.aufgabe.id : '');
      anlass.required = false;
      anlass.options[0].textContent = 'allgemein (keine bestimmte Aufgabe)';
      anlass.addEventListener('change', () => {
        anlass.closest('dialog').dispatchEvent(new Event('cancel'));
        setTimeout(() => oeffnen({ schueler: v.schueler.id, aufgabe: anlass.value || null }).then(o.danach || (() => {})), 0);
      });
    }

    const kannTab = v.kann.length ? el('div', { class: 'rk-kann' },
      el('div', { class: 'rk-kopf' }, el('span', { text: 'Kann-Aussage' }), el('span', { text: v.schueler.vorname }), el('span', { text: 'Ihre Sicht' })),
      v.kann.map(k => el('div', { class: 'rk-zeile' },
        el('div', {}, el('b', { class: 'mono', text: k.kuerzel + ' ' }), k.text,
          k.nachher && kannWerte[k.kann_id] && Math.abs(k.nachher - kannWerte[k.kann_id]) >= 2 ? el('div', { class: 'chip gelb klein', text: 'Einschätzungen weichen ab' }) : null),
        el('div', { class: 'rk-schueler' }, el('div', {}, el('span', { class: 'leise', text: 'vorher ' }), L.stufeText(k.vorher, zahlen)),
          el('div', {}, el('span', { class: 'leise', text: 'nachher ' }), el('b', { text: L.stufeText(k.nachher, zahlen) }))),
        L.skala(kannWerte[k.kann_id], lesen ? null : s => { kannWerte[k.kann_id] = s; }, zahlen)))) : null;

    // Entscheidung
    let entscheidung = null, neueFrist = null, entscheidungsBlock = null;
    if (offen && !lesen) {
      const n = 'e' + Math.random().toString(36).slice(2);
      const an = el('input', { type: 'radio', name: n, value: 'angenommen', checked: e && e.entscheidung === 'angenommen' });
      const ue = el('input', { type: 'radio', name: n, value: 'ueberarbeiten', checked: e && e.entscheidung === 'ueberarbeiten' });
      neueFrist = el('input', { type: 'date', value: e && e.neue_frist ? e.neue_frist : v.frist_vorschlag });
      entscheidung = () => an.checked ? 'angenommen' : ue.checked ? 'ueberarbeiten' : null;
      entscheidungsBlock = el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Entscheidung' }),
        el('div', { class: 'entscheidung' }, el('label', { class: 'haken' }, an, 'angenommen'),
          el('label', { class: 'haken' }, ue, 'überarbeiten bis', neueFrist)),
        el('p', { class: 'leise klein', text: 'Vorgabe für die neue Frist: der übernächste Unterrichtstag. ' + v.schueler.vorname + ' darf sich jederzeit wieder fertig melden.' }));
    } else if (e && e.entscheidung) {
      entscheidungsBlock = el('div', {}, el('span', { class: 'sc ' + e.entscheidung, text: e.entscheidung === 'angenommen' ? 'angenommen' : 'überarbeiten bis ' + L.tag(e.neue_frist) }));
    }

    // Text
    const text = el('textarea', { rows: 6, maxlength: 6000, readonly: lesen || null, placeholder: 'Rückmeldung für ' + v.schueler.vorname + ' …' });
    text.value = e ? e.text : '';
    const textWerkzeug = lesen ? null : el('div', { class: 'zeile' },
      window.Diktat ? Diktat.knopf(text, v) : null,
      el('button', { type: 'button', class: 'klein', onclick: () => { text.value = fuellwoerter(text.value); }, text: 'Füllwörter entfernen' }));

    // Empfehlungen
    const liste = el('div', { class: 'stapel', style: 'gap:8px' });
    if (lesen) {
      (e ? e.empfehlungen : []).forEach(x => liste.appendChild(el('div', { class: 'emp-zeile' }, el('div', {},
        el('b', { text: x.aufgabe ? x.aufgabe.kuerzel + ' ' + x.aufgabe.titel : '' }), ' · ', x.verbindlich ? 'verbindlich bis ' + L.tag(x.wirksam || x.frist) : 'freiwillig',
        x.hinweis ? el('div', { class: 'leise klein', text: x.hinweis }) : null, x.erledigt ? el('div', { class: 'leise klein', text: 'erledigt' }) : null))));
    } else {
      (e ? e.empfehlungen : []).forEach(x => liste.appendChild(empfehlungZeile(v.auswahl, x, v.frist_vorschlag, true)));
    }
    const empBlock = el('div', { class: 'stapel', style: 'gap:8px' }, el('div', { class: 'etikett', text: 'Empfehlungen für ' + v.schueler.vorname }), liste,
      lesen ? (liste.children.length ? null : el('p', { class: 'leise klein', text: 'keine' }))
        : el('button', { type: 'button', class: 'klein', style: 'justify-self:start', onclick: () => liste.appendChild(empfehlungZeile(v.auswahl, null, v.frist_vorschlag, true)) },
          L.symbol('plus'), 'Aufgabe empfehlen'));

    const daten = freigeben => ({
      schueler_id: v.schueler.id, id: e && !e.freigegeben ? e.id : undefined, meldung_id: v.meldung ? v.meldung.id : undefined,
      termin_id: v.termin ? v.termin.id : undefined, aufgabe_id: v.aufgabe ? v.aufgabe.id : undefined, paket_id: v.paket_id || undefined,
      text: text.value, entscheidung: entscheidung ? entscheidung() : undefined, neue_frist: neueFrist ? neueFrist.value : undefined,
      kann: kannWerte, empfehlungen: Array.from(liste.children).filter(z => z.lesen).map(z => z.lesen()), freigeben,
    });
    const speichern = freigeben => async () => {
      const d = daten(freigeben);
      if (d.empfehlungen.some(x => !x.aufgabe_id)) throw new Error('Bitte bei jeder Empfehlung eine Aufgabe wählen.');
      const r = await L.api('POST', '/api/rueckmeldung', d);
      L.meldung(freigeben ? 'Freigegeben. ' + v.schueler.vorname + ' sieht die Rückmeldung jetzt.' : 'Entwurf gespeichert. Nur Sie sehen ihn.');
      return r;
    };
    const titel = 'Rückmeldung · ' + (v.aufgabe ? v.aufgabe.kuerzel + ' ' + v.aufgabe.titel : v.termin && v.termin.anlass_text ? v.termin.anlass_text : 'Feedback');
    return L.dialog({
      titel, breit: true, abbrechen: 'Schließen',
      knopf: lesen ? null : 'Freigeben',
      weitere: lesen ? [] : [{ text: 'Entwurf speichern', speichern: speichern(false) }],
      fuss: lesen ? (v.darf ? null : 'Mit Einsicht sehen Sie alles, ändern nichts.') : v.schueler.vorname + ' sieht Text, Ihre Einschätzung und die Empfehlungen erst nach „Freigeben“.',
      inhalt: el('div', { class: 'stapel', style: 'gap:14px' }, kopf,
        anlass ? L.feld('Anlass', anlass) : null,
        v.aufgabe && v.aufgabe.moodle_link ? el('a', { class: 'knopf klein', style: 'justify-self:start', href: v.aufgabe.moodle_link, target: '_blank', rel: 'noopener' },
          L.symbol('extern'), 'Abgabe in Moodle ansehen') : null,
        kannTab, entscheidungsBlock,
        el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'etikett', text: 'Text für ' + v.schueler.vorname + (lesen ? '' : ' (bearbeitbar)') }), text, textWerkzeug),
        empBlock,
        e && !e.freigegeben && !lesen ? L.nebenknopf('Entwurf verwerfen …', () => verwerfen(e, o)) : null),
      speichern: speichern(true),
    }).then(r => { if (r && o.danach) o.danach(r); return r; });
  }

  async function verwerfen(e, o) {
    const ok = await L.dialog({ titel: 'Entwurf verwerfen?', knopf: 'Verwerfen', gefaehrlich: true,
      inhalt: el('p', { text: 'Text, Einschätzung und Empfehlungen dieses Entwurfs werden gelöscht.' }),
      speichern: () => L.api('POST', '/api/rueckmeldung/' + e.id + '/verwerfen', {}) });
    if (ok && o.danach) o.danach(ok);
  }

  // Empfehlung ohne Gespräch, sofort sichtbar
  async function empfehlen(schuelerId, vorname) {
    let v;
    try { v = await vorlage({ schueler: schuelerId }); } catch (e) { L.meldung(e.message, true); return null; }
    const zeile = empfehlungZeile(v.auswahl, null, v.frist_vorschlag, false);
    return L.dialog({
      titel: 'Aufgabe empfehlen', knopf: 'Empfehlen',
      inhalt: el('div', { class: 'stapel', style: 'gap:8px' }, zeile,
        el('p', { class: 'leise klein', text: (vorname || 'Der Schüler') + ' sieht die Empfehlung sofort. Zusatzaufgaben erscheinen im Plan unter „Empfohlen für dich“.' })),
      speichern: () => {
        const d = zeile.lesen();
        if (!d.aufgabe_id) throw new Error('Bitte eine Aufgabe wählen.');
        return L.api('POST', '/api/klassen/' + v.schueler.klasse_id + '/schueler/' + schuelerId + '/empfehlungen', d);
      },
    });
  }

  return { oeffnen, empfehlen, fuellwoerter };
})();
