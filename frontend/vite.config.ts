import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const apiPort = Number(process.env.MEDITRON_API_PORT ?? "8000");
const webPort = Number(process.env.MEDITRON_WEB_PORT ?? "5173");
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: webPort,
    strictPort: true,
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
      "/health": `http://127.0.0.1:${apiPort}`,
    },
  },
});
