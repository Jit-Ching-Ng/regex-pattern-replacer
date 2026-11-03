import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Django API runs on :8000 and Vite proxies /api to it,
// so the browser sees a single origin (no CORS setup needed locally).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
