import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { resolve } from 'path';

// Use import.meta.dirname (ESM standard) — avoids the __dirname warning in Vite 8
const _dirname = import.meta.dirname ?? resolve(new URL(import.meta.url).pathname, '..');

export default defineConfig({
  root: _dirname,
  plugins: [react(), viteSingleFile()],
  build: {
    // Build entry is mcp-app.html — the production single-file bundle
    // served by registerAppResource.  ui/index.html + ui/src/main.tsx remain
    // for `npm run dev:ui` (Vite dev server uses the root index.html by default).
    rollupOptions: {
      input: resolve(_dirname, 'mcp-app.html'),
    },
    outDir: resolve(_dirname, '../dist-ui'),
    emptyOutDir: true,
    target: 'es2020',
    // Single-file: inline all assets
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
  },
});
