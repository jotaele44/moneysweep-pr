import path from 'node:path';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Modelled on aguayluz-pr/dashboard/vitest.config.js. Deliberately a local file
// rather than a rendered federation template: templating it would make every
// JSX frontend drifted until all five had the harness, which would block
// landing tests one repo at a time.
//
// Deliberately separate from vite.config.js rather than merging it: the build
// config carries offline-export plumbing (vite-plugin-singlefile) and a dev
// server port pinned to the backend's CORS allowlist, none of which a test run
// needs or should depend on.
//
// `include` is narrower than the default on purpose. dashboard/tests/ holds
// federation-pilot.test.mjs, a `node --test` suite with its own assertion
// library that `npm run verify:pilot` runs separately — vitest must not collect
// it. Tests here are co-located with the code they cover.
//
// `globals: true` is set for parity with the sibling frontends, but the tests
// still import describe/it/expect from 'vitest' explicitly. In centinelas that
// is load-bearing; here it is not, because this repo's eslint config supplies
// its own `rules` block which replaces the recommended set, so no-undef never
// runs. Kept explicit so the suites read the same across the federation, and so
// they stay valid if that config is ever tightened.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
    include: ['src/**/*.test.{js,jsx}'],
  },
});
