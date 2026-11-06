'use strict';
(async () => {
  try {
    const status = await L.api('GET', '/api/status');
    if (status.eingerichtet) location.replace('/anmelden');
  } catch (e) { /* Seite trotzdem zeigen */ }
})();

document.getElementById('einrichtung').addEventListener('submit', async ev => {
  ev.preventDefault();
  const fehler = document.getElementById('fehler');
  const knopf = ev.target.querySelector('button');
  fehler.textContent = '';
  knopf.disabled = true;
  try {
    await L.api('POST', '/api/einrichtung', {
      code: document.getElementById('code').value,
      kuerzel: document.getElementById('kuerzel').value,
      name: document.getElementById('name').value,
      passwort: document.getElementById('passwort').value,
    });
    location.href = '/lehrer';
  } catch (e) {
    fehler.textContent = e.message;
    knopf.disabled = false;
  }
});
