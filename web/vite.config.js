import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The frontend calls the API at a relative /api path and the dev server proxies it to
// FastAPI. This keeps browser and API same-origin, which is what lets the SameSite=lax
// session cookie flow without resorting to SameSite=None. Production mirrors the same
// shape with a platform rewrite (e.g. Vercel rewriting /api/* to the API host).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
