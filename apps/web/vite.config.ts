import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// `npm run dev` serves the app on http://localhost:5173 and sends /api to the yyai server.
// Point it at another server with YYAI_API_URL, for example YYAI_API_URL=http://127.0.0.1:18000 npm run dev
const apiUrl = process.env.YYAI_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: apiUrl } },
  },
  build: {
    outDir: 'dist',
    // Fonts and images stay separate files (never inlined as data: URLs), so the strict
    // Content-Security-Policy in the Caddyfile can allow only our own origin.
    assetsInlineLimit: 0,
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})
