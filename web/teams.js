// Lernteams und Nachrichten im Lehrerbereich (Stufe G).
// Teamübersicht je Einheit (Paket, Wahlgruppe, Aufgabe oder Stammteams der Klasse): Teams mit Mitgliedern, offene Einladungen,
// Austrittswünsche, wartende Fertigmeldungen und „ohne Team“ mit Zuteilen. Nachrichten: Verläufe mit einem Team oder einem
// Schüler, mit Antworten der Schüler; aus einem Teamverlauf lässt sich ein Teamtermin eintragen.
'use strict';
const Lernteams = (() => {
  const el = L.el;
  const MODUS = { frei: 'Team frei', pflicht: 'Team Pflicht', vorgabe: 'vorgegebene Teams', stamm: 'Stammteams' };
  const inhalt = () => document.getElementById('inhalt');
  const titel = t => { document.getElementById('unter').textContent = t; L.titel(t); };

  function mitgliedChip(m, darf, t, neu) {
    return el('span', { class: 'mg' + (m.status === 'eingeladen' ? ' wartet' : ''), title: m.status === 'eingeladen' ? 'eingeladen, hat noch nicht angenommen' : null },
      el('i', { class: 'av', text: (m.name.split(' ')[0][0] || '') + (m.name.split(' ').slice(-1)[0][0] || '') }), m.name + (m.status === 'eingeladen' ? ' · eingeladen' : ''),
      darf && m.status === 'aktiv' ? el('button', { type: 'button', class: 'mg-weg', title: 'aus dem Team nehmen', onclick: () => entfernen(t, m, neu) }, '×') : null);
  }

  async function entfernen(t, m, neu) {
    const ok = await L.dialog({ titel: m.name + ' aus ' + t.name + ' nehmen?', knopf: 'Herausnehmen', gefaehrlich: true,
      inhalt: el('p', { text: m.name.split(' ')[0] + ' behält den bisherigen Plan und arbeitet danach allein oder in einem anderen Team.' }),
      speichern: () => L.api('POST', '/api/lernteams/' + t.id + '/mitglied', { schueler_id: m.id, aktion: 'entfernen' }) });
    if (ok) neu();
  }

  async function seite(kid, schluessel) {
    titel('Teams');
    const { klassen } = await L.api('GET', '/api/klassen');
    const meine = klassen.filter(k => k.rolle === 'team' || k.rolle === 'einsicht');
    if (!meine.length) { L.setzen(inhalt(), el('div', { class: 'leer', text: 'Noch keine Klasse.' })); return; }
    const k = meine.find(x => x.id === kid) || meine[0];
    const u = await L.api('GET', '/api/klassen/' + k.id + '/teams');
    const e = u.einheiten.find(x => x.schluessel === schluessel) || u.einheiten.find(x => x.teams.length || x.austritte) || u.einheiten[0];
    const neu = () => seite(k.id, e.schluessel);
    const kw = el('select', { onchange: ev => { location.hash = 'teams/' + ev.target.value; } }, meine.map(x => el('option', { value: x.id, text: x.name })));
    kw.value = k.id;
    const ew = el('select', { onchange: ev => { location.hash = 'teams/' + k.id + '/' + ev.target.value; } },
      u.einheiten.map(x => el('option', { value: x.schluessel, text: (x.bereich === 'stamm' ? '' : x.paket + ' · ') + x.titel + ' (' + MODUS[x.modus] + ')'
        + (x.austritte ? ' · ' + x.austritte + ' Austrittswunsch' : '') })));
    ew.value = e.schluessel;
    const darf = u.darf;
    const ohneTitel = e.modus === 'frei' ? 'Arbeiten allein (' + e.ohne_team.length + ')' : 'Ohne Team (' + e.ohne_team.length + ')';
    const zuteilen = s => darf && e.teams.length ? el('select', { class: 'klein', onchange: async ev => {
      if (!ev.target.value) return;
      try { await L.api('POST', '/api/lernteams/' + ev.target.value + '/mitglied', { schueler_id: s.id, aktion: 'hinzu' }); neu(); }
      catch (f) { L.meldung(f.message, true); ev.target.value = ''; }
    } }, el('option', { value: '', text: 'zuteilen …' }), e.teams.map(t => el('option', { value: t.id, text: t.name + ' (' + t.anzahl + ')' }))) : null;
    const austritte = [];
    e.teams.forEach(t => t.mitglieder.filter(m => m.austritt).forEach(m => austritte.push({ t, m })));
    L.setzen(inhalt(),
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Teams' }), kw, ew,
        darf ? el('button', { type: 'button', class: 'haupt', onclick: () => bilden(k, e, u, neu) }, L.symbol('plus'), 'Team bilden') : null),
      el('div', { class: 'zeile klein' }, el('span', { class: 'chip lila klein', text: MODUS[e.modus] }),
        e.min && e.max ? el('span', { text: 'Größe ' + (e.min === e.max ? e.min : e.min + ' bis ' + e.max) }) : null,
        e.stichtag ? el('span', { class: e.stichtag_vorbei ? 'rot-text' : null, text: 'Stichtag ' + L.tag(e.stichtag, true) + (e.stichtag_vorbei ? ' (vorbei)' : '') }) : null,
        e.kuerzel.length ? el('span', { class: 'leise', text: 'gilt für ' + e.kuerzel.join(', ') }) : el('span', { class: 'leise', text: e.bereich === 'stamm' ? 'noch keine Aufgabe mit Modus „Stammteams“' : '' })),
      austritte.length ? el('div', { class: 'karte stapel' }, el('h2', { text: 'Austrittswünsche' }), austritte.map(({ t, m }) => el('div', { class: 'anfrage' },
        el('div', {}, el('b', { text: m.name }), ' möchte ' + t.name + ' verlassen', el('div', { class: 'leise klein', text: '„' + m.austritt + '“' + (m.austritt_zeit ? ' · ' + L.wann(m.austritt_zeit) : '') })),
        darf ? el('div', { class: 'zeile' },
          el('button', { type: 'button', class: 'klein', onclick: () => austritt(t, m, false, neu) }, 'ablehnen'),
          el('button', { type: 'button', class: 'klein haupt', onclick: () => austritt(t, m, true, neu) }, 'zustimmen')) : null)),
        el('p', { class: 'leise klein', text: 'Bei Zustimmung behält der Schüler seinen bisherigen Plan und sucht ein neues Team oder wird zugeteilt.' })) : null,
      el('div', { class: 'teams-raster' },
        el('div', { class: 'stapel' }, e.teams.length ? el('div', { class: 'team-karten' }, e.teams.map(t => el('div', { class: 'karte stapel team-k' + (t.quelle === 'lehrkraft' ? ' lk' : '') },
          el('div', { class: 'zeile' }, el('b', { text: t.name }),
            el('span', { class: 'chip klein', text: t.quelle === 'lehrkraft' ? 'von Ihnen' : 'selbst gebildet' }),
            t.offen ? el('span', { class: 'chip blau klein', text: 'offen' }) : null,
            el('span', { class: 'rechts' },
              el('button', { type: 'button', class: 'klein', onclick: () => { location.hash = 'nachrichten/t' + t.id; } }, L.symbol('rueck'), 'schreiben'))),
          el('div', { class: 'mitglieder' }, t.mitglieder.map(m => mitgliedChip(m, darf, t, neu))),
          t.wartet.map(w => el('div', { class: 'chip gelb klein', text: w.kuerzel + ' fertig · wartet auf ' + w.wartet.join(', ') })),
          darf ? el('div', { class: 'zeile' },
            el('select', { class: 'klein', onchange: async ev => {
              if (!ev.target.value) return;
              try { await L.api('POST', '/api/lernteams/' + t.id + '/mitglied', { schueler_id: Number(ev.target.value), aktion: 'hinzu' }); neu(); }
              catch (f) { L.meldung(f.message, true); ev.target.value = ''; }
            } }, el('option', { value: '', text: '+ Mitglied …' }), u.schueler.filter(s => !t.mitglieder.some(m => m.id === s.id && m.status === 'aktiv'))
              .map(s => el('option', { value: s.id, text: s.name }))),
            el('button', { type: 'button', class: 'klein', onclick: () => teamtermin(t) }, L.symbol('uhr'), 'Teamtermin'),
            el('button', { type: 'button', class: 'klein warnen', onclick: () => aufloesen(t, neu) }, 'auflösen')) : null)))
          : el('div', { class: 'leer', text: e.modus === 'frei' || e.modus === 'pflicht' ? 'Noch kein Team. Die Schüler finden sich in ihrem Plan selbst; Sie können auch Teams bilden.'
            : 'Noch kein Team. Bilden Sie die Teams mit „Team bilden“.' })),
        el('div', { class: 'karte stapel ohne-team' + (e.modus === 'frei' ? ' frei' : '') }, el('h3', { text: ohneTitel }),
          e.ohne_team.length ? e.ohne_team.map(s => el('div', { class: 'zeile' }, el('span', { text: s.name }), el('span', { class: 'rechts' }, zuteilen(s))))
            : el('p', { class: 'leise klein', text: 'Alle sind in einem Team.' }),
          e.modus === 'pflicht' ? el('p', { class: 'leise klein', text: e.stichtag_vorbei ? 'Der Stichtag ist vorbei: bitte zuteilen. Sie dürfen dabei die Teamgröße überschreiten.'
            : 'Bis zum Stichtag finden sich die Schüler selbst. Danach teilen Sie die übrigen zu.' }) : null)),
      el('p', { class: 'leise klein', text: 'Gemeinsam im Team: Plan, Wahl, Fertigmeldung (alle bestätigen), der Teil „An das ganze Team“ der Rückmeldung, Nachrichten und Teamtermin. Je Person: Kann-Liste, Farben, eigener Teil der Rückmeldung, Empfehlungen, Gelingensnachweis.' }));
  }

  async function bilden(k, e, u, neu) {
    const name = el('input', { maxlength: 40, placeholder: e.bereich === 'stamm' ? 'z. B. Werkbank 1' : 'leer = Team + erster Vorname' });
    const imTeam = {};
    e.teams.forEach(t => t.mitglieder.filter(m => m.status === 'aktiv').forEach(m => { imTeam[m.id] = t.name; }));
    const liste = el('div', { class: 'stapel', style: 'gap:4px;max-height:45vh;overflow:auto' }, u.schueler.map(s => el('label', { class: 'haken klein' },
      el('input', { type: 'checkbox', value: s.id }), s.name, imTeam[s.id] ? el('span', { class: 'leise', text: ' · jetzt in ' + imTeam[s.id] }) : null)));
    const ok = await L.dialog({
      titel: 'Team bilden · ' + e.titel, knopf: 'Team bilden',
      inhalt: el('div', { class: 'felder' }, L.feld('Name (wahlweise)', name), el('div', { class: 'etikett', text: 'Mitglieder' }), liste,
        el('p', { class: 'leise klein', text: 'Das Team gilt sofort. Wer schon in einem Team dieser Einheit ist, wechselt. Die Pläne der Mitglieder werden zusammengelegt.' })),
      speichern: form => L.api('POST', '/api/klassen/' + k.id + '/teams', { bereich: e.bereich, bezug_id: e.bezug_id, name: name.value,
        schueler_ids: Array.from(form.querySelectorAll('input[type=checkbox]:checked'), c => Number(c.value)) }),
    });
    if (ok) neu();
  }

  async function austritt(t, m, zustimmen, neu) {
    try { await L.api('POST', '/api/lernteams/' + t.id + '/austritt', { schueler_id: m.id, zustimmen }); L.meldung(zustimmen ? m.name + ' ist ausgetreten.' : 'Abgelehnt.'); neu(); }
    catch (f) { L.meldung(f.message, true); }
  }

  async function aufloesen(t, neu) {
    const ok = await L.dialog({ titel: t.name + ' auflösen?', knopf: 'Auflösen', gefaehrlich: true,
      inhalt: el('p', { text: 'Alle behalten ihren bisherigen Plan und arbeiten danach allein oder in einem neuen Team. Der Nachrichtenverlauf bleibt lesbar.' }),
      speichern: () => L.api('POST', '/api/lernteams/' + t.id + '/aufloesen', {}) });
    if (ok) neu();
  }

  async function teamtermin(t, danach) {
    let plaetze;
    try { plaetze = (await L.api('GET', '/api/lernteams/' + t.id + '/plaetze')).plaetze; } catch (f) { L.meldung(f.message, true); return; }
    let wahl = null;
    const hinweis = el('input', { maxlength: 200, placeholder: 'z. B. Bringt eure Stückliste mit' });
    const ok = await L.dialog({
      titel: 'Teamtermin · ' + t.name, knopf: 'Termin eintragen',
      inhalt: plaetze.length ? el('div', { class: 'stapel', style: 'gap:10px' },
        el('div', { class: 'stapel', style: 'gap:8px' }, plaetze.map(p => el('div', { class: 'stapel', style: 'gap:4px' },
          el('div', { class: 'etikett', text: L.tag(p.datum) + ' · ' + p.dauer + ' min' }),
          el('div', { class: 'slots' }, p.plaetze.map(b => el('button', { type: 'button', text: b, onclick: ev => {
            wahl = { zeitfenster_id: p.zeitfenster_id, datum: p.datum, beginn: b };
            ev.currentTarget.closest('form').querySelectorAll('.slots button').forEach(x => x.classList.toggle('an', x === ev.currentTarget));
          } })))))),
        L.feld('Hinweis an das Team (wahlweise)', hinweis),
        el('p', { class: 'leise klein', text: 'Ein Pflichttermin aus Ihrer Sprechzeit für alle Mitglieder. Absagen können nur Lehrkräfte.' }))
        : el('div', { class: 'banner warnung', text: 'In Ihren Sprechzeiten dieser Klasse ist nichts frei. Legen Sie unter „Zeitfenster“ eine Sprechzeit an.' }),
      speichern: () => {
        if (!wahl) throw new Error('Bitte einen Platz wählen.');
        return L.api('POST', '/api/lernteams/' + t.id + '/termin', Object.assign({ hinweis: hinweis.value }, wahl));
      },
    });
    if (ok) { L.meldung('Teamtermin eingetragen: ' + L.tag(wahl.datum) + ' · ' + wahl.beginn); if (danach) danach(); }
  }

  // --- Nachrichten ---

  async function nachrichten(ziel) {
    titel('Nachrichten');
    const { verlaeufe } = await L.api('GET', '/api/nachrichten');
    const team = ziel && ziel[0] === 't' ? Number(ziel.slice(1)) : null;
    const schueler = ziel && ziel[0] === 's' ? Number(ziel.slice(1)) : null;
    let v = null;
    if (team || schueler) {
      try { v = await L.api('GET', '/api/nachrichten/verlauf?' + (team ? 'team=' + team : 'schueler=' + schueler)); }
      catch (f) { L.meldung(f.message, true); }
    }
    if (typeof navNachrichten === 'function') navNachrichten();
    const liste = el('div', { class: 'karte stapel verlaeufe' },
      el('div', { class: 'zeile' }, el('h3', { text: 'Verläufe' }), el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein haupt', onclick: neueNachricht }, L.symbol('plus'), 'neu'))),
      verlaeufe.length ? verlaeufe.map(x => el('a', { class: 'vl' + ((x.team_id && x.team_id === team) || (x.schueler_id && x.schueler_id === schueler) ? ' an' : ''),
        href: '#nachrichten/' + (x.team_id ? 't' + x.team_id : 's' + x.schueler_id) },
        el('div', { class: 'zeile' }, x.team_id ? L.symbol('klassen') : null, el('b', { text: x.titel }), x.ungelesen ? el('span', { class: 'chip rot klein rechts', text: String(x.ungelesen) }) : null),
        el('div', { class: 'leise klein', text: x.klasse + ' · ' + x.unter }),
        el('div', { class: 'klein vl-letzte', text: x.letzte.von + ': ' + x.letzte.text })))
        : el('p', { class: 'leise klein', text: 'Noch keine Nachrichten. Schreiben Sie einem Team aus der Teamübersicht oder einem Schüler von seiner Seite aus.' }));
    let rechts;
    if (v) {
      const text = el('textarea', { rows: 3, maxlength: 2000, placeholder: v.art === 'team' ? 'Nachricht an das ganze Team …' : 'Nachricht an ' + v.titel.split(' ')[0] + ' …' });
      const fluss = el('div', { class: 'nachrichten' }, v.nachrichten.length ? v.nachrichten.map(n => el('div', { class: 'nachricht' + (n.von_art === 'lehrkraft' ? ' ich' : '') },
        el('small', { text: n.von + ' · ' + L.wann(n.zeit) }), el('span', { class: 'nl', text: n.text })))
        : el('p', { class: 'leise klein', text: 'Noch keine Nachricht in diesem Verlauf.' }));
      rechts = el('div', { class: 'karte stapel' },
        el('div', { class: 'zeile' }, v.art === 'team' ? L.symbol('klassen') : null, el('h2', { text: v.titel }), el('span', { class: 'leise klein', text: v.unter }),
          v.art === 'team' && v.team ? el('span', { class: 'rechts leise klein', text: v.team.mitglieder.filter(m => m.status === 'aktiv').map(m => m.name).join(', ') + ' lesen mit' }) : null),
        fluss,
        v.darf && v.aktiv ? el('form', { class: 'stapel', style: 'gap:6px', onsubmit: async ev => {
          ev.preventDefault();
          if (!text.value.trim()) return;
          try { await L.api('POST', '/api/nachrichten', { text: text.value, team_id: v.team_id || undefined, schueler_id: v.schueler_id || undefined }); nachrichten(ziel); }
          catch (f) { L.meldung(f.message, true); }
        } }, text, el('div', { class: 'zeile' }, el('button', { type: 'submit', class: 'haupt' }, 'Senden'),
          v.art === 'team' ? el('button', { type: 'button', onclick: () => teamtermin({ id: v.team_id, name: v.titel }) }, L.symbol('uhr'), 'Teamtermin eintragen') : null,
          v.art === 'team' ? el('a', { class: 'knopf', href: '#teams/' + v.klasse_id + '/' + v.team.schluessel }, 'zum Team')
            : el('a', { class: 'knopf', href: '#schueler/' + v.klasse_id + '/' + v.schueler_id }, 'zur Schülerseite')))
          : el('p', { class: 'leise klein', text: v.aktiv ? 'Mit Einsicht lesen Sie mit, schreiben aber nicht.' : 'Dieser Verlauf ist abgeschlossen.' }));
      setTimeout(() => { fluss.scrollTop = fluss.scrollHeight; }, 0);
    } else {
      rechts = el('div', { class: 'leer', text: 'Links einen Verlauf wählen oder eine neue Nachricht beginnen.' });
    }
    L.setzen(inhalt(), el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Nachrichten' })),
      el('div', { class: 'nachrichten-raster' }, liste, rechts));
  }

  async function neueNachricht() {
    const { klassen } = await L.api('GET', '/api/klassen');
    const meine = klassen.filter(k => k.rolle === 'team');
    if (!meine.length) { L.meldung('Sie sind in keiner Klasse im Team.', true); return; }
    const kw = el('select', {}, meine.map(k => el('option', { value: k.id, text: k.name })));
    const zw = el('select', { required: true });
    const laden = async () => {
      const [u, k] = await Promise.all([L.api('GET', '/api/klassen/' + kw.value + '/teams'), L.api('GET', '/api/klassen/' + kw.value)]);
      const teams = [];
      u.einheiten.forEach(e => e.teams.forEach(t => teams.push({ t, e })));
      L.setzen(zw, el('option', { value: '', text: 'Team oder Schüler wählen …' }),
        teams.length ? el('optgroup', { label: 'Teams' }, teams.map(({ t, e }) => el('option', { value: 't' + t.id, text: t.name + ' · ' + e.titel }))) : null,
        el('optgroup', { label: 'Einzeln' }, (k.klasse.schueler || []).filter(s => s.aktiv).map(s => el('option', { value: 's' + s.id, text: s.vorname + ' ' + s.nachname }))));
    };
    kw.addEventListener('change', laden);
    await laden();
    const ok = await L.dialog({ titel: 'Neue Nachricht', knopf: 'Weiter',
      inhalt: el('div', { class: 'felder' }, L.feld('Klasse', kw), L.feld('An', zw, 'Im Team lesen alle Mitglieder mit; einzeln nur der Schüler.')),
      speichern: () => { if (!zw.value) throw new Error('Bitte wählen, an wen.'); return zw.value; } });
    if (ok) location.hash = 'nachrichten/' + ok;
  }

  return { seite, nachrichten, teamtermin };
})();
