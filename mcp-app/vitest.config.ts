import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    // UI component tests (*.test.tsx under ui/) use jsdom via the
    // @vitest-environment docblock in each file.
    environmentMatchGlobs: [
      ["ui/src/**/*.test.tsx", "jsdom"],
    ],
  },
  resolve: {
    // Allow .js extensions to resolve .ts files (needed for ESM imports in tests)
    extensions: [".ts", ".tsx", ".js", ".jsx"],
  },
});
