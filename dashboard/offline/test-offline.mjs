import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve(process.env.OFFLINE_DIST || 'dist');
const out = path.resolve(process.env.OFFLINE_EVIDENCE || 'offline-evidence');
await mkdir(out, { recursive: true });
const manifest = JSON.parse(await readFile(path.join(root, 'offline-manifest.json'), 'utf8'));
const sha = b => createHash('sha256').update(b).digest('hex');
async function poll(predicate, timeout = 120000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await predicate() === true) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Bounded lifecycle observation timed out');
}
for (const entry of manifest.entries) {
  const bytes = await readFile(path.join(root, decodeURIComponent(entry.url.slice(manifest.base.length))));
  assert.equal(bytes.length, entry.size);
  assert.equal(sha(bytes), entry.sha256);
}
assert.equal(new Set(manifest.entries.map(e => e.url)).size, manifest.entries.length);
assert.equal(manifest.bytes, manifest.entries.reduce((n, e) => n + e.size, 0));
let corrupt = false;
let unavailable = false;
let successor = false;
const successorVersion = 'b'.repeat(64) === manifest.version ? 'c'.repeat(64) : 'b'.repeat(64);
const target = manifest.entries.find(e => e.url.endsWith('.js') && !e.url.endsWith('offline-client.js')).url;
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.wasm': 'application/wasm', '.svg': 'image/svg+xml', '.png': 'image/png' };
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (unavailable && url.pathname === target) { res.writeHead(503); res.end(); return; }
  if (url.pathname === '/api/private') { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"private":true}'); return; }
  if (corrupt && url.pathname === target) { res.writeHead(200, { 'Content-Type': 'text/javascript' }); res.end('corrupt'); return; }
  const relative = decodeURIComponent(url.pathname.slice(manifest.base.length));
  let filename = path.resolve(root, relative || 'index.html');
  if (!filename.startsWith(root + path.sep)) { res.writeHead(403); res.end(); return; }
  try {
    let body;
    try { body = await readFile(filename); } catch {
      if (path.extname(filename)) { res.writeHead(404); res.end(); return; }
      filename = path.join(root, 'index.html'); body = await readFile(filename);
    }
    if (successor && url.pathname === manifest.base + 'sw.js') body = Buffer.from(body.toString().replace(manifest.version, successorVersion));
    res.writeHead(200, { 'Content-Type': mime[path.extname(filename)] || 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(body);
  } catch { res.writeHead(500); res.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const results = [];
try {
  for (const width of process.env.NEGATIVE_ONLY ? [] : [1440, 393, 430]) {
    console.log('viewport', width);
    const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 1000 : 932 } });
    let page = await context.newPage();
    await page.goto(origin + manifest.base);
    await page.waitForFunction(() => document.documentElement.dataset.offlineShellReady === 'true', undefined, { timeout: 30000 }).catch(async error => { console.log(await page.evaluate(() => ({state: document.documentElement.dataset.offlineShellError, html:document.body.innerHTML.slice(0,1500)}))); throw error; });
    console.log('shell ready', width);
    assert.equal(await page.evaluate(async () => (await fetch('/api/private')).ok), true);
    assert.equal(await page.evaluate(async () => Boolean(await caches.match('/api/private'))), false);
    if (manifest.appId === 'spiderweb-pr') {
      await page.getByRole('button', { name: 'SAVE LOCAL COPY', exact: true }).click();
      await page.getByText(/Local demo copy ·/).waitFor();
    }
    await page.evaluate(() => localStorage.setItem('offline-regression-sentinel', 'saved'));
    await page.close();
    await context.setOffline(true);
    page = await context.newPage();
    await page.goto(origin + manifest.base);
    await page.waitForFunction(() => document.documentElement.dataset.offlineShellReady === 'true');
    assert.equal(await page.evaluate(() => localStorage.getItem('offline-regression-sentinel')), 'saved');
    assert.equal(await page.evaluate(async () => {
      try { await fetch('/api/private'); return true; } catch { return false; }
    }), false);
    if (manifest.appId === 'spiderweb-pr') await page.getByText(/Local demo copy ·/).waitFor();
    if (manifest.appId === 'thehub-pr') {
      await context.setOffline(false);
      await page.goto(origin + manifest.base + 'operator-settings');
      await page.getByRole('heading', { name: 'Federation offline readiness' }).waitFor();
      await page.getByText('jotaele44/spiderweb-pr', { exact: true }).waitFor();
      await context.setOffline(true);
      await page.reload();
      await page.getByText(/current remote heads have not been revalidated/).waitFor();
    }
    // Fetch every manifest entry while disconnected: covers all unvisited lazy chunks.
    const available = await page.evaluate(async entries => {
      for (const entry of entries) { try { if (!(await fetch(entry.url)).ok) return entry.url; } catch { return entry.url; } }
      return true;
    }, manifest.entries);
    assert.equal(available, true);
    assert.equal(await page.evaluate(async () => {
      try { await fetch('/api/private', { method: 'POST', body: '{}' }); return true; } catch { return false; }
    }), false);
    if (manifest.appId === 'spiderweb-pr') {
      await page.getByRole('tab', { name: 'Finance', exact: true }).click();
      await page.getByRole('tab', { name: 'Graph', exact: true }).click();
      await page.getByText('Loading module…', { exact: true }).waitFor({ state: 'hidden' });
    }
    await page.screenshot({ path: path.join(out, `offline-${width}.png`), fullPage: true });
    await page.goto(origin + manifest.base + 'offline-route-regression');
    await page.waitForFunction(() => document.documentElement.dataset.offlineShellReady === 'true');
    const inspect = async () => page.evaluate(() => new Promise(resolve => {
      const channel = new MessageChannel(); channel.port1.onmessage = event => resolve(event.data);
      navigator.serviceWorker.controller.postMessage({ type: 'OFFLINE_STATUS' }, [channel.port2]);
    }));
    await page.evaluate(async target => {
      const names = await caches.keys();
      const cache = await caches.open(names.find(name => name.startsWith('fed-shell:')));
      await cache.delete(target);
    }, target);
    await context.setOffline(true);
    unavailable = true;
    assert.equal((await inspect()).ready, false);
    await context.setOffline(false);
    unavailable = false;
    assert.equal((await inspect()).ready, true);
    results.push({ status: 'PASS', checks: ['evicted-asset-detected', 'verified-online-repair'] });
    assert.ok(page.url().endsWith('/offline-route-regression'));
    await context.setOffline(false);
    assert.equal(await page.evaluate(async () => (await fetch('/api/private')).ok), true);
    results.push({ width, status: 'PASS', checks: ['cold-reopen', 'all-shell-assets', 'local-storage-survival', 'api-not-cached', 'offline-api-fails', 'deep-link-preserved', 'reconnect'] });
    await context.close();
  }
  if (!process.env.NEGATIVE_ONLY) {
    const context = await browser.newContext();
    let page = await context.newPage();
    await page.goto(origin + manifest.base);
    await page.waitForFunction(() => document.documentElement.dataset.offlineShellReady === 'true');
    await page.evaluate(async () => { await caches.open('unrelated-app-sentinel'); localStorage.setItem('update-work-sentinel', 'unsaved-work'); });
    successor = true;
    await page.evaluate(async () => { const registration = await navigator.serviceWorker.getRegistration(); await registration.update(); });
    await poll(() => page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return registration?.waiting?.state === 'installed' && !registration.installing;
    }));
    let successorWorker;
    for (const worker of context.serviceWorkers()) {
      if (await worker.evaluate(() => manifest.version).catch(() => null) === successorVersion) successorWorker = worker;
    }
    assert.ok(successorWorker, 'successor worker must be independently identified');
    assert.equal(await page.evaluate(async () => (await caches.keys()).some(key => key.endsWith('b'.repeat(64)))), true);
    // A waiting update must not reload a document or erase its in-progress state.
    assert.equal(await page.evaluate(() => localStorage.getItem('update-work-sentinel')), 'unsaved-work');
    await page.close();
    // Observe activation rather than assuming a delay is evidence of completion.
    const deadline = Date.now() + 30000;
    let activated = false;
    while (Date.now() < deadline) {
      activated = await successorWorker.evaluate(() => !self.registration.waiting && !self.registration.installing && self.registration.active?.state === 'activated').catch(() => false);
      if (activated) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.equal(activated, true, 'successor activation must complete before cold reopen');
    await context.setOffline(true);
    page = await context.newPage();
    await page.goto(origin + manifest.base);
    await page.waitForFunction(() => document.documentElement.dataset.offlineShellReady === 'true');
    assert.equal(await page.evaluate(async () => (await caches.keys()).includes('unrelated-app-sentinel')), true);
    assert.equal(await page.evaluate(async version => (await caches.keys()).some(key => key.endsWith(version)), manifest.version), false);
    results.push({ status: 'PASS', checks: ['waiting-update-preserves-open-document', 'successor-cold-offline-launch', 'old-cache-cleanup', 'other-app-cache-preserved'] });
    await context.close();
    successor = false;
  }
  corrupt = true;
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(origin + manifest.base);
  await page.waitForFunction(() => document.documentElement.dataset.offlineShellError?.includes('failed'), undefined, { timeout: 120000 });
  assert.equal(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length), 0);
  assert.equal(await page.evaluate(async () => (await caches.keys()).some(key => key.startsWith('fed-shell:'))), false);
  results.push({ status: 'PASS', checks: ['corrupt-asset-rejects-install', 'partial-cache-removed'] });
  await context.close();
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
await writeFile(path.join(out, 'browser-receipt.json'), JSON.stringify({ scope: 'offline-shell-only', appId: manifest.appId, version: manifest.version, assets: manifest.entries.length, bytes: manifest.bytes, results }, null, 2));
console.log(JSON.stringify({ appId: manifest.appId, assets: manifest.entries.length, results }));
