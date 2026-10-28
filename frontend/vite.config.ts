import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the Python backend, so the browser only ever
// talks to localhost:8077 and we never have to worry about CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 8077,
    proxy: {
      "/api": {
        target: "http://localhost:8010",
        changeOrigin: true,
      },
    },
  },
});
