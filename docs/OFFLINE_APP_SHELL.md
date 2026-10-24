# Offline HTTP app shell — candidate v1

The production frontend at `dashboard` registers a scoped service worker. Prepare it online first and wait for **Shell ready**. The offline label describes build assets, not data completeness or server availability. Development Vite servers do not register this worker. Use HTTPS or localhost. An untouched browser cannot perform its first visit offline.

The build enumerates emitted assets, including lazy chunks, fonts and public runtime resources; each has size and SHA-256. Installation verifies every byte and fails as a unit. Maximum shell size is 128 MiB. API responses, credentials, cross-origin maps, POST/DELETE requests and source maps are not precached. Transient `.rsync-tmp` writer staging is excluded from the emitted-asset universe; other hidden artifacts fail the build. `offline-receipts.json` is a separately versioned governance snapshot, loaded by TheHub's own consumer and intentionally excluded to avoid self-referential release hashes.

Updates wait for existing controlled windows to close; they never invoke skipWaiting or force a reload. Cache cleanup owns only this app's identity and base path. An evicted entry makes readiness incomplete; recovery admits only bytes matching the frozen manifest. Browser storage can be evicted and is not a backup.

Existing local backends, desktop launchers and standalone exports retain their own contracts. A browser shell cannot execute the Python backend. Live feeds, remote GIS tiles, credentials and server mutation authority require their applicable service. No automatic mutation replay was added.

## Verification

Run `npm run build` and `node offline/test-offline.mjs` inside `dashboard`. Browser qualification covers desktop/393/430, offline cold-window reopen, every manifest asset, navigation URL preservation, local-storage survival, API exclusion, failed/corrupt installation, eviction recovery, waiting updates and cache ownership. These are desktop Chromium emulations, not physical iPhone or native-device proof. The browser executable must match the selected Playwright toolchain.

The seven-app registry is `.federation/offline-shell.json`; per-app source and evidence hashes are stored separately from the receipts themselves. Do not infer full application, deployment, or federation certification from a shell PASS. Domain working sets, offline edits, conflict resolution, authoritative synchronization, current deployment binding and device evidence remain independent acceptance leaves.
