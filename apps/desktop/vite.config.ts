import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Tauri window loads this build (apps/desktop/dist); in development it loads the dev server.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  // the microphone recorder's worklet is one file shared with the web app (packages/ui/public); the window's content policy needs it
  // served from the app itself
  publicDir: "../../packages/ui/public",
  server: { port: 1420, strictPort: true },
  build: { target: "es2022", outDir: "dist", emptyOutDir: true },
});
