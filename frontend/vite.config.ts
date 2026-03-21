import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const railway = env.RAILWAY_API_BASE_URL?.replace(/\/$/, "") || "";
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: railway || "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
