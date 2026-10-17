import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { chunkSizeWarningLimit: 2000, target: "es2022" },
  esbuild: { target: "es2022" },
  optimizeDeps: { esbuildOptions: { target: "es2022" } },
  test: { environment: "jsdom", globals: false, include: ["src/**/*.test.{ts,tsx}"] },
});
