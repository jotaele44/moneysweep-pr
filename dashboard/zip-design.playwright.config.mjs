import { defineConfig } from 'playwright/test';
export default defineConfig({
 testDir: './tests', testMatch: 'zip-design.spec.mjs', workers: 1,
 timeout: 45000, reporter: 'line',
 use: { baseURL: 'http://127.0.0.1:5419', screenshot: 'only-on-failure' },
 webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 5419 --strictPort', url: 'http://127.0.0.1:5419', reuseExistingServer: false, timeout: 60000 },
});
