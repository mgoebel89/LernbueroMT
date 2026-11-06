// Lernpakete (Stufe B): Übersicht je Klasse und Vorlagen, Paket-Editor mit Pflichtaufgaben, Wahlgruppen,
// Zusatzaufgaben, Kann-Liste und Gelingensnachweis. Jede Änderung läuft über ein Overlay.
'use strict';
const Pakete = (() => {
  const el = L.el;
  const NW_ART = { moodle: 'Moodle-Test', praxis: 'Praktische Prüfung', fachgespraech: 'Fachgespräch' };
  const ERGEBNIS = { gelungen: 'gelungen / noch nicht gelungen', punkte: 'gelungen / noch nicht + Punkte', note: 'gelungen / noch nicht + Note' };
  const ZUSATZ = { vertiefung: 'Vertiefung', wiederholung: 'Wiederholung' };

  const api = (pid, pfad, daten) => L.api('POST', '/api/pakete/' + pid + (pfad || ''), daten);

  // --- Übersicht ---

  async function uebersicht(klasseId) {
    titelSetzen('Pakete');
    const [{ klassen }, { vorlagen }] = await Promise.all([L.api('GET', '/api/klassen'), L.api('GET', '/api/vorlagen')]);
    const meine = klassen.filter(k => k.rolle === 'team' || k.rolle === 'einsicht');
    const aktiv = meine.find(k => k.id === klasseId) || meine[0];
    const pakete = aktiv ? (await L.api('GET', '/api/klassen/' + aktiv.id + '/pakete')).pakete : [];
    const wahl = el('select', { onchange: ev => { location.hash = 'pakete/' + ev.target.value; } },
      meine.map(k => el('option', { value: k.id, text: k.name + (k.schuljahr ? ' · ' + k.schuljahr : '') })));
    if (aktiv) wahl.value = aktiv.id;
    const karte = p => el('a', { class: 'karte klassenkarte', href: '#paket/' + p.id },
      el('div', { class: 'zeile' }, el('h3', { text: p.titel }), el('span', { class: 'rechts' },
        p.lernfeld ? el('span', { class: 'chip', text: p.lernfeld }) : null,
        p.archiviert ? el('span', { class: 'chip', text: 'archiviert' }) : p.freigabe ? el('span', { class: 'chip gruen', text: 'ab ' + L.tag(p.freigabe) })
          : p.klasse_id ? el('span', { class: 'chip gelb', text: 'Entwurf' }) : el('span', { class: 'chip', text: 'Vorlage' }))),
      el('div', { class: 'leise klein', text: p.aufgaben + ' Aufgaben' + (p.frist ? ' · Paket-Frist ' + L.tag(p.frist) : '') }));
    L.setzen(inhalt,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Lernpakete' }),
        meine.length ? wahl : null,
        aktiv && aktiv.rolle === 'team' ? el('button', { class: 'haupt', type: 'button', onclick: () => neu(aktiv, vorlagen) }, L.symbol('plus'), 'Paket') : null),
      !meine.length ? el('div', { class: 'leer' }, 'Sie sind noch in keiner Klasse eingetragen. ', el('a', { href: '#klassen', text: 'Zu den Klassen' })) : null,
      aktiv ? (pakete.length ? el('div', { class: 'raster' }, pakete.map(karte))
        : el('div', { class: 'leer', text: 'Noch kein Paket für ' + aktiv.name + '.' })) : null,
      el('h2', { class: 'dreieck', text: 'Meine Vorlagen' }),
      vorlagen.length ? el('div', { class: 'raster' }, vorlagen.map(karte))
        : el('p', { class: 'leise klein', text: 'Noch keine Vorlage. Jedes Paket lässt sich mit „Kopieren“ als Vorlage speichern, Vorlagen sehen nur Sie.' }));
  }

  async function neu(k, vorlagen) {
    const titel = el('input', { required: true, maxlength: 80, placeholder: 'z. B. Elektropneumatik' });
    const lf = el('input', { maxlength: 20, placeholder: 'LF 4' });
    const aus = el('select', {}, el('option', { value: '', text: 'leer beginnen' }), vorlagen.map(v => el('option', { value: v.id, text: 'aus Vorlage: ' + v.titel })));
    const ok = await L.dialog({
      titel: 'Neues Paket für ' + k.name, knopf: 'Anlegen',
      inhalt: el('div', { class: 'felder' }, L.feld('Beginnen', aus), L.feld('Titel', titel, 'bei einer Vorlage leer lassen = Titel der Vorlage'), L.feld('Lernfeld', lf)),
      speichern: () => aus.value
        ? L.api('POST', '/api/pakete/' + aus.value + '/kopieren', { ziel_klasse_id: k.id, titel: titel.value || undefined })
        : L.api('POST', '/api/pakete', { klasse_id: k.id, titel: titel.value, lernfeld: lf.value }),
    });
    if (ok) location.hash = 'paket/' + ok.paket.id;
  }

  // --- Editor ---

  async function editor(pid) {
    const { paket: p } = await L.api('GET', '/api/pakete/' + pid);
    zeichnen(p);
  }

  function fristText(x) {
    if (!x.frist) return el('span', { class: 'leise', text: '–' });
    const geerbt = x.quelle && x.quelle !== 'eigen';
    return el('span', {}, el('span', { class: geerbt ? 'leise' : null, text: L.tag(x.wirksam || x.frist) }),
      geerbt ? el('span', { class: 'leise klein', text: x.quelle === 'gruppe' ? ' (Gruppe)' : ' (Paket)' }) : null,
      x.hinweis ? el('span', { class: 'chip gelb klein', title: 'Die Frist rutscht auf den nächsten Unterrichtstag.',
        text: 'statt ' + L.tag(x.frist) + ': ' + x.hinweis }) : null);
  }

  function zeichnen(p) {
    titelSetzen(p.titel);
    const darf = p.darf_aendern;
    const neu = (pfad, daten) => api(p.id, pfad, daten).then(r => { zeichnen(r.paket); return r; });
    const pfeile = (pfad) => darf ? [
      el('button', { type: 'button', class: 'klein leicht', title: 'nach oben', onclick: () => neu(pfad, { verschieben: -1 }).catch(e => L.meldung(e.message, true)) }, L.symbol('hoch_pfeil')),
      el('button', { type: 'button', class: 'klein leicht', title: 'nach unten', onclick: () => neu(pfad, { verschieben: 1 }).catch(e => L.meldung(e.message, true)) }, L.symbol('runter_pfeil'))] : [];
    const link = a => a.moodle_link ? el('a', { href: a.moodle_link, target: '_blank', rel: 'noopener', title: a.moodle_link, class: 'klein' }, L.symbol('extern')) : null;
    const zeile = a => el('tr', {},
      el('td', { class: 'mono', text: a.kuerzel }),
      el('td', {}, a.titel, ' ', link(a), a.kann.length ? el('span', { class: 'leise klein', text: ' · ' + p.kann.filter(k => a.kann.includes(k.id)).map(k => k.kuerzel).join(', ') }) : null),
      el('td', {}, a.art === 'pflicht' ? el('span', { class: 'chip', text: 'Pflicht' }) : a.art === 'wahl' ? el('span', { class: 'chip blau', text: 'Wahl' })
        : el('span', { class: 'chip gelb', text: ZUSATZ[a.zusatz_art] })),
      el('td', {}, a.art === 'zusatz' ? el('span', { class: 'leise klein', text: 'bei Empfehlung' }) : fristText(a)),
      el('td', { class: 'leise klein', text: a.voraussetzung ? 'nach ' + a.voraussetzung : '' }),
      el('td', { class: 'knoepfe' }, pfeile('/aufgaben/' + a.id), darf ? el('button', { type: 'button', class: 'klein', onclick: () => aufgabeDialog(p, a) }, 'Bearbeiten') : null));
    const zeilen = [];
    p.ablauf.forEach(e => {
      if (e.typ === 'aufgabe') { zeilen.push(zeile(e)); return; }
      zeilen.push(el('tr', { class: 'gruppe-zeile' }, el('td', { colspan: 6 }, el('div', { class: 'zeile' },
        el('b', { text: 'Wahlgruppe ' + e.buchstabe }), e.titel ? ' · ' + e.titel : '', ' · wähle ' + e.waehlen + ' von ' + e.aufgaben.length,
        e.frist ? el('span', { class: 'klein' }, ' · Frist ', fristText(e)) : null,
        el('span', { class: 'rechts' }, pfeile('/gruppen/' + e.id),
          darf ? el('button', { type: 'button', class: 'klein', onclick: () => aufgabeDialog(p, null, 'wahl', e) }, L.symbol('plus'), 'Aufgabe') : null,
          darf ? el('button', { type: 'button', class: 'klein', onclick: () => gruppeDialog(p, e) }, 'Bearbeiten') : null)))));
      e.aufgaben.forEach(a => zeilen.push(zeile(a)));
      if (!e.aufgaben.length) zeilen.push(el('tr', {}, el('td', { colspan: 6, class: 'leise klein', text: 'Noch keine Aufgabe in dieser Gruppe.' })));
    });
    if (p.zusatz.length) {
      zeilen.push(el('tr', { class: 'gruppe-zeile zusatz' }, el('td', { colspan: 6 }, el('b', { text: 'Zusatzaufgaben' }),
        el('span', { class: 'leise klein', text: ' · nur sichtbar für Schüler, denen Sie sie empfehlen' }))));
      p.zusatz.forEach(a => zeilen.push(zeile(a)));
    }

    L.setzen(inhalt,
      el('div', { class: 'werkzeug' },
        el('h1', { class: 'dreieck', text: p.titel }),
        p.lernfeld ? el('span', { class: 'chip', text: p.lernfeld }) : null,
        p.vorlage ? el('span', { class: 'chip', text: 'Vorlage' }) : el('a', { class: 'chip blau', href: '#pakete/' + p.klasse_id, text: p.klasse }),
        p.archiviert ? el('span', { class: 'chip', text: 'archiviert' }) : null,
        darf ? el('button', { type: 'button', onclick: () => paketDialog(p) }, 'Bearbeiten') : null,
        darf && !p.vorlage ? el('button', { type: 'button', class: p.freigabe ? null : 'haupt', onclick: () => freigabeDialog(p) }, p.freigabe ? 'Freigabe ändern' : 'Freigeben …') : null,
        el('button', { type: 'button', onclick: () => kopierDialog(p) }, L.symbol('kopie'), 'Kopieren')),
      el('div', { class: 'zeile klein' },
        p.vorlage ? el('span', { class: 'leise', text: 'Vorlage: nur Sie sehen sie. Zum Arbeiten in eine Klasse kopieren.' })
          : p.freigabe ? el('span', {}, 'Für die Schüler freigegeben ab ', el('b', { text: L.tag(p.freigabe.wirksam || p.freigabe.datum, true) }),
            p.freigabe.hinweis ? el('span', { class: 'chip gelb klein', text: 'statt ' + L.tag(p.freigabe.datum) + ': ' + p.freigabe.hinweis }) : null)
          : el('span', { class: 'chip gelb', text: 'Entwurf: die Schüler sehen das Paket noch nicht' }),
        el('span', { class: 'leise', text: ' · ' }), 'Paket-Frist: ', p.frist.frist ? fristText(p.frist) : el('span', { class: 'leise', text: 'keine' })),
      el('div', { class: 'karte stapel' },
        el('h2', { text: 'Aufgaben' }),
        zeilen.length ? el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
          el('thead', {}, el('tr', {}, ['Kürzel', 'Aufgabe', 'Art', 'Frist', 'Voraussetzung', ''].map(t => el('th', { text: t })))), el('tbody', {}, zeilen)))
          : el('div', { class: 'leer', text: 'Noch keine Aufgabe. Jede Aufgabe bekommt ihren Link in Moodle.' }),
        darf ? el('div', { class: 'zeile' },
          el('button', { type: 'button', class: 'klein', onclick: () => aufgabeDialog(p, null, 'pflicht') }, L.symbol('plus'), 'Pflichtaufgabe'),
          el('button', { type: 'button', class: 'klein', onclick: () => gruppeDialog(p, null) }, L.symbol('plus'), 'Wahlgruppe'),
          el('button', { type: 'button', class: 'klein', onclick: () => aufgabeDialog(p, null, 'zusatz') }, L.symbol('plus'), 'Zusatzaufgabe')) : null),
      el('div', { class: 'zwei-spalten' },
        el('div', { class: 'karte stapel' },
          el('h2', { text: 'Kann-Liste' }),
          el('p', { class: 'leise klein', text: 'Die Schüler schätzen jede Aussage vorher und nachher ein, auf 4 Stufen von „muss noch viel üben“ bis „kann es perfekt“.' }),
          p.kann.length ? el('div', { class: 'stapel', style: 'gap:6px' }, p.kann.map(k => el('div', { class: 'zeile' },
            el('b', { class: 'mono', text: k.kuerzel }), el('span', { style: 'flex:1;min-width:180px' }, 'Ich kann ' + k.text,
              k.aufgaben_kuerzel.length ? el('span', { class: 'leise klein', text: ' · ' + k.aufgaben_kuerzel.join(', ') }) : el('span', { class: 'chip gelb klein', text: 'keine Aufgabe' })),
            el('span', {}, pfeile('/kann/' + k.id), darf ? el('button', { type: 'button', class: 'klein', onclick: () => kannDialog(p, k) }, 'Bearbeiten') : null))))
            : el('div', { class: 'leer', text: 'Noch keine Kann-Aussage.' }),
          darf ? el('div', {}, el('button', { type: 'button', class: 'klein', onclick: () => kannDialog(p, null) }, L.symbol('plus'), 'Kann-Aussage')) : null),
        el('div', { class: 'karte stapel' },
          el('h2', { text: 'Gelingensnachweis' }),
          p.nachweise.length ? el('div', { class: 'stapel', style: 'gap:8px' }, p.nachweise.map(n => el('div', { class: 'zeile' },
            el('b', { text: n.titel || NW_ART[n.art] }), el('span', { class: 'chip', text: NW_ART[n.art] }),
            el('span', { class: 'leise klein', text: ERGEBNIS[n.ergebnis].replace('+ Punkte', '+ Punkte (max. ' + n.max_punkte + ')') }),
            el('span', { class: 'klein' }, 'Frist ', fristText(n)), n.moodle_link ? link(n) : null,
            darf ? el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => nachweisDialog(p, n) }, 'Bearbeiten')) : null)))
            : el('div', { class: 'leer', text: 'Noch kein Gelingensnachweis.' }),
          el('p', { class: 'leise klein', text: 'Vor der Bereitmeldung schätzt der Schüler alle Kann-Aussagen „nachher“ ein. Fachgespräch und praktische Prüfung bucht er in Ihren Prüfungszeiten.' }),
          darf ? el('div', {}, el('button', { type: 'button', class: 'klein', onclick: () => nachweisDialog(p, null) }, L.symbol('plus'), 'Gelingensnachweis')) : null)),
      darf ? null : el('p', { class: 'leise klein', text: 'Sie haben Einsicht in diese Klasse und können das Paket nicht ändern.' }));
  }

  const datumFeld = wert => el('input', { type: 'date', value: wert || '' });
  const fertig = r => { if (r) zeichnen(r.paket); };
  const entfernen = (titel, text, pfad, pid) => L.nebenknopf('Entfernen …', async () => {
    fertig(await L.dialog({ titel, knopf: 'Entfernen', gefaehrlich: true, inhalt: el('p', { text }), speichern: () => api(pid, pfad, { aktiv: false }) }));
  });

  function alleAufgaben(p) {
    return [].concat(...p.ablauf.map(e => e.typ === 'aufgabe' ? [e] : e.aufgaben), p.zusatz);
  }

  async function aufgabeDialog(p, a, art, gruppe) {
    art = a ? a.art : art;
    const titel = el('input', { required: true, maxlength: 120, value: a ? a.titel : '' });
    const kuerzel = el('input', { maxlength: 6, value: a ? a.kuerzel : '', placeholder: 'automatisch' });
    const frist = datumFeld(a ? a.eigene_frist : '');
    const link = el('input', { type: 'url', value: a ? a.moodle_link : '', placeholder: 'https://moodle…/mod/assign/view.php?id=…' });
    const andere = alleAufgaben(p).filter(x => (!a || x.id !== a.id) && x.art !== 'zusatz');
    const vor = el('select', {}, el('option', { value: '', text: 'keine' }), andere.map(x => el('option', { value: x.id, text: x.kuerzel + ' ' + x.titel })));
    vor.value = a && a.voraussetzung_id ? a.voraussetzung_id : '';
    const zusatz = el('select', {}, Object.entries(ZUSATZ).map(([w, t]) => el('option', { value: w, text: t })));
    zusatz.value = a && a.zusatz_art ? a.zusatz_art : 'vertiefung';
    const was = art === 'pflicht' ? 'Pflichtaufgabe' : art === 'wahl' ? 'Aufgabe in Wahlgruppe ' + (gruppe ? gruppe.buchstabe : '') : 'Zusatzaufgabe';
    fertig(await L.dialog({
      titel: a ? a.kuerzel + ' bearbeiten' : 'Neue ' + was, knopf: a ? 'Speichern' : 'Anlegen',
      inhalt: el('div', { class: 'felder' },
        el('div', { class: 'felder zwei' }, L.feld('Titel', titel), L.feld('Kürzel', kuerzel)),
        L.feld('Link zur Aufgabe in Moodle', link, 'Adresse aus der Browserzeile, wenn die Aufgabe in Moodle offen ist'),
        art === 'zusatz' ? L.feld('Art der Zusatzaufgabe', zusatz, 'Frist setzen Sie, wenn Sie sie einem Schüler verbindlich empfehlen')
          : el('div', { class: 'felder zwei' }, L.feld('Frist', frist, art === 'wahl' ? 'leer = Frist der Wahlgruppe' : 'leer = Paket-Frist'),
            L.feld('Voraussetzung', vor, 'vorgemerkt, die Reihenfolge bleibt vorerst frei')),
        a ? el('div', {}, entfernen(a.kuerzel + ' entfernen?', '„' + a.titel + '“ verschwindet aus dem Paket. Schon Geplantes der Schüler bleibt im Verlauf.', '/aufgaben/' + a.id, p.id)) : null),
      speichern: () => {
        const d = { titel: titel.value, moodle_link: link.value };
        if (kuerzel.value) d.kuerzel = kuerzel.value;
        if (art === 'zusatz') d.zusatz_art = zusatz.value;
        else { d.frist = frist.value || null; d.voraussetzung_id = vor.value ? Number(vor.value) : null; }
        if (!a) { d.art = art; if (gruppe) d.wahlgruppe_id = gruppe.id; }
        return api(p.id, a ? '/aufgaben/' + a.id : '/aufgaben', d);
      },
    }));
  }

  async function gruppeDialog(p, g) {
    const titel = el('input', { maxlength: 80, value: g ? g.titel : '', placeholder: 'z. B. Lernsituation' });
    const waehlen = el('input', { type: 'number', min: 1, max: 9, value: g ? g.waehlen : 1, required: true });
    const frist = datumFeld(g ? g.eigene_frist : '');
    fertig(await L.dialog({
      titel: g ? 'Wahlgruppe ' + g.buchstabe : 'Neue Wahlgruppe', knopf: g ? 'Speichern' : 'Anlegen',
      inhalt: el('div', { class: 'felder' }, L.feld('Titel', titel),
        el('div', { class: 'felder zwei' }, L.feld('Wie viele wählen?', waehlen, '„wähle 1 von 3“'), L.feld('Gemeinsame Frist', frist, 'leer = Paket-Frist')),
        g ? el('div', {}, entfernen('Wahlgruppe ' + g.buchstabe + ' entfernen?', 'Die Gruppe und ihre Aufgaben verschwinden aus dem Paket.', '/gruppen/' + g.id, p.id))
          : el('p', { class: 'leise klein', text: 'Danach legen Sie die Aufgaben der Gruppe an (A1, A2, …).' })),
      speichern: () => api(p.id, g ? '/gruppen/' + g.id : '/gruppen', { titel: titel.value, waehlen: Number(waehlen.value), frist: frist.value || null }),
    }));
  }

  async function kannDialog(p, k) {
    const text = el('textarea', { required: true, maxlength: 200, rows: 2, placeholder: 'Zylinderkräfte und Luftverbrauch berechnen.' });
    text.value = k ? k.text : '';
    const kaesten = alleAufgaben(p).map(a => el('label', { class: 'haken klein' },
      el('input', { type: 'checkbox', value: a.id, checked: k && k.aufgaben.includes(a.id) }), a.kuerzel + ' ' + a.titel));
    fertig(await L.dialog({
      titel: k ? k.kuerzel + ' bearbeiten' : 'Neue Kann-Aussage', knopf: k ? 'Speichern' : 'Anlegen',
      inhalt: el('div', { class: 'felder' }, L.feld('Ich kann …', text),
        el('div', { class: 'stapel', style: 'gap:4px' }, el('div', { class: 'etikett', text: 'Erarbeitet in' }),
          kaesten.length ? kaesten : el('p', { class: 'leise klein', text: 'Legen Sie zuerst Aufgaben an.' })),
        k ? el('div', {}, entfernen(k.kuerzel + ' entfernen?', 'Die Aussage verschwindet aus der Kann-Liste.', '/kann/' + k.id, p.id)) : null),
      speichern: form => api(p.id, k ? '/kann/' + k.id : '/kann', { text: text.value,
        aufgaben: Array.from(form.querySelectorAll('input[type=checkbox]:checked'), c => Number(c.value)) }),
    }));
  }

  async function nachweisDialog(p, n) {
    const titel = el('input', { maxlength: 80, value: n ? n.titel : '', placeholder: 'leer = Art als Titel' });
    const art = el('select', {}, Object.entries(NW_ART).map(([w, t]) => el('option', { value: w, text: t })));
    art.value = n ? n.art : 'moodle';
    const ergebnis = el('select', {}, Object.entries(ERGEBNIS).map(([w, t]) => el('option', { value: w, text: t })));
    ergebnis.value = n ? n.ergebnis : 'gelungen';
    const punkte = el('input', { type: 'number', min: 1, max: 1000, value: n && n.max_punkte ? n.max_punkte : 40 });
    const frist = datumFeld(n ? n.eigene_frist : '');
    const link = el('input', { type: 'url', value: n ? n.moodle_link : '', placeholder: 'https://moodle…/mod/quiz/view.php?id=…' });
    const punkteFeld = L.feld('Höchste Punktzahl', punkte), linkFeld = L.feld('Link zum Test in Moodle', link);
    const sichtbar = () => { punkteFeld.hidden = ergebnis.value !== 'punkte'; linkFeld.hidden = art.value !== 'moodle'; };
    art.addEventListener('change', sichtbar); ergebnis.addEventListener('change', sichtbar); sichtbar();
    fertig(await L.dialog({
      titel: n ? 'Gelingensnachweis bearbeiten' : 'Neuer Gelingensnachweis', knopf: n ? 'Speichern' : 'Anlegen',
      inhalt: el('div', { class: 'felder' }, el('div', { class: 'felder zwei' }, L.feld('Art', art), L.feld('Titel', titel)),
        el('div', { class: 'felder zwei' }, L.feld('Ergebnis', ergebnis), punkteFeld), el('div', { class: 'felder zwei' }, L.feld('Frist', frist, 'leer = Paket-Frist'), linkFeld),
        n ? el('div', {}, entfernen('Gelingensnachweis entfernen?', 'Der Nachweis verschwindet aus dem Paket.', '/nachweise/' + n.id, p.id)) : null),
      speichern: () => api(p.id, n ? '/nachweise/' + n.id : '/nachweise', { titel: titel.value, art: art.value, ergebnis: ergebnis.value,
        max_punkte: Number(punkte.value), frist: frist.value || null, moodle_link: link.value }),
    }));
  }

  async function paketDialog(p) {
    const titel = el('input', { required: true, maxlength: 80, value: p.titel });
    const lf = el('input', { maxlength: 20, value: p.lernfeld });
    const frist = datumFeld(p.frist.frist);
    const archiv = el('input', { type: 'checkbox', checked: p.archiviert });
    fertig(await L.dialog({
      titel: 'Paket bearbeiten',
      inhalt: el('div', { class: 'felder' }, L.feld('Titel', titel), el('div', { class: 'felder zwei' }, L.feld('Lernfeld', lf), L.feld('Paket-Frist', frist, 'gilt für alles ohne eigene Frist')),
        el('label', { class: 'haken' }, archiv, 'archiviert (Schüler sehen es nicht mehr in der Planung)')),
      speichern: () => api(p.id, '', { titel: titel.value, lernfeld: lf.value, frist: frist.value || null, archiviert: archiv.checked }),
    }));
  }

  async function freigabeDialog(p) {
    const { tage, heute } = await L.api('GET', '/api/klassen/' + p.klasse_id + '/tage');
    const kommende = tage.filter(t => t.datum >= heute && (t.status === 'unterricht' || t.status === 'ohne')).slice(0, 12);
    const wahl = el('select', {}, kommende.map(t => el('option', { value: t.datum, text: L.tag(t.datum, true) })),
      el('option', { value: 'datum', text: 'anderes Datum …' }), p.freigabe ? el('option', { value: '', text: 'Freigabe zurücknehmen (wieder Entwurf)' }) : null);
    if (p.freigabe) wahl.value = p.freigabe.datum;
    const datum = datumFeld(p.freigabe ? p.freigabe.datum : heute);
    const datumFeldEl = L.feld('Datum', datum);
    const sichtbar = () => { datumFeldEl.hidden = wahl.value !== 'datum'; };
    wahl.addEventListener('change', sichtbar);
    if (p.freigabe && !kommende.some(t => t.datum === p.freigabe.datum)) wahl.value = 'datum';
    sichtbar();
    fertig(await L.dialog({
      titel: 'Paket freigeben', knopf: 'Speichern',
      inhalt: el('div', { class: 'felder' },
        el('p', { class: 'leise', text: 'Ab diesem Unterrichtstag sehen die Schüler von ' + p.klasse + ' das Paket in ihrem Plan und können es planen. Die Planung selbst kommt mit Stufe C.' }),
        kommende.length ? L.feld('Freigeben ab', wahl) : el('p', { class: 'banner warnung', text: 'Für die Klasse sind noch keine Unterrichtstage eingetragen (Klassenseite).' }), datumFeldEl),
      speichern: () => api(p.id, '', { freigabe: wahl.value === 'datum' || !kommende.length ? datum.value : wahl.value || null }),
    }));
  }

  async function kopierDialog(p) {
    const { klassen } = await L.api('GET', '/api/klassen');
    const ziele = klassen.filter(k => k.rolle === 'team');
    const ziel = el('select', {}, el('option', { value: 'vorlage', text: 'als meine Vorlage' }),
      ziele.map(k => el('option', { value: k.id, text: 'in Klasse ' + k.name + (k.schuljahr ? ' · ' + k.schuljahr : '') })));
    const titel = el('input', { required: true, maxlength: 80, value: p.titel });
    const ok = await L.dialog({
      titel: 'Paket kopieren', knopf: 'Kopieren',
      inhalt: el('div', { class: 'felder' }, L.feld('Wohin?', ziel), L.feld('Titel der Kopie', titel),
        el('p', { class: 'leise klein', text: 'Kopiert werden Aufgaben, Wahlgruppen, Zusatzaufgaben, Kann-Liste und Gelingensnachweis mit Moodle-Links, aber keine Daten (Freigabe, Fristen).' })),
      speichern: () => api(p.id, '/kopieren', { ziel_klasse_id: ziel.value === 'vorlage' ? null : Number(ziel.value), titel: titel.value }),
    });
    if (ok) { L.meldung('Kopie angelegt.'); location.hash = 'paket/' + ok.paket.id; }
  }

  return { uebersicht, editor };
})();
