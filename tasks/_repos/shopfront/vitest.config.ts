import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Keep Vite's cache out of the project, so it never shows up in a diff.
  cacheDir: "/tmp/shopfront-vite",
  test: {
    environment: "jsdom",
    globals: true,
  },
});
