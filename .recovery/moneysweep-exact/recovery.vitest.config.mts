import { defineConfig } from "vitest/config";
export default defineConfig({
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  test: {
    globals: true,
    environment: "jsdom",
    environmentMatchGlobs: [["helpers/moneySweepResponsiveQa.spec.tsx", "node"]],
    setupFiles: ["./recovery.vitest.setup.mjs"],
    restoreMocks: false,
    clearMocks: true,
  },
});
