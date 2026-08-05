import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중에는 vite dev server가 /api를 FastAPI로 프록시한다 (세션 쿠키 동일 출처 유지).
// 배포 시에는 빌드 산출물(web/dist)을 FastAPI가 StaticFiles로 서빙한다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
});
