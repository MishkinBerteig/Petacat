import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

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
        target: 'http://app:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://app:8000',
        ws: true,
      },
    },
  },
})
