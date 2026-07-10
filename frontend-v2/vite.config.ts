import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

const backend = process.env.VITE_DEV_BACKEND || 'http://127.0.0.1:8180';
export default defineConfig({
  base: '/v2/',
  plugins: [vue()],
  server: {
    port: 8182,
    proxy: {
      '/teams': backend, '/rooms': backend, '/agents': backend, '/activities': backend,
      '/runs': backend, '/config': backend, '/system': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
});
