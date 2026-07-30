import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// The client calls the API on relative paths (`API_BASE = '/api'`), so everything
// reaches the backend through this proxy. The target used to be `app:8000` — the
// Docker Compose service name and the port inside that container — which stops
// resolving the moment the client runs on the host (WP2.1 removed the container
// stack): the GUI loads and every request fails with `ENOTFOUND app`. It now points
// at the natively-run API, honouring the same `PORT` override `scripts/dev.sh` reads
// so the two cannot drift apart.
const API_PORT = process.env.PORT ?? '8100'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${API_PORT}`,
        changeOrigin: true,
      },
      '/ws': {
        target: `ws://127.0.0.1:${API_PORT}`,
        ws: true,
      },
    },
  },
})
