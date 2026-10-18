import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    // 5173 belongs to Flow Kit's dashboard; strictPort so the two never swap.
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": "http://localhost:8434",
      "/media": "http://localhost:8434",
      "/ws": {
        target: "ws://localhost:8434",
        ws: true,
      },
    },
  },
});
