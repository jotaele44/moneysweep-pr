/* All shell entries are content-verified before installation can succeed. */
const manifest = /*__MANIFEST__*/ null;
const prefix = `fed-shell:${manifest.appId}:${manifest.base}:`;
const cacheName = prefix + manifest.version;
const absolute = entry => new URL(entry.url, self.location.origin).href;
const assets = new Set(manifest.entries.map(absolute));
const hex = bytes => Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, '0')).join('');
async function verifiedAsset(entry) {
  const response = await fetch(absolute(entry), { cache: 'reload', credentials: 'omit', redirect: 'error' });
  if (!response.ok || response.type === 'opaque') throw new Error(`Offline asset unavailable: ${entry.url}`);
  const body = await response.clone().arrayBuffer();
  if (body.byteLength !== entry.size || hex(await crypto.subtle.digest('SHA-256', body)) !== entry.sha256) {
    throw new Error(`Offline asset changed during preparation: ${entry.url}`);
  }
  return response;
}

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(cacheName);
    try {
      // Bounded concurrency avoids unbounded memory on mobile devices.
      let next = 0;
      const results = await Promise.allSettled(Array.from({ length: 6 }, async () => {
        while (next < manifest.entries.length) {
          const entry = manifest.entries[next++];
          const response = await verifiedAsset(entry);
          await cache.put(absolute(entry), response);
        }
      }));
      const failed = results.find(result => result.status === 'rejected');
      if (failed) throw failed.reason;
      // No skipWaiting: old documents keep their compatible worker and assets.
    } catch (error) {
      await caches.delete(cacheName);
      throw error;
    }
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    // Activation normally waits for old controlled windows to close.
    for (const name of await caches.keys()) if (name.startsWith(prefix) && name !== cacheName) await caches.delete(name);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (assets.has(url.href)) {
    event.respondWith((async () => (await (await caches.open(cacheName)).match(url.href)) || fetch(request))());
    return;
  }
  const relative = url.pathname.slice(manifest.base.length);
  const serverRoute = /^(?:api|_api|auth|oauth|tiles|agencies|vendors|sites|contracts|events|anomalies|sources|investigations|alerts|pipeline|rag)(?:\/|$)/.test(relative);
  if (request.mode === 'navigate' && url.pathname.startsWith(manifest.base) && !serverRoute && !relative.split('/').pop().includes('.')) {
    // Preserve the URL. The application's own router and authorization still decide the view.
    event.respondWith((async () => (await (await caches.open(cacheName)).match(manifest.base + 'index.html')) || fetch(request))());
  }
});

self.addEventListener('message', event => {
  if (event.data?.type !== 'OFFLINE_STATUS' || !event.ports[0]) return;
  event.waitUntil((async () => {
    const cache = await caches.open(cacheName);
    const present = [];
    for (const entry of manifest.entries) {
      let response = await cache.match(absolute(entry));
      if (!response) {
        // Recover evicted entries only from content-verified bytes. A failed
        // repair stays visibly incomplete and never admits a server fallback.
        try { response = await verifiedAsset(entry); await cache.put(absolute(entry), response.clone()); } catch { response = undefined; }
      }
      present.push(Boolean(response));
    }
    event.ports[0].postMessage({ appId: manifest.appId, version: manifest.version, ready: present.every(Boolean), assets: manifest.entries.length, bytes: manifest.bytes });
  })());
});
