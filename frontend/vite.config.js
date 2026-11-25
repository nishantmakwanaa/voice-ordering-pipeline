import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendTarget = process.env.VITE_BACKEND_URL || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/menu': backendTarget,
      '/orders': backendTarget,
      '/cart': backendTarget,
      '/recommendations': backendTarget,
      '/reports': backendTarget,
      '/health': backendTarget,
      '/ws': {
        target: backendTarget.replace(/^http/, 'ws'),
        ws: true,
      },
    },
  },
});
