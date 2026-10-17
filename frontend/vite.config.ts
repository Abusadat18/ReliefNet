import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  // The Google map chunk (deck.gl, about 1 MB) loads lazily, only when a Maps key is set.
  build: { chunkSizeWarningLimit: 1100 },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: api, changeOrigin: true },
      "/uploads": { target: api, changeOrigin: true },
    },
  },
});
