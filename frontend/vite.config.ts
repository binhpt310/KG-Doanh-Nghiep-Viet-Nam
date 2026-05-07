import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: SPA on :5173, Flask API on :5001 (run `python script.py` or Docker kg-app on 5002→map proxy if needed)
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
      },
    },
  },
});
