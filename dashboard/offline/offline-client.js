// Passive status only; no duplicate Settings controls and no API interception.
const current = new URL(import.meta.url);
const base = new URL('./', current);
const status = document.createElement('output');
status.id = 'federation-offline-status';
status.setAttribute('role', 'status');
status.setAttribute('aria-live', 'polite');
status.style.cssText = 'display:block;font:11px system-ui;overflow-wrap:anywhere;max-width:100%';
function mount() {
  const host = document.querySelector('[data-offline-status-host]');
  if (host) { if (status.parentElement !== host) host.append(status); return true; }
  return false;
}
mount();
// A route can destroy and recreate its layout. Keep the single output bound
// without adding duplicate controls or a second status surface.
const observer = new MutationObserver(mount);
observer.observe(document.body, { childList: true, subtree: true });
let registration;
let shellReady = false;
let failure = '';
function render() {
  status.textContent = `${navigator.onLine ? 'Network available' : 'Offline'} · ${shellReady ? 'Shell ready' : failure || 'Preparing shell…'}`;
  status.title = 'Local data availability is separate from the app shell. Live services require a connection.';
  status.dataset.ready = String(shellReady);
  document.documentElement.dataset.offlineShellReady = String(shellReady);
  document.documentElement.dataset.offlineShellError = failure;
  if (failure && !mount() && !status.isConnected) document.body.prepend(status);
}
function inspect() {
  const worker = navigator.serviceWorker.controller;
  if (!worker) return;
  const channel = new MessageChannel();
  const timeout = setTimeout(() => { failure = 'Offline readiness unverified'; shellReady = false; render(); }, 10000);
  channel.port1.onmessage = event => {
    clearTimeout(timeout);
    channel.port1.close();
    if (event.data.appId !== '__APP_ID__') return;
    shellReady = event.data.ready === true;
    failure = shellReady ? '' : 'Offline app shell incomplete';
    render();
    window.dispatchEvent(new CustomEvent('federation:offline-status', { detail: event.data }));
  };
  worker.postMessage({ type: 'OFFLINE_STATUS' }, [channel.port2]);
}
function watch(worker) {
  if (!worker) return;
  worker.addEventListener('statechange', () => {
    if (worker.state === 'redundant' && !shellReady) { failure = 'Offline preparation failed; reconnect and reopen to retry'; render(); }
    if (worker.state === 'activated') inspect();
  });
}
render();
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.addEventListener('controllerchange', inspect);
  navigator.serviceWorker.register(new URL('sw.js', base), { scope: base.pathname, updateViaCache: 'none' }).then(value => {
    registration = value;
    watch(value.installing);
    value.addEventListener('updatefound', () => watch(value.installing));
    inspect();
  }).catch(() => { failure = 'Offline app shell unavailable'; render(); });
} else { failure = 'Offline HTTP shell unsupported in this context'; render(); }
window.addEventListener('online', () => { render(); inspect(); registration?.update().catch(() => {}); });
window.addEventListener('offline', () => { render(); inspect(); });
window.addEventListener('pageshow', inspect);
