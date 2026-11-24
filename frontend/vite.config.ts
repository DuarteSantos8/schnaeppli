import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "Schnäppli",
        short_name: "Schnäppli",
        description: "Your personal AI shopping agent",
        theme_color: "#f4f3f1",
        background_color: "#f4f3f1",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        runtimeCaching: [
          {
            // Previously loaded data stays readable offline; fresh data wins when online.
            urlPattern: ({ url }) =>
              url.pathname.startsWith("/api/") &&
              !url.pathname.startsWith("/api/auth") &&
              !url.pathname.startsWith("/api/ai/credentials"),
            handler: "NetworkFirst",
            method: "GET",
            options: {
              cacheName: "schnaeppli-api",
              networkTimeoutSeconds: 6,
              expiration: { maxEntries: 200, maxAgeSeconds: 7 * 24 * 3600 },
              cacheableResponse: { statuses: [200] },
            },
          },
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api/img"),
            handler: "CacheFirst",
            options: { cacheName: "schnaeppli-img", expiration: { maxEntries: 400, maxAgeSeconds: 14 * 24 * 3600 } },
          },
        ],
      },
    }),
  ],
  server: { proxy: { "/api": process.env.SCHNAEPPLI_API || "http://127.0.0.1:8000" } },
  preview: { proxy: { "/api": process.env.SCHNAEPPLI_API || "http://127.0.0.1:8000" } },
  build: { target: "es2022", sourcemap: false },
});
