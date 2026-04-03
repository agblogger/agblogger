import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

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
      '/post/': {
        target: `http://localhost:${backendProxyPort}`,
        changeOrigin: true,
        bypass(req) {
          // Only proxy asset requests (paths with a file extension after slug/)
          const path = req.url ?? '';
          const parts = path.replace(/^\/post\//, '').split('/');
          if (parts.length >= 2) {
            const leaf = parts.at(-1) ?? '';
            if (leaf.includes('.') && !leaf.endsWith('.md')) {
              return; // proxy to backend
            }
          }
          return path; // serve SPA for post view routes
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
