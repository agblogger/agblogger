import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

import { shouldProxyPostRequestToBackend } from './vitePostProxy'

const backendProxyPort = process.env['AGBLOGGER_BACKEND_PORT'] ?? '8000'
const allowedHosts = ['host.docker.internal']

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    allowedHosts,
    proxy: {
      '/api': {
        target: `http://localhost:${backendProxyPort}`,
        changeOrigin: true,
      },
      '/favicon.ico': {
        target: `http://localhost:${backendProxyPort}`,
        changeOrigin: true,
      },
      '/favicon.png': {
        target: `http://localhost:${backendProxyPort}`,
        changeOrigin: true,
      },
      '/favicon.svg': {
        target: `http://localhost:${backendProxyPort}`,
        changeOrigin: true,
      },
      '/favicon.webp': {
        target: `http://localhost:${backendProxyPort}`,
        changeOrigin: true,
      },
      '/post/': {
        target: `http://localhost:${backendProxyPort}`,
        changeOrigin: true,
        bypass(req) {
          const requestPath = req.url ?? ''
          if (shouldProxyPostRequestToBackend(requestPath)) {
            return
          }

          return requestPath
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
