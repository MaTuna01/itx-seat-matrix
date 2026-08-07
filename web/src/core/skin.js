// 접속 기기에 따라 어느 스킨을 그릴지 정한다 (→ D-50).
//
// **맥이 기본으로 web을 받는 것이 이 파일의 핵심이다.** Phase 1~4 내내 개발·디버깅을 맥
// 브라우저로 해왔는데(D-43 미정 ③), iOS 스킨은 393pt 고정이라 맥에서 확인하기 나쁘다.
// 그래서 web 스킨을 버리지 않고 맥의 기본값으로 남긴다.

const KEY = "itx.skin";
export const SKINS = ["web", "ios"];

// `?ui=ios` / `?ui=web`으로 강제하고, `?ui=auto`로 되돌린다.
// 강제한 값은 localStorage에 고정된다 — 맥에서 iOS 스킨을 눈으로 볼 때 매번 붙일 필요가 없다.
function readOverride() {
  const v = new URLSearchParams(window.location.search).get("ui");
  if (v === "auto") return "auto";
  return SKINS.includes(v) ? v : null;
}

function fromUserAgent() {
  const ua = navigator.userAgent || "";
  // iPadOS 13+는 맥 UA로 위장한다 — UA만 보면 아이패드가 web 스킨을 받는다.
  // 맥에는 터치 포인트가 없으므로 그것으로 가른다.
  const iPadPretendingToBeMac = /Macintosh/.test(ua) && (navigator.maxTouchPoints || 0) > 1;
  return /iPhone|iPad|iPod/.test(ua) || iPadPretendingToBeMac ? "ios" : "web";
}

// 사파리 프라이빗 모드에서 localStorage가 던진다 — 스킨 선택은 저장에 실패해도 동작해야 한다
const store = {
  get() {
    try {
      return localStorage.getItem(KEY);
    } catch {
      return null;
    }
  },
  set(v) {
    try {
      if (v === null) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, v);
    } catch {
      /* 무시 */
    }
  },
};

export function resolveSkin() {
  const override = readOverride();
  if (override === "auto") store.set(null);
  else if (override) {
    store.set(override);
    return override;
  }
  const saved = store.get();
  if (SKINS.includes(saved)) return saved;
  return fromUserAgent();
}
