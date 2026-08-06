// 웹푸시 구독 (PLAN 8·10절, D-9/D-21).
//
// ★ `Notification.requestPermission()`은 **버튼 탭 핸들러 안에서만** 부른다.
// 페이지 로드 시 자동 요청은 iOS에서 조용히 실패한다 — 예외도 안 나고 프롬프트도
// 안 뜬다. 그래서 여기 있는 함수는 전부 "사용자가 방금 눌렀다"를 전제로 한다 (D-21).
//
// iOS는 **홈화면에 추가된 웹앱**에서만 푸시를 허용한다. 사파리 탭에서는 permission을
// 요청해도 실패하므로, 그 상태를 먼저 진단해서 알려준다 (안내 없이 실패하면 사용자는
// 앱이 고장난 줄 안다).

const SW_URL = "/sw.js";

export function isStandalone() {
  return (
    window.navigator.standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches
  );
}

// 왜 푸시를 켤 수 없는지. null이면 켤 수 있다.
export function pushBlockedReason() {
  if (!("serviceWorker" in navigator)) return "이 브라우저는 서비스 워커를 지원하지 않습니다";
  if (!("PushManager" in window)) {
    return isStandalone()
      ? "이 브라우저는 웹푸시를 지원하지 않습니다"
      : "공유 → 홈 화면에 추가 후 그 앱에서 열어야 알림을 켤 수 있습니다 (iOS 제약)";
  }
  if (Notification.permission === "denied") {
    return "알림이 차단돼 있습니다 · 기기 설정에서 이 앱의 알림을 허용해 주세요";
  }
  return null;
}

export async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  try {
    return await navigator.serviceWorker.register(SW_URL);
  } catch {
    return null; // 오프라인 캐시가 없을 뿐 앱은 그대로 동작한다
  }
}

// base64url → Uint8Array. applicationServerKey가 요구하는 형태다.
function decodeKey(base64url) {
  const padded = base64url.padEnd(Math.ceil(base64url.length / 4) * 4, "=");
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (ch) => ch.charCodeAt(0));
}

/**
 * 이 기기를 알림 대상으로 등록한다. **버튼 탭 핸들러에서만 호출할 것.**
 * 반환값은 서버에 보낼 { endpoint, keys } — 저장은 호출부가 한다.
 */
export async function subscribeThisDevice(vapidPublicKey) {
  const blocked = pushBlockedReason();
  if (blocked) throw new Error(blocked);
  if (!vapidPublicKey) throw new Error("서버에 VAPID 공개키가 설정되지 않았습니다 (.env)");

  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("알림 권한이 허용되지 않았습니다");

  const registration = (await navigator.serviceWorker.getRegistration(SW_URL))
    || (await registerServiceWorker());
  if (!registration) throw new Error("서비스 워커를 등록할 수 없습니다");
  await navigator.serviceWorker.ready;

  // 이미 구독돼 있으면 그대로 쓴다 — 재구독하면 endpoint가 바뀌어 서버에 행이 하나 더 생긴다
  const existing = await registration.pushManager.getSubscription();
  const subscription =
    existing ||
    (await registration.pushManager.subscribe({
      userVisibleOnly: true, // iOS 필수. 조용한 푸시는 허용되지 않는다
      applicationServerKey: decodeKey(vapidPublicKey),
    }));

  const { endpoint, keys } = subscription.toJSON();
  return { endpoint, keys };
}

export async function unsubscribeThisDevice() {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.getRegistration(SW_URL);
  const subscription = registration && (await registration.pushManager.getSubscription());
  if (subscription) await subscription.unsubscribe();
}

// 기기 라벨 기본값. 사용자가 폰/아이패드를 구분할 수 있을 정도면 충분하다.
export function guessDeviceLabel() {
  const ua = navigator.userAgent;
  if (/iPad/.test(ua)) return "아이패드";
  if (/iPhone/.test(ua)) return "아이폰";
  if (/Android/.test(ua)) return "안드로이드";
  if (/Macintosh/.test(ua)) return "맥";
  return "이 기기";
}
