// Diktat im Rückmeldungsfenster (Stufe D, Konzept Abschnitt 10): „Diktat“ tippen, sprechen, „Stopp“. Die Aufnahme geht
// nur an den Container, Whisper erkennt den Text, die Aufnahme wird danach gelöscht. Der Text landet im Feld und
// lässt sich vor „Freigeben“ bearbeiten. Mikrofon nur über HTTPS (im Lehrerbereich gegeben).
'use strict';
const Diktat = (() => {
  const el = L.el;
  const MAX_S = 300;   // nach 5 Minuten stoppt die Aufnahme von selbst
  let stand = null;

  async function standHolen() {
    if (!stand) { try { stand = await L.api('GET', '/api/diktat'); } catch (e) { stand = { verfuegbar: false }; } }
    return stand;
  }

  function format() {
    if (!window.MediaRecorder) return '';
    return ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported(t)) || '';
  }

  function einfuegen(feld, text) {
    if (!text) return;
    const an = typeof feld.selectionStart === 'number' ? feld.selectionStart : feld.value.length;
    const bis = typeof feld.selectionEnd === 'number' ? feld.selectionEnd : an;
    const vorher = feld.value.slice(0, an);
    const nachher = feld.value.slice(bis);
    const trenner = vorher && !/\s$/.test(vorher) ? ' ' : '';
    feld.value = vorher + trenner + text + (nachher && !/^\s/.test(nachher) ? ' ' : '') + nachher;
    const pos = (vorher + trenner + text).length;
    feld.focus();
    feld.setSelectionRange(pos, pos);
    feld.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // feld: <textarea>, v: Vorlage der Rückmeldung (für die Fachwörter des Pakets)
  function knopf(feld, v) {
    const hinweis = el('span', { class: 'leise klein diktat-hinweis' });
    const b = el('button', { type: 'button', class: 'klein diktat' }, L.symbol('mikro'), el('span', { text: 'Diktat' }));
    const ort = el('span', { class: 'zeile', style: 'gap:6px' }, b, hinweis);
    let rec = null, uhr = null, start = 0, strom = null;
    const text = t => { b.lastChild.textContent = t; };

    const stoppen = () => { if (rec && rec.state !== 'inactive') rec.stop(); };

    async function senden(blob) {
      b.disabled = true;
      b.classList.remove('laeuft');
      text('Erkenne …');
      hinweis.textContent = 'Die Aufnahme ist im Container, gleich kommt der Text.';
      const t0 = Date.now();
      try {
        const antwort = await fetch('/api/diktat' + (v && v.paket_id ? '?paket=' + v.paket_id : ''), {
          method: 'POST', credentials: 'same-origin', body: blob,
          headers: { 'X-Lernbuero': '1', 'Content-Type': (blob.type || 'audio/webm').split(';')[0] } });
        let d = {};
        try { d = await antwort.json(); } catch (e) { /* leer */ }
        if (!antwort.ok) throw new Error(d.fehler || 'Fehler ' + antwort.status);
        einfuegen(feld, d.text);
        const s = Math.round((Date.now() - t0) / 1000);
        hinweis.textContent = (d.text ? 'Erkannt in ' + s + ' s' : 'Nichts verstanden') + ', die Aufnahme ist gelöscht.' +
          (d.unsicher && d.unsicher.length ? ' Bitte prüfen: ' + d.unsicher.join(', ') : '');
      } catch (e) {
        hinweis.textContent = '';
        L.meldung(e.message, true);
      } finally {
        b.disabled = false;
        text('Diktat');
      }
    }

    b.addEventListener('click', async () => {
      if (rec && rec.state === 'recording') { stoppen(); return; }
      if (!navigator.mediaDevices || !window.MediaRecorder) {
        L.meldung('Dieser Browser kann hier nicht aufnehmen (Mikrofon nur über https://).', true);
        return;
      }
      const st = await standHolen();
      if (!st.verfuegbar) { L.meldung('Das Diktat ist im Container noch nicht eingerichtet.', true); return; }
      try { strom = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, noiseSuppression: true, echoCancellation: true } }); }
      catch (e) { L.meldung('Kein Zugriff auf das Mikrofon. Bitte im Browser erlauben.', true); return; }
      const typ = format();
      const teile = [];
      rec = new MediaRecorder(strom, typ ? { mimeType: typ, audioBitsPerSecond: 32000 } : undefined);
      rec.ondataavailable = ev => { if (ev.data && ev.data.size) teile.push(ev.data); };
      rec.onstop = () => {
        clearInterval(uhr);
        strom.getTracks().forEach(t => t.stop());
        const blob = new Blob(teile, { type: rec.mimeType || typ || 'audio/webm' });
        rec = null;
        if (blob.size) senden(blob); else { text('Diktat'); b.classList.remove('laeuft'); }
      };
      rec.start(1000);
      start = Date.now();
      b.classList.add('laeuft');
      hinweis.textContent = 'Aufnahme läuft, „Stopp“ zum Beenden.';
      const zeigen = () => {
        const s = Math.round((Date.now() - start) / 1000);
        text('Stopp · ' + Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'));
        if (s >= MAX_S) stoppen();
      };
      zeigen();
      uhr = setInterval(zeigen, 500);
    });
    // Fenster geschlossen, während die Aufnahme läuft: Mikrofon freigeben
    const beobachter = new MutationObserver(() => {
      if (!document.body.contains(ort)) { beobachter.disconnect(); if (rec && rec.state !== 'inactive') { rec.onstop = null; rec.stop(); } if (strom) strom.getTracks().forEach(t => t.stop()); clearInterval(uhr); }
    });
    setTimeout(() => beobachter.observe(document.body, { childList: true, subtree: true }), 0);
    return ort;
  }

  return { knopf, standHolen };
})();
