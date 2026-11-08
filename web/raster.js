// Lernplan-Raster (Stufe C), für die Schülerseite (bearbeitbar) und die Schülerseite der Lehrkraft (nur lesen).
// Spalten = Unterrichtstage der Klasse (Ferien und Ausfall schraffiert, „ohne Lehrkraft“ gelb), Zeilen = Aufgaben.
// Zwei Modi für den Schüler: „markieren“ (Normalfall: Tipp auf heute oder einen Unterrichtstag der letzten 7 Tage schaltet die
// Farbe grün → gelb → rot → leer, die ganze Zelle wird eingefärbt) und „planen“ (nach dem Knopf „Plan bearbeiten“: Zelle
// antippen oder mit der Maus über mehrere Tage ziehen; vergangene Tage und Tage ohne Unterricht sind gesperrt).
// Fertig gemeldete und angenommene Aufgaben sind ausgegraut. Am Handy und Tablet hochkant: Seite mit 4 Unterrichtstagen zum Blättern.
'use strict';
const Raster = (() => {
  const el = L.el;
  const STATUS = { offen: ['offen', 'offen'], geplant: ['geplant', 'geplant'], arbeit: ['arbeit', 'in Arbeit'],
    fertig: ['fertig', 'fertig gemeldet'], angenommen: ['angenommen', 'angenommen'], ueberarbeiten: ['ueberarbeiten', 'überarbeiten'] };
  const plant = t => t.status === 'unterricht' || t.status === 'ohne';
  const NW_STATUS = { bereit: ['fertig', 'bereit gemeldet'], frei: ['fertig', 'in Moodle frei'], termin: ['fertig', 'Termin gebucht'],
    gelungen: ['angenommen', 'gelungen'], nicht: ['ueberarbeiten', 'noch nicht gelungen'] };

  function statusChip(r) {
    if (r.ueber_frist) return el('span', { class: 'sc spaet', text: 'Frist überschritten' });
    const s = STATUS[r.status] || STATUS.offen;
    return el('span', { class: 'sc ' + s[0], text: r.status === 'ueberarbeiten' && r.wirksam ? 'überarbeiten bis ' + L.tag(r.wirksam) : s[1] });
  }

  function teamChip(t) {
    if (!t) return null;
    return el('span', { class: 'chip lila-hell klein', title: t.status === 'aktiv' ? 'Zweierteam: gemeinsamer Plan, eine Fertigmeldung' : 'Einladung offen' },
      L.symbol('klassen'), t.status === 'aktiv' ? 'mit ' + (t.partner || (t.a.name + ' + ' + t.b.name)) : t.eingeladen_von_mir ? 'eingeladen: ' + t.partner : 'Einladung von ' + t.partner);
  }

  function empfehlungChip(r) {
    const offen = (r.empfehlungen || []).filter(e => !e.erledigt);
    if (!offen.length) return null;
    const v = offen.find(e => e.verbindlich);
    return el('span', { class: 'chip ' + (v ? 'lila' : 'lila-hell') + ' klein', title: offen.map(e => e.hinweis).filter(Boolean).join(' · ') || null },
      L.symbol('stern'), v ? 'verbindlich' + (v.wirksam ? ' bis ' + L.tag(v.wirksam) : '') : 'empfohlen');
  }

  const FARBEN = ['g', 'y', 'r'];
  const FARBTEXT = { g: 'im Zeitplan', y: 'knapp, schaffe ich bis zur Frist', r: 'nicht im Zeitplan' };
  const MARKIER_TAGE = 7;
  const erledigt = r => r.status === 'fertig' || r.status === 'angenommen';

  function isoMinus(iso, tage) {
    const d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() - tage);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  // Handy und Tablet hochkant: statt des breiten Rasters eine Seite mit 4 Unterrichtstagen zum Blättern (Pfeile, Wischen),
  // schmale erste Spalte (Kürzel in Statusfarbe + Kurztitel), keine Spalte „Stand“. Der Seitenanfang bleibt beim Neuzeichnen.
  const SEITE = 4;
  let seitenStart = null;
  const istKompakt = () => !!(window.matchMedia && window.matchMedia('(max-width: 800px)').matches);

  // z: Zustand von /api/s/<code>/plan; o: { bearbeitbar, modus: 'markieren' | 'planen', planen(aufgabe_id, hinzu, weg),
  //   markieren(aufgabe_id, datum, farbe|null), waehlen(zeile, gruppe), oeffnen(zeile, gruppe), nachweis(n), team(bezug), kompakt }
  function zeichnen(z, o = {}) {
    const kompakt = o.kompakt !== undefined ? o.kompakt : istKompakt();
    const planModus = o.bearbeitbar && o.modus === 'planen';
    const markModus = o.bearbeitbar && !planModus;
    const markAb = isoMinus(z.heute, MARKIER_TAGE);
    const alleTage = kompakt ? z.spalten.filter(t => t.status !== 'ferien') : z.spalten;
    if (kompakt && (seitenStart === null || seitenStart > Math.max(0, alleTage.length - 1))) {
      const i = alleTage.findIndex(t => t.datum >= z.heute);
      seitenStart = Math.max(0, (i < 0 ? alleTage.length - SEITE : i) - 1);   // ein Tag zurück: zum Nachtragen der Farbe
    }
    const ort = el('div', { class: 'r-scroll' + (kompakt ? ' kompakt' : '') });
    const zurueck = el('button', { type: 'button', class: 'leicht', 'aria-label': 'frühere Tage', onclick: () => blaettern(-SEITE) }, L.symbol('links'));
    const vor = el('button', { type: 'button', class: 'leicht', 'aria-label': 'spätere Tage', onclick: () => blaettern(SEITE) }, L.symbol('rechts'));
    const seitenText = el('span', { class: 'seiten-text' });
    const heuteKnopf = el('button', { type: 'button', class: 'klein', text: 'heute', onclick: () => { seitenStart = null; seitenStart = startHeute(); bauen(); } });
    const pager = kompakt ? el('div', { class: 'seiten' }, zurueck, seitenText, heuteKnopf, vor) : null;

    function startHeute() {
      const i = alleTage.findIndex(t => t.datum >= z.heute);
      return Math.max(0, (i < 0 ? alleTage.length - SEITE : i) - 1);
    }
    function blaettern(schritt) {
      const neu = Math.min(Math.max(0, seitenStart + schritt), Math.max(0, alleTage.length - 1));
      if (neu === seitenStart) return;
      seitenStart = neu;
      bauen();
    }
    function bauen() {
      const tage = kompakt ? alleTage.slice(seitenStart, seitenStart + SEITE) : alleTage;
      L.setzen(ort, tabelleBauen(tage));
      if (pager) {
        seitenText.textContent = tage.length ? L.tag(tage[0].datum) + ' – ' + L.tag(tage[tage.length - 1].datum) : 'keine Unterrichtstage';
        zurueck.disabled = seitenStart <= 0;
        vor.disabled = seitenStart + SEITE >= alleTage.length;
        heuteKnopf.hidden = tage.some(t => t.datum === z.heute) || seitenStart === startHeute();
      }
    }
    if (kompakt) {   // Wischen nach links/rechts blättert (senkrechtes Scrollen bleibt)
      let x0 = null, y0 = null;
      ort.addEventListener('touchstart', ev => { x0 = ev.touches[0].clientX; y0 = ev.touches[0].clientY; }, { passive: true });
      ort.addEventListener('touchend', ev => {
        if (x0 === null) return;
        const dx = ev.changedTouches[0].clientX - x0, dy = ev.changedTouches[0].clientY - y0;
        x0 = null;
        if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) blaettern(dx < 0 ? SEITE : -SEITE);
      }, { passive: true });
    }
    bauen();
    return el('div', { class: 'stapel', style: 'gap:8px' },
      el('div', { class: 'legende' }, el('span', {}, el('i', { class: 'm-bal' }), 'geplant'),
        FARBEN.map(f => el('span', {}, el('i', { class: 'm-farbe f-' + f }), kompakt ? { g: 'im Zeitplan', y: 'knapp', r: 'nicht im Zeitplan' }[f] : FARBTEXT[f])),
        el('span', {}, el('span', { class: 'frist', style: 'position:static', text: 'F' }), 'Frist'), el('span', {}, el('i', { class: 'm-aus' }), 'kein Unterricht'),
        el('span', {}, el('i', { class: 'm-ohne' }), 'ohne Lehrkraft'),
        planModus ? el('span', { class: 'hinweis-modus', text: kompakt ? 'Planen: Tag antippen, Kürzel = alle Tage' : 'Planen: Tag antippen oder Balken ziehen' })
          : markModus ? el('span', { class: 'hinweis-modus', text: 'Tag antippen = Farbe für heute und die letzten 7 Tage' }) : null),
      pager, ort);

    function tabelleBauen(tage) {
      const spalten = tage.length + (kompakt ? 1 : 2);
      const kopf = el('tr', {}, el('th', { class: 'links', text: 'Aufgabe' }), kompakt ? null : el('th', { class: 'links', text: 'Stand' }),
        tage.map(t => el('th', { class: [t.datum === z.heute ? 'heute' : '', t.status !== 'unterricht' ? (t.status === 'ohne' ? 'ohne' : 'aus') : ''].join(' ').trim(),
          title: t.grund || null }, t.tag, el('br'), t.datum.slice(8, 10) + '.' + t.datum.slice(5, 7) + '.')));
      const koerper = el('tbody');
      z.pakete.forEach(p => {
        koerper.appendChild(el('tr', { class: 'paket' }, el('td', { colspan: spalten }, p.titel,
          el('span', { class: 'pm', text: [kompakt ? null : p.lernfeld, p.frist && p.frist.wirksam ? 'Frist ' + L.tag(p.frist.wirksam) : ''].filter(Boolean).join(' · ') }),
          p.team ? teamChip(p.team) : p.team_moeglich && o.team ? el('button', { type: 'button', class: 'klein team-knopf', onclick: () => o.team({ bereich: 'paket', bezug_id: p.id, titel: 'das ganze Paket ' + p.titel }) },
            L.symbol('klassen'), 'zu zweit bearbeiten') : p.team_moeglich ? el('span', { class: 'pm', text: '· zu zweit möglich' }) : null)));
        let gruppe = null;
        p.zeilen.forEach(r => {
          if (r.typ === 'empfohlen') {
            koerper.appendChild(el('tr', { class: 'wahl emp' }, el('td', { colspan: spalten },
              el('span', {}, L.symbol('stern')), o.bearbeitbar ? 'Empfohlen für dich' : 'Empfohlene Zusatzaufgaben')));
            return;
          }
          if (r.typ === 'gruppe') {
            gruppe = r;
            koerper.appendChild(el('tr', { class: 'wahl' }, el('td', { colspan: spalten },
              'Wahlgruppe ' + r.buchstabe + (r.titel && !kompakt ? ' · ' + r.titel : '') + ' · wähle ' + r.waehlen + ' von ' + r.anzahl,
              el('span', { class: 'pm', text: r.gewaehlt.length ? 'gewählt: ' + r.gewaehlt.join(', ') : 'noch nicht gewählt' }))));
            return;
          }
          koerper.appendChild(zeile(r, r.art === 'wahl' ? gruppe : null));
        });
        p.nachweise.forEach(n => koerper.appendChild(el('tr', { class: 'nw' },
          el('td', { class: 'auf' }, o.nachweis ? el('button', { type: 'button', class: 'kz', text: '◆', title: 'Gelingensnachweis öffnen', onclick: () => o.nachweis(n) })
            : el('span', { class: 'kz', text: '◆' }), (kompakt ? '' : 'Gelingensnachweis: ') + (n.art_text || '') + (n.titel && !kompakt ? ' · ' + n.titel : ''),
            kompakt && NW_STATUS[n.status] ? el('div', { class: 'kurz-status', text: NW_STATUS[n.status][1] }) : null),
          kompakt ? null : el('td', { class: 'st' }, NW_STATUS[n.status] ? el('span', { class: 'sc ' + NW_STATUS[n.status][0], text: NW_STATUS[n.status][1] }) : null,
            n.wirksam && !n.gelungen ? el('span', { class: 'leise klein' + (n.ueber_frist ? ' rot-text' : ''), text: ' bis ' + L.tag(n.wirksam) }) : null),
          tage.map(t => el('td', { class: zellKlasse(t, z) }, n.wirksam === t.datum ? el('span', { class: 'frist', text: 'F' }) : null)))));
      });
      const tabelle = el('table', { class: 'lp' + (planModus ? ' planmodus' : markModus ? ' markmodus' : '') + (kompakt ? ' kompakt' : '') },
        kompakt ? el('colgroup', {}, el('col', { class: 'c-auf' }), tage.map(() => el('col'))) : null, el('thead', {}, kopf), koerper);
      if (planModus) ziehen(tabelle, o);
      if (markModus) tabelle.addEventListener('click', ev => {
        const td = ev.target.closest ? ev.target.closest('td.mk') : null;
        if (!td) return;
        const alt = td.dataset.farbe || '';
        const neu = alt === '' ? 'g' : alt === 'g' ? 'y' : alt === 'y' ? 'r' : null;
        td.classList.remove('f-g', 'f-y', 'f-r');
        if (neu) td.classList.add('f-' + neu);
        td.dataset.farbe = neu || '';
        o.markieren(Number(td.parentNode.dataset.aufgabe), td.dataset.datum, neu);
      });
      return tabelle;

      function zeile(r, g) {
        const planbar = planModus && r.gewaehlt;
        const markbar = markModus && r.gewaehlt && !erledigt(r);
        const knopf = o.bearbeitbar && r.art === 'wahl' && !kompakt
          ? el('button', { type: 'button', class: 'klein', onclick: () => o.waehlen(r, g) }, r.gewaehlt ? 'abwählen' : 'wählen') : null;
        const kzKlasse = 'kz' + (kompakt && r.gewaehlt ? ' s-' + (r.ueber_frist ? 'spaet' : r.status) : '');
        const kzTitel = (STATUS[r.status] || STATUS.offen)[1] + (r.ueber_frist ? ', Frist überschritten' : '') + (o.oeffnen ? ' · Aufgabe öffnen' : '');
        const kz = o.oeffnen ? el('button', { type: 'button', class: kzKlasse, title: kzTitel, text: r.kuerzel, onclick: () => o.oeffnen(r, g) })
          : el('span', { class: kzKlasse, title: kzTitel, text: r.kuerzel });
        const titel = r.moodle_link ? el('a', { class: 'alink', href: r.moodle_link, target: '_blank', rel: 'noopener', text: r.titel }) : r.titel;
        return el('tr', { class: [r.gewaehlt ? '' : 'blass', r.art === 'zusatz' ? 'zusatz' : '', erledigt(r) ? 'erledigt' : ''].join(' ').trim() || null, 'data-aufgabe': r.id,
          'data-planbar': planbar ? '1' : null },
          el('td', { class: 'auf', title: r.titel }, kz, titel,
            kompakt ? (r.team && r.team.status === 'aktiv' ? el('span', { class: 'kurz-team', title: 'mit ' + r.team.partner }, L.symbol('klassen')) : null)
              : r.art === 'pflicht' ? el('span', { class: 'art', text: 'Pflicht' }) : r.art === 'zusatz' ? el('span', { class: 'art', text: r.zusatz_art === 'vertiefung' ? 'Vertiefung' : 'Wiederholung' }) : null),
          kompakt ? null : el('td', { class: 'st' }, r.gewaehlt ? statusChip(r) : null, r.ampel && r.gewaehlt ? el('span', { class: 'ampel a-' + r.ampel, title: 'letzte Ampel' }) : null,
            knopf ? ' ' : null, knopf, r.plant_nach_frist && r.gewaehlt ? el('span', { class: 'chip rot klein', text: 'nach der Frist' }) : null, empfehlungChip(r),
            r.team && r.team.bereich === 'aufgabe' ? teamChip(r.team) : null),
          tage.map((t, i) => {
            const geplant = r.plan.includes(t.datum), voriger = i > 0 && r.plan.includes(tage[i - 1].datum), naechster = i < tage.length - 1 && r.plan.includes(tage[i + 1].datum);
            const kann = planbar && plant(t) && t.datum >= z.heute;
            const mk = markbar && plant(t) && t.datum <= z.heute && t.datum >= markAb;
            const farbe = r.ist[t.datum];
            return el('td', { class: zellKlasse(t, z) + (kann ? ' kann' : '') + (mk ? ' mk' : '') + (farbe ? ' f-' + farbe : ''),
              'data-datum': kann || mk ? t.datum : null, 'data-farbe': mk ? farbe || '' : null,
              title: farbe ? FARBTEXT[farbe] : t.grund || null },
              geplant ? el('span', { class: 'bal' + (voriger ? '' : ' a') + (naechster ? '' : ' e') }) : null,
              r.wirksam === t.datum && r.gewaehlt ? el('span', { class: 'frist', text: 'F' }) : null);
          }));
      }
    }
  }

  function zellKlasse(t, z) {
    return 't' + (t.datum === z.heute ? ' heute' : '') + (t.status === 'ausfall' || t.status === 'ferien' ? ' aus' : t.status === 'ohne' ? ' ohne' : '');
  }

  // Ziehen mit Maus oder Stift über eine Zeile, Antippen mit dem Finger: erst die Anzeige, beim Loslassen an den Server
  function ziehen(tabelle, o) {
    let lauf = null;
    const zelle = ev => {
      const e = document.elementFromPoint(ev.clientX, ev.clientY);
      return e && e.closest ? e.closest('td.t.kann') : null;
    };
    const markieren = td => {
      if (!lauf || !td || td.parentNode !== lauf.zeile || lauf.tage.has(td.dataset.datum)) return;
      lauf.tage.add(td.dataset.datum);
      const bal = td.querySelector('.bal');
      if (lauf.modus === 'hinzu' && !bal) td.appendChild(el('span', { class: 'bal a e' }));
      if (lauf.modus === 'weg' && bal) bal.remove();
    };
    tabelle.addEventListener('pointerdown', ev => {
      const td = zelle(ev);
      if (!td || ev.button > 0) return;
      lauf = { zeile: td.parentNode, modus: td.querySelector('.bal') ? 'weg' : 'hinzu', tage: new Set(), maus: ev.pointerType !== 'touch',
        start: td, x: ev.clientX, y: ev.clientY };
      if (lauf.maus) { markieren(td); ev.preventDefault(); }
    });
    tabelle.addEventListener('pointermove', ev => { if (lauf && lauf.maus && ev.buttons) markieren(zelle(ev)); });
    const ende = ev => {
      if (!lauf) return;
      const l = lauf;
      // Finger: nur Antippen plant (Wischen scrollt das Raster)
      if (!l.maus && ev && Math.hypot(ev.clientX - l.x, ev.clientY - l.y) < 12) markieren(l.start);
      lauf = null;
      if (!l.tage.size) return;
      const tage = Array.from(l.tage);
      o.planen(Number(l.zeile.dataset.aufgabe), l.modus === 'hinzu' ? tage : [], l.modus === 'weg' ? tage : []);
    };
    window.addEventListener('pointerup', ende);
    window.addEventListener('pointercancel', () => { lauf = null; });
  }

  // Eintrag aus dem Ereignisprotokoll als Satz (Schülerseite der Lehrkraft)
  function ereignisText(e) {
    const d = e.daten || {};
    const tage = l => (l || []).map(x => L.tag(x)).join(', ');
    const AMPEL = { g: 'grün', y: 'gelb', r: 'rot' };
    const texte = {
      plan_neu: () => 'Erster Plan für ' + d.kuerzel + ': ' + tage(d.hinzu),
      plan: () => d.kuerzel + ': ' + [d.hinzu && d.hinzu.length ? '+ ' + tage(d.hinzu) : '', d.weg && d.weg.length ? '− ' + tage(d.weg) : ''].filter(Boolean).join(' · ')
        + (d.grund === 'ausfall' ? ' (durch Ausfall)' : ''),
      gewaehlt: () => d.kuerzel + ' gewählt',
      abgewaehlt: () => d.kuerzel + ' abgewählt' + (d.weg && d.weg.length ? ', Planung ' + tage(d.weg) + ' entfernt' : ''),
      tagesabschluss: () => 'Tag abgeschlossen: ' + (d.bearbeitet.length ? d.bearbeitet.map(b => b.kuerzel + ' ' + AMPEL[b.ampel]).join(', ') : 'nichts bearbeitet'),
      kann_vorher: () => 'Kann-Liste vorher: ' + d.kuerzel + ' Stufe ' + d.stufe,
      kann_nachher: () => 'Kann-Liste nachher: ' + d.kuerzel + ' Stufe ' + d.stufe,
      schueler_angelegt: () => 'in die Klasse aufgenommen' + (d.quelle === 'moodle' ? ' (Moodle-Liste)' : ''),
      code_erneuert: () => 'neuer Zugangscode',
      schueler_umbenannt: () => 'umbenannt: ' + d.alt + ' → ' + d.name,
      schueler_archiviert: () => 'archiviert', schueler_aktiv: () => 'wieder aktiv',
      fertig: () => d.kuerzel + ' fertig gemeldet' + (d.kann && d.kann.length ? ' (' + d.kann.map(k => k.kuerzel + ' ' + k.stufe).join(', ') + ')' : ''),
      fertig_zurueck: () => d.kuerzel + ': Fertigmeldung zurückgezogen',
      rueckmeldung: () => 'Rückmeldung' + (d.kuerzel ? ' zu ' + d.kuerzel : '') + (d.entscheidung === 'angenommen' ? ': angenommen'
        : d.entscheidung === 'ueberarbeiten' ? ': überarbeiten bis ' + L.tag(d.neue_frist) : '')
        + (d.empfehlungen && d.empfehlungen.length ? ', empfohlen: ' + d.empfehlungen.map(e => e.kuerzel + (e.verbindlich ? ' (verbindlich)' : '')).join(', ') : ''),
      empfehlung: () => d.kuerzel + ' empfohlen' + (d.verbindlich ? ', verbindlich bis ' + L.tag(d.frist) : ''),
      empfehlung_entfernt: () => 'Empfehlung ' + d.kuerzel + ' entfernt',
      empfehlung_erledigt: () => 'Empfehlung ' + d.kuerzel + ' erledigt', empfehlung_offen: () => 'Empfehlung ' + d.kuerzel + ' wieder offen',
      hilfe: () => 'Hilfe gerufen', hilfe_zurueck: () => 'Hilfe zurückgezogen', hilfe_erledigt: () => 'Hilfe erledigt',
      termin_gebucht: () => 'Feedbacktermin gebucht: ' + L.tag(d.datum) + ' ' + d.beginn,
      termin_abgesagt: () => 'Termin ' + L.tag(d.datum) + ' ' + d.beginn + ' abgesagt',
      team_eingeladen: () => 'Zweierteam (' + d.bezug + ') mit ' + d.partner + ': Einladung',
      team_aktiv: () => 'Zweierteam (' + d.bezug + ') mit ' + d.partner + ' bestätigt',
      team_gebildet: () => 'Zweierteam (' + d.bezug + ') mit ' + d.partner + ' von der Lehrkraft gebildet',
      team_abgelehnt: () => 'Einladung zum Zweierteam (' + d.bezug + ') abgelehnt', team_zurueck: () => 'Einladung zum Zweierteam (' + d.bezug + ') zurückgezogen',
      team_aufgeloest: () => 'Zweierteam (' + d.bezug + ') mit ' + d.partner + ' aufgelöst' + (d.grund ? ' (' + d.grund + ')' : ''),
      markiert: () => d.kuerzel + ' am ' + L.tag(d.datum) + ': ' + (d.ampel ? { g: 'im Zeitplan', y: 'knapp', r: 'nicht im Zeitplan' }[d.ampel] : 'Markierung entfernt'),
      gespraech: () => 'Gespräch nötig zu ' + d.kuerzel + ': ' + L.tag(d.datum) + ' ' + d.beginn,
      bereit: () => 'bereit gemeldet für den Gelingensnachweis (' + d.paket + ', ' + d.versuch + '. Versuch)',
      bereit_zurueck: () => 'Bereitmeldung zurückgezogen (' + d.versuch + '. Versuch)',
      freigeschaltet: () => 'Test in Moodle freigeschaltet (' + d.versuch + '. Versuch)', freischaltung_zurueck: () => 'Freischaltung zurückgenommen',
      nachweis_ergebnis: () => 'Gelingensnachweis, ' + d.versuch + '. Versuch: ' + (d.ergebnis === 'gelungen' ? 'gelungen' : 'noch nicht gelungen, neue Frist ' + L.tag(d.neue_frist))
        + (d.punkte !== null && d.punkte !== undefined ? ' (' + d.punkte + ' Punkte)' : d.note ? ' (Note ' + d.note + ')' : ''),
      zeitfenster_angelegt: () => 'Zeitfenster angelegt', zeitfenster_entfernt: () => 'Zeitfenster entfernt',
    };
    try { return (texte[e.art] || (() => e.art))(); } catch (f) { return e.art; }
  }

  return { zeichnen, ereignisText, statusChip, STATUS, FARBTEXT, teamChip };
})();
