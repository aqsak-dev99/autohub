import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dashboard calls /api on its own origin and Vite forwards it to FastAPI.
// Same origin means no CORS setup, which matters in Codespaces where every port has its own URL.
const api = process.env.API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true, // Codespaces serves the dev server from *.app.github.dev
    hmr: process.env.HMR_CLIENT_PORT ? { clientPort: Number(process.env.HMR_CLIENT_PORT) } : undefined,
    proxy: { '/api': { target: api, changeOrigin: true }, '/health': { target: api, changeOrigin: true } },
  },
  preview: { port: 4173, proxy: { '/api': { target: api, changeOrigin: true } } },
})
