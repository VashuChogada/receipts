import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';

// The API runs on 8491 (uvicorn in dev, behind Caddy in production).
const API = process.env.RECEIPTS_API ?? 'http://127.0.0.1:8491';

export default defineConfig({
  plugins: [
    preact(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'Receipts',
        short_name: 'Receipts',
        description: 'Household receipts, scanned and filed on the home server',
        theme_color: '#0f766e',
        background_color: '#f8fafc',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // The app shell only. Receipts and the API always come from the server.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/ca\.crt/],
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
      },
    }),
  ],
  server: {
    host: true,
    proxy: { '/api': API },
  },
  build: { outDir: 'dist', sourcemap: false },
});
