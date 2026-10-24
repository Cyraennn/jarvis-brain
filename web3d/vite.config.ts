import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Cikti CYRAEN'in gomulu kaynak klasorune yazilir (assets/ hem git'te hem cyraen.spec'te):
// ui/hud/boot3d.py bu klasoru yerel sunucudan QtWebEngine'e verir.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  // Ust klasordeki (multi/) Tailwind 3 postcss.config.mjs'in bulunup uygulanmasini engeller
  css: { postcss: { plugins: [] } },
  build: {
    outDir: '../assets/web3d',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600,
  },
  server: { host: '127.0.0.1', port: 5183 },
})
