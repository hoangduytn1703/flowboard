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
    // 127.0.0.1, not "localhost": the agent listens on IPv4 only, and on
    // Windows Node tries ::1 first — every proxied call waited ~200 ms for
    // that to fail (2026-10-24: /api/health 209 ms via localhost, 3 ms direct).
    proxy: {
      "/api": "http://127.0.0.1:8434",
      "/media": "http://127.0.0.1:8434",
      "/ws": {
        target: "ws://127.0.0.1:8434",
        ws: true,
      },
    },
  },
});
