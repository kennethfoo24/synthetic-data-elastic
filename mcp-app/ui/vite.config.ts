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
    outDir: resolve(_dirname, '../dist-ui'),
    emptyOutDir: true,
    target: 'es2020',
    // Single-file: inline all assets
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
  },
});
