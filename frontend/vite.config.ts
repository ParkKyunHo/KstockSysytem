import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// V7.1 Carbon Design System frontend.
//
// Backend proxy resolution (priority high → low):
//   1. VITE_API_PROXY_TARGET env (e.g. .env.development.local 또는
//      `VITE_API_PROXY_TARGET=... npm run dev`)
//   2. AWS Lightsail 운영 서버 (default — 사용자 단일 OWNER이므로 dev
//      에서 운영 데이터 직접 접근. HTTPS는 옵션 E 후속).
//
// 운영 배포 영향 0: vite dev server (5173) 한정. `npm run build` 산출물은
// hotfix.ps1로 운영 backend (43.200.235.74:8080)에 정적 파일로 mount되며
// 같은 origin이라 proxy가 필요 없음.
const DEFAULT_PROXY_TARGET = 'http://43.200.235.74:8080';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const httpTarget = env.VITE_API_PROXY_TARGET || DEFAULT_PROXY_TARGET;
  const wsTarget = httpTarget.replace(/^http/, 'ws');
  return {
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
      },
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: httpTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    target: 'es2022',
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
  };
});
