import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 本地开发：/api 代理到 FastAPI，避免 CORS
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
