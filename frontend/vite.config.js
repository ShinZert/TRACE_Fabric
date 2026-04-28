import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes into Flask's static/dist/ so the production server can
// serve the bundle without a separate web server. Filenames are predictable
// (no hashes) so templates/index.html can hard-reference them.
export default defineConfig({
  plugins: [react()],
  base: "/static/dist/",
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:5000",
    },
  },
});
