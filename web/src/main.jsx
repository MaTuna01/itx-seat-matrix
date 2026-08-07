import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { registerServiceWorker } from "./core/push";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);

// 서비스 워커 등록 — 오프라인 캐시 + 푸시 수신의 전제 (PLAN 10절).
// **권한 요청은 하지 않는다.** 등록과 권한은 별개이고, 로드 시 권한을 요청하면
// iOS에서 조용히 실패한다 (D-21). 권한은 설정 화면 버튼 탭에서만 요청한다.
registerServiceWorker();

// 알림 탭 딥링크의 폴백 경로 (D-20). iOS 홈화면 웹앱에서는 service worker의
// `client.navigate()`가 막힐 수 있어, 그때 워커가 이 메시지를 보낸다.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("message", (event) => {
    if (event.data && event.data.type === "itx:navigate" && event.data.url) {
      window.location.href = event.data.url;
    }
  });
}
