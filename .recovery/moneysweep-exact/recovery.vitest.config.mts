import { defineConfig } from "vitest/config";
export default defineConfig({
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./recovery.vitest.setup.mjs"],
    restoreMocks: false,
    clearMocks: true,
  },
});
