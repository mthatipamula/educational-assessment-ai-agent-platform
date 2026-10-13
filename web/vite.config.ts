import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// `npm run dev` serves the UI on :5176 and forwards API calls to the backend (docker compose up).
export default defineConfig({
  plugins: [react()],
  server: { port: 5176, proxy: { '/api': process.env.API_TARGET ?? 'http://localhost:8071' } },
});
