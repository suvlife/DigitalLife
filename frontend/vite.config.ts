import { defineConfig, type ProxyOptions } from 'vite';
import vue from '@vitejs/plugin-vue';

const backendTarget = 'http://127.0.0.1:8180';

function createApiProxy(target: string): ProxyOptions {
  return {
    target,
    configure(proxy) {
      proxy.on('error', (_error, _req, res) => {
        const response = res as {
          headersSent?: boolean;
          writeHead: (statusCode: number, headers: Record<string, string>) => void;
          end: (body: string) => void;
        };

        if (response.headersSent) {
          return;
        }

        response.writeHead(503, {
          'Content-Type': 'application/json; charset=utf-8',
          'X-Proxy-Error': 'backend-unavailable',
        });
        response.end(JSON.stringify({
          error_code: 'BACKEND_UNAVAILABLE',
          error_desc: '开发代理无法连接后端服务，请确认后端已启动',
        }));
      });
    },
  };
}

export default defineConfig({
  base: '/v1/',
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        // vendor 分包：消除 >500KB 单 chunk 警告，改善首屏并行加载与缓存命中（审计性能项）
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'vue-i18n'],
          'vendor-markdown': ['markdown-it', 'markdown-it-task-lists', 'highlight.js'],
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 8181,
    proxy: {
      '/auth': createApiProxy(backendTarget),
      '/config': createApiProxy(backendTarget),
      '/system': createApiProxy(backendTarget),
      '/role_templates': createApiProxy(backendTarget),
      '/agents': createApiProxy(backendTarget),
      '/members': createApiProxy(backendTarget),
      '/rooms': createApiProxy(backendTarget),
      '/teams': createApiProxy(backendTarget),
      '/activities': createApiProxy(backendTarget),
      '/runs': createApiProxy(backendTarget),
      '/usage': createApiProxy(backendTarget),
      '/files': createApiProxy(backendTarget),
      '/ws': { target: 'ws://127.0.0.1:8180', ws: true },
    },
  },
});
