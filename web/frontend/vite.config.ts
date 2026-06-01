import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // `ws: true` lets the live-play WebSocket (/api/live/ws/...) proxy through too.
      '/api': { target: 'http://localhost:8000', ws: true },
    },
  },
})
