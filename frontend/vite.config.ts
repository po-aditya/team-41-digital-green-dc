import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// CSP-friendly: no runtime style injection beyond Vite's dev needs.
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173, allowedHosts: true },
  preview: { host: true, port: 4173, allowedHosts: true },
  build: { outDir: 'dist', sourcemap: true },
});
