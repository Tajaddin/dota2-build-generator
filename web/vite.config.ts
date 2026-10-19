/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Python server serves the built files from src/d2bg/static; `npm run dev` proxies the API to it.
const api = "http://127.0.0.1:4242";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/d2bg/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    proxy: { "/api": api, "/health": api, "/docs": api, "/openapi.json": api },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
  },
});
