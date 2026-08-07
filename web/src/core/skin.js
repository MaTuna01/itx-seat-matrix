// 접속 기기에 따라 어느 스킨을 그릴지 정한다 (→ D-50).
//
// **기준은 "iOS 기기냐 아니냐"다 — 맥이냐 아니냐가 아니다.**
// iOS 기기(아이폰·아이패드)만 `ios`를 받고, **그 외 전부**가 `web`을 받는다:
// 맥·윈도우·리눅스 데스크탑은 물론 **안드로이드 폰도** `web`이다.
//
// 그래도 되는 이유: web 스킨은 `max-width: 480`이라 **480px는 곧 폰 폭**이고,
// Phase 1~4 내내 아이폰에서 쓰던 화면이 바로 그것이다. 데스크탑 레이아웃이 폰에
// 찌그러지는 게 아니라 원래 폰용으로 만든 화면이 나온다.
//
// **폼팩터(모바일 vs 데스크탑)로 가르지 않는다.** ios 스킨은 "모바일"이 아니라
// **iOS 관용구**다(세이프 에어리어·홈 인디케이터·iOS 스위치·바텀시트). 안드로이드에 그걸
// 주면 크기는 맞고 관용구는 틀린 화면이 된다. 게다가 `pointer: coarse` + 폭으로 가르면
// 데스크탑 창을 좁혔을 때 스킨이 튄다 — 개발 중에 이게 제일 성가시다.
// 안드로이드를 실제로 쓰게 되면 `ios`에 얹을 게 아니라 `skins/android/`를 만드는 것이
// D-50 구조의 취지다.
//
// 데스크탑이 web을 받는 것은 그 자체로 목적이기도 하다 — Phase 1~4 내내 개발·디버깅을
// 데스크탑 브라우저로 해왔고(D-43 미정 ③), iOS 스킨은 393pt 고정이라 거기서 확인하기 나쁘다.

const KEY = "itx.skin";
export const SKINS = ["web", "ios"];

// `?ui=ios` / `?ui=web`으로 강제하고, `?ui=auto`로 되돌린다.
// 강제한 값은 localStorage에 고정된다 — 맥에서 iOS 스킨을 눈으로 볼 때 매번 붙일 필요가 없다.
function readOverride() {
  const v = new URLSearchParams(window.location.search).get("ui");
  if (v === "auto") return "auto";
  return SKINS.includes(v) ? v : null;
}

// 순수 함수로 뽑아 뒀다 — 기기별로 무엇을 받는지 `npm run smoke`가 고정한다.
// "맥이 web을 받는다"는 좁은 표현 때문에 한 번 오해가 났던 자리다.
export function skinForDevice(ua = "", maxTouchPoints = 0) {
  // iPadOS 13+는 맥 UA로 위장한다 — UA만 보면 아이패드가 web 스킨을 받는다.
  // 맥에는 터치 포인트가 없으므로 그것으로 가른다. `Macintosh` 조건이 함께 있어야
  // 터치 스크린 윈도우 노트북이 잘못 걸리지 않는다.
  const iPadPretendingToBeMac = /Macintosh/.test(ua) && maxTouchPoints > 1;
  return /iPhone|iPad|iPod/.test(ua) || iPadPretendingToBeMac ? "ios" : "web";
}

function fromUserAgent() {
  return skinForDevice(navigator.userAgent || "", navigator.maxTouchPoints || 0);
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
