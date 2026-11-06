'use strict';
document.getElementById('anmelden').addEventListener('submit', async ev => {
  ev.preventDefault();
  const fehler = document.getElementById('fehler');
  const knopf = ev.target.querySelector('button');
  fehler.textContent = '';
  knopf.disabled = true;
  try {
    await L.api('POST', '/api/anmelden', {
      kuerzel: document.getElementById('kuerzel').value,
      passwort: document.getElementById('passwort').value,
    });
    location.href = '/lehrer';
  } catch (e) {
    fehler.textContent = e.message;
    knopf.disabled = false;
  }
});
