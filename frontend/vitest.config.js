import { defineConfig } from "vitest/config";

// Vitest config kept separate from vite.config.js so the build pipeline
// stays untouched. Tests run in node — the lib modules under test are pure
// JS with no DOM dependency.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/__tests__/**/*.test.{js,jsx}", "src/**/*.test.{js,jsx}"],
  },
});
