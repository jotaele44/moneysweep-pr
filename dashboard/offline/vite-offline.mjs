import { createHash } from 'node:crypto';
import { readdir, readFile, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

/** Build assets only. Never caches API responses or automatically queues writes. */
export function federationOffline({ appId }) {
  if (!/^[a-z][a-z0-9-]+$/.test(appId)) throw new Error('Invalid offline app identity');
  let config;
  return {
    name: 'federation-offline-shell-v1',
    apply: 'build',
    configResolved(value) {
      config = value;
      if (!value.base.startsWith('/') || value.base.startsWith('//')) {
        throw new Error('Offline HTTP shell requires an absolute same-origin base');
      }
    },
    transformIndexHtml() {
      return [{ tag: 'script', attrs: { type: 'module', src: `${config.base}offline-client.js` }, injectTo: 'body' }];
    },
    closeBundle: {
      order: 'post', sequential: true,
      async handler() {
        const out = path.resolve(config.root, config.build.outDir);
        const runtime = await readFile(path.join(here, 'offline-client.js'), 'utf8');
        await writeFile(path.join(out, 'offline-client.js'), runtime.replaceAll('__APP_ID__', appId));
        const entries = [];
        async function walk(dir) {
          for (const item of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
            // The workspace transfer layer can stage files beside the output
            // while a build completes. Those are not emitted app resources.
            if (item.name === '.rsync-tmp') continue;
            const filename = path.join(dir, item.name);
            if (item.isSymbolicLink()) throw new Error(`Symlink in offline assets: ${filename}`);
            if (item.isDirectory()) { await walk(filename); continue; }
            const relative = path.relative(out, filename).split(path.sep).join('/');
            if (['sw.js', 'offline-manifest.json', 'offline-receipts.json'].includes(relative) || relative.endsWith('.map')) continue;
            if (relative.split('/').some(p => p.startsWith('.'))) throw new Error(`Hidden asset excluded from offline build: ${relative}`);
            const bytes = await readFile(filename);
            entries.push({ url: config.base + relative.split('/').map(encodeURIComponent).join('/'), sha256: digest(bytes), size: (await stat(filename)).size });
          }
        }
        await walk(out);
        if (!entries.some(e => e.url === `${config.base}index.html`)) throw new Error('Offline index missing');
        const bytes = entries.reduce((n, e) => n + e.size, 0);
        if (bytes > 128 * 1024 * 1024) throw new Error(`Offline shell exceeds 128 MiB: ${bytes}`);
        const template = await readFile(path.join(here, 'worker-template.js'), 'utf8');
        const version = digest(JSON.stringify({ appId, base: config.base, entries, template }));
        const manifest = { schema: 'federation-offline-shell/v1', appId, base: config.base, version, bytes, entries, excludedPatterns: ['.rsync-tmp/**', '*.map', 'sw.js', 'offline-manifest.json', 'offline-receipts.json'] };
        await writeFile(path.join(out, 'offline-manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
        await writeFile(path.join(out, 'sw.js'), template.replace('/*__MANIFEST__*/ null', JSON.stringify(manifest)));
      },
    },
  };
}
