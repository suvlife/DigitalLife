import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 8183,
    proxy: {
      '/teams': 'http://127.0.0.1:8180',
      '/rooms': 'http://127.0.0.1:8180',
      '/agents': 'http://127.0.0.1:8180',
      '/runs': 'http://127.0.0.1:8180',
      '/config': 'http://127.0.0.1:8180',
      '/system': 'http://127.0.0.1:8180',
      '/files': 'http://127.0.0.1:8180',
      '/auth': 'http://127.0.0.1:8180',
      '/usage': 'http://127.0.0.1:8180',
      '/role_templates': 'http://127.0.0.1:8180',
      '/activities': 'http://127.0.0.1:8180',
      '/ws': { target: 'ws://127.0.0.1:8180', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  base: '/v3/',
});
