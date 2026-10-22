'use strict';
const button = document.querySelector('#install-update');
const message = document.querySelector('#update-status');
const error = document.querySelector('#update-error');
const busy = ['preparing', 'dependencies', 'validating', 'backup', 'restarting'];
let csrf = '';
let sending = false;
let running = false;
let misses = 0;
try {
  const theme = localStorage.getItem('socketstat-theme');
  if (['light', 'dark', 'classic'].includes(theme)) document.documentElement.dataset.theme = theme;
} catch (_) {}
async function poll() {
  try {
    const response = await fetch('/api/updates', {cache: 'no-store', signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('status');
    const state = await response.json();
    csrf = state.csrf;
    misses = 0;
    running = busy.includes(state.phase);
    document.querySelector('#version').textContent = state.revision || 'Початкове встановлення';
    message.textContent = state.enabled ? state.message : 'Оновлення ще не налаштовано. Потрібне одноразове встановлення через консоль PythonAnywhere.';
    const backup = document.querySelector('#backup');
    backup.hidden = !state.backup;
    backup.textContent = state.backup ? `Резервна копія: ${state.backup}` : '';
    button.disabled = sending || running || !state.enabled;
    error.hidden = state.phase !== 'error';
    if (state.phase === 'error') error.textContent = state.message;
  } catch (_) {
    misses++;
    message.textContent = running && misses < 20 ? 'Сайт перезапускається. Очікуємо відновлення зв’язку…' : 'Немає зв’язку із сервером. Перевіряємо повторно…';
    button.disabled = true;
    if (misses >= 20) {
      error.textContent = 'Сайт довго не відповідає. Перевірте журнали PythonAnywhere; за потреби відновіть попередню версію командою з інструкції.';
      error.hidden = false;
    }
  }
}
button.addEventListener('click', async () => {
  if (sending || running) return;
  sending = true;
  button.disabled = true;
  error.hidden = true;
  try {
    const response = await fetch('/api/updates', {method: 'POST', headers: {'X-SocketStat-Token': csrf}, signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('Оновлення не запущено. Перевірте стан і повторіть спробу.');
    running = true;
    message.textContent = 'Запускаємо оновлення…';
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
  } finally {
    sending = false;
    await poll();
  }
});
poll();
setInterval(poll, 3000);
