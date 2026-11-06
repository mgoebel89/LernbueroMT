// Lernplan-Raster (Stufe C), für die Schülerseite (bearbeitbar) und die Schülerseite der Lehrkraft (nur lesen).
// Spalten = Unterrichtstage der Klasse (Ferien und Ausfall schraffiert, „ohne Lehrkraft“ gelb), Zeilen = Aufgaben.
// Planen: Zelle antippen oder mit der Maus über mehrere Tage ziehen. Vergangene Tage und Tage ohne Unterricht sind gesperrt.
'use strict';
const Raster = (() => {
  const el = L.el;
  const STATUS = { offen: ['offen', 'offen'], geplant: ['geplant', 'geplant'], arbeit: ['arbeit', 'in Arbeit'] };
  const plant = t => t.status === 'unterricht' || t.status === 'ohne';

  function statusChip(r) {
    if (r.ueber_frist && r.status !== 'offen') return el('span', { class: 'sc spaet', text: 'Frist überschritten' });
    if (r.ueber_frist) return el('span', { class: 'sc spaet', text: 'Frist überschritten' });
    const s = STATUS[r.status];
    return el('span', { class: 'sc ' + s[0], text: s[1] });
  }

  // z: Zustand von /api/s/<code>/plan; o: { bearbeitbar, planen(aufgabe_id, hinzu, weg), waehlen(zeile, gruppe) }
  function zeichnen(z, o = {}) {
    const tage = z.spalten;
    const kopf = el('tr', {}, el('th', { class: 'links', text: 'Aufgabe' }), el('th', { class: 'links', text: 'Stand' }),
      tage.map(t => el('th', { class: [t.datum === z.heute ? 'heute' : '', t.status !== 'unterricht' ? (t.status === 'ohne' ? 'ohne' : 'aus') : ''].join(' ').trim(),
        title: t.grund || null }, t.tag, el('br'), t.datum.slice(8, 10) + '.' + t.datum.slice(5, 7) + '.')));
    const koerper = el('tbody');
    z.pakete.forEach(p => {
      koerper.appendChild(el('tr', { class: 'paket' }, el('td', { colspan: tage.length + 2 }, p.titel,
        el('span', { class: 'pm', text: [p.lernfeld, p.frist && p.frist.wirksam ? 'Paket-Frist ' + L.tag(p.frist.wirksam) : ''].filter(Boolean).join(' · ') }))));
      let gruppe = null;
      p.zeilen.forEach(r => {
        if (r.typ === 'gruppe') {
          gruppe = r;
          koerper.appendChild(el('tr', { class: 'wahl' }, el('td', { colspan: tage.length + 2 },
            'Wahlgruppe ' + r.buchstabe + (r.titel ? ' · ' + r.titel : '') + ' · wähle ' + r.waehlen + ' von ' + r.anzahl,
            el('span', { class: 'pm', text: r.gewaehlt.length ? 'gewählt: ' + r.gewaehlt.join(', ') : 'noch nicht gewählt' }))));
          return;
        }
        koerper.appendChild(zeile(r, r.art === 'wahl' ? gruppe : null));
      });
      p.nachweise.forEach(n => koerper.appendChild(el('tr', { class: 'nw' },
        el('td', { class: 'auf' }, el('span', { class: 'kz', text: '◆' }), 'Gelingensnachweis' + (n.titel ? ': ' + n.titel : '')),
        el('td', { class: 'st leise klein', text: n.wirksam ? 'bis ' + L.tag(n.wirksam) : '' }),
        tage.map(t => el('td', { class: zellKlasse(t, z) }, n.wirksam === t.datum ? el('span', { class: 'frist', text: 'F' }) : null)))));
    });
    const tabelle = el('table', { class: 'lp' }, el('thead', {}, kopf), koerper);
    if (o.bearbeitbar) ziehen(tabelle, o);
    return el('div', { class: 'stapel', style: 'gap:8px' },
      el('div', { class: 'legende' }, el('span', {}, el('i', { class: 'm-bal' }), 'geplant'), el('span', {}, el('i', { class: 'm-ist' }), 'bearbeitet'),
        el('span', {}, el('span', { class: 'frist', style: 'position:static', text: 'F' }), 'Frist'), el('span', {}, el('i', { class: 'm-aus' }), 'kein Unterricht'),
        el('span', {}, el('i', { class: 'm-ohne' }), 'ohne Lehrkraft'), o.bearbeitbar ? el('span', { text: 'Tag antippen oder Balken ziehen = planen' }) : null),
      el('div', { class: 'r-scroll' }, tabelle));

    function zeile(r, g) {
      const planbar = o.bearbeitbar && r.gewaehlt;
      const knopf = o.bearbeitbar && r.art === 'wahl'
        ? el('button', { type: 'button', class: 'klein', onclick: () => o.waehlen(r, g) }, r.gewaehlt ? 'abwählen' : 'wählen') : null;
      return el('tr', { class: r.gewaehlt ? null : 'blass', 'data-aufgabe': r.id, 'data-planbar': planbar ? '1' : null },
        el('td', { class: 'auf', title: r.titel },
          el('span', { class: 'kz', text: r.kuerzel }),
          r.moodle_link ? el('a', { class: 'alink', href: r.moodle_link, target: '_blank', rel: 'noopener', text: r.titel }) : r.titel,
          r.art === 'pflicht' ? el('span', { class: 'art', text: 'Pflicht' }) : null),
        el('td', { class: 'st' }, r.gewaehlt ? statusChip(r) : null, r.ampel && r.gewaehlt ? el('span', { class: 'ampel a-' + r.ampel, title: 'letzte Ampel' }) : null,
          knopf ? ' ' : null, knopf, r.plant_nach_frist && r.gewaehlt ? el('span', { class: 'chip rot klein', text: 'nach der Frist' }) : null),
        tage.map((t, i) => {
          const geplant = r.plan.includes(t.datum), voriger = i > 0 && r.plan.includes(tage[i - 1].datum), naechster = i < tage.length - 1 && r.plan.includes(tage[i + 1].datum);
          const kann = planbar && plant(t) && t.datum >= z.heute;
          return el('td', { class: zellKlasse(t, z) + (kann ? ' kann' : ''), 'data-datum': kann ? t.datum : null, title: t.grund || null },
            geplant ? el('span', { class: 'bal' + (voriger ? '' : ' a') + (naechster ? '' : ' e') }) : null,
            r.ist[t.datum] ? el('span', { class: 'ist' }) : null,
            r.ist[t.datum] ? el('span', { class: 'ak a-' + r.ist[t.datum] }) : null,
            r.wirksam === t.datum && r.gewaehlt ? el('span', { class: 'frist', text: 'F' }) : null);
        }));
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
    };
    try { return (texte[e.art] || (() => e.art))(); } catch (f) { return e.art; }
  }

  return { zeichnen, ereignisText };
})();
