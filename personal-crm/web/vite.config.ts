import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/app/', plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: Object.fromEntries(['/auth', '/ready', '/workspace', '/sources', '/tasks', '/proposals', '/overview', '/ai'].map(path =>
      [path, { target: 'http://127.0.0.1:8001', changeOrigin: false }])) },
  test: { include:['src/**/*.test.ts','src/**/*.test.tsx'], environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], restoreMocks: true },
});
