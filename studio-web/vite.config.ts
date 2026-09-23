/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

interface ProxyEvents {
  on(event: 'proxyReq', listener: (request: { removeHeader(name: string): void }) => void): void;
}

// The production build is served by the Python Studio server, so it is
// written straight into the package. During `pnpm dev`, API calls are
// proxied to a Studio server started with `rocqipath studio`.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../src/rocqipath/studio/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        // Studio rejects cross-origin writes; the dev proxy is same-machine.
        configure: (proxy) =>
          (proxy as unknown as ProxyEvents).on('proxyReq', (request) => request.removeHeader('origin')),
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
});
