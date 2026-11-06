// Startseite fuer Schueler (Port 80, "/"): Code eintippen. Ein gemerkter Code oeffnet den Plan sofort, bis ein anderer
// Code gescannt oder eingetippt wird (keine Abmeldung auf geteilten Geraeten, so entschieden).
'use strict';
const SPEICHER = 'lernbuero-code';

function gemerkt() {
  try { return localStorage.getItem(SPEICHER); } catch (e) { return null; }
}

// Lehrerbereich laeuft ueber HTTPS auf demselben Rechner
if (location.protocol === 'http:' && !location.port) document.getElementById('lehrer-link').href = 'https://' + location.hostname + '/anmelden';

if (gemerkt() && !new URLSearchParams(location.search).has('neu')) location.replace('/s/' + gemerkt());

document.getElementById('code').addEventListener('input', ev => {
  const roh = ev.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
  ev.target.value = roh.length > 4 ? roh.slice(0, 4) + '-' + roh.slice(4) : roh;
});

document.getElementById('code-form').addEventListener('submit', async ev => {
  ev.preventDefault();
  const fehler = document.getElementById('fehler');
  const code = document.getElementById('code').value.toUpperCase().replace(/[^A-Z0-9]/g, '');
  fehler.textContent = '';
  try {
    await L.api('GET', '/api/s/' + code);
    location.href = '/s/' + code;
  } catch (e) {
    fehler.textContent = e.message;
  }
});
