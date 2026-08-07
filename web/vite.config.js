import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The `@` alias is required by shadcn/ui: its generated components import `@/lib/utils` and
// `@/components/ui/*`, and the CLI writes those paths verbatim. `jsconfig.json` mirrors this
// mapping for the CLI's own resolver, which looks for it even in a plain-JS project.

// The frontend calls the API at a relative /api path and the dev server proxies it to
// FastAPI. This keeps browser and API same-origin, which is what lets the SameSite=lax
// session cookie flow without resorting to SameSite=None. Production mirrors the same
// shape with a platform rewrite (e.g. Vercel rewriting /api/* to the API host).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
