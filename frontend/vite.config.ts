import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

// The dev proxy keeps API calls same-origin for the browser; direct-to-S3 uploads always
// cross origins and therefore rely on the bucket CORS rules provisioned by the backend.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/**/*.d.ts'],
      reporter: [
        'text',
        'json-summary',
        // Repository-relative SF paths let Coveralls merge Python and TS without rewriting reports.
        ['lcovonly', { projectRoot: fileURLToPath(new URL('..', import.meta.url)) }],
      ],
    },
  },
});
