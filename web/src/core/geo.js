// GPS 포그라운드 위치 취득 (PLAN 10절, D-13/D-21/D-59).
//
// 서버는 D-30에서 `/matrix`의 GPS 4개 파라미터를 완성해 뒀지만 프론트가 좌표를
// 한 번도 보내지 않아 실사용에서 항상 시각표 추정이었다 (이슈 #81). 여기가 그 반쪽이다.
//
// ★ iOS 홈화면 PWA는 `getCurrentPosition`의 권한 프롬프트를 **사용자 탭 안에서만**
// 안정적으로 띄운다 — 푸시(push.js, D-21)와 같은 제약이다. 그래서 정책은 두 갈래다:
//   1) 권한이 이미 있으면(또는 사용자가 한 번 탭으로 켰으면) 매 조회 때 조용히 자동 시도
//   2) 자동 시도가 실패/무응답이면 배지를 눌러 **제스처 안에서** 권한을 요청 (viaTap)
//
// 이 모듈은 import 시점에 `navigator`를 만지지 않는다 — node 스모크에서 순수 함수만
// import해 검증할 수 있어야 하기 때문이다.

// ── 조정값 (D-17: 매직 넘버를 로직에 인라인하지 않는다) ─────────────────────
// 취득이 이보다 오래 걸리면 GPS 없이 조회한다 — 매트릭스가 GPS를 기다리게 두지 않는다.
export const GEO_TIMEOUT_MS = 4000;
// 브라우저 캐시 좌표 허용 나이. 서버 신선도(GeoConfig 30초)의 절반으로 잡아 전송 지연 여유.
export const GEO_MAX_AGE_MS = 15000;
export const GEO_HIGH_ACCURACY = true;
// 사용자가 배지를 눌러 권한을 켰고 성공한 적이 있다 — 이후 조회는 자동 시도한다.
const OPTIN_KEY = "itx.geo.optin";

export function geoSupported() {
  return typeof navigator !== "undefined" && "geolocation" in navigator;
}

export function hasOptedIn() {
  try {
    return localStorage.getItem(OPTIN_KEY) === "1";
  } catch {
    return false;
  }
}

export function setOptedIn(on) {
  try {
    if (on) localStorage.setItem(OPTIN_KEY, "1");
    else localStorage.removeItem(OPTIN_KEY);
  } catch {
    /* 저장 실패는 무시 — opt-in은 편의 장치일 뿐이다 */
  }
}

// "granted" | "denied" | "prompt" | "unknown".
// Safari는 Permissions API가 없거나 geolocation 이름에서 throw한다 → "unknown".
export async function queryPermission() {
  try {
    if (typeof navigator === "undefined" || !navigator.permissions?.query) return "unknown";
    const status = await navigator.permissions.query({ name: "geolocation" });
    return status.state; // "granted" | "denied" | "prompt"
  } catch {
    return "unknown";
  }
}

// 순수: 이번 load에서 자동 취득을 시도할지. 프롬프트를 강제로 띄우는 경로는 여기가 아니다.
export function shouldAutoAcquire({ supported, permission, optedIn, last }) {
  if (!supported) return false;
  if (permission === "denied") return false; // 확실히 거부됨 — 탭해도 설정으로 가야 한다
  if (permission === "granted" || optedIn) return true; // 프롬프트 없이 바로 얻는다
  // 이 세션에서 이미 거절/무응답이면 자동으로 또 찌르지 않는다 — 탭을 기다린다.
  if (last === "denied" || last === "prompt") return false;
  // 첫 시도, 또는 timeout/unavailable 뒤 재시도 — 프롬프트를 강제하지 않는 실패라 무해하다.
  return true;
}

// 순수: GeolocationPositionError.code → 상태.
// 1=PERMISSION_DENIED 2=POSITION_UNAVAILABLE 3=TIMEOUT.
// code 1이 자동 시도(viaTap=false)에서 왔고 권한이 "denied"로 확정되지 않았다면 → "prompt":
// iOS 자동 시도가 프롬프트도 못 띄우고 조용히 죽은 경우와 진짜 거부를 구분한다.
export function classifyError(code, { permission = "unknown", viaTap = false } = {}) {
  if (code === 1) return permission === "denied" || viaTap ? "denied" : "prompt";
  if (code === 2) return "unavailable";
  if (code === 3) return "timeout";
  return "unavailable";
}

// getCurrentPosition 래퍼. **절대 reject하지 않는다** — 화면 흐름을 막지 않으려고
// { state, fix }로만 돌려준다. state: "ok"|"prompt"|"denied"|"unavailable"|"timeout"|"unsupported".
export function acquireFix({ viaTap = false, permission = "unknown" } = {}) {
  return new Promise((resolve) => {
    if (!geoSupported()) {
      resolve({ state: "unsupported", fix: null });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = pos.coords;
        resolve({
          state: "ok",
          fix: {
            lat: c.latitude,
            lng: c.longitude,
            accuracy_m: c.accuracy,
            fixed_at_ms: pos.timestamp, // epoch ms — 서버가 그대로 KST로 변환 (D-30)
          },
        });
      },
      (err) => resolve({ state: classifyError(err.code, { permission, viaTap }), fix: null }),
      { enableHighAccuracy: GEO_HIGH_ACCURACY, timeout: GEO_TIMEOUT_MS, maximumAge: GEO_MAX_AGE_MS }
    );
  });
}

// 순수: fix → `/matrix` 쿼리 파라미터. 넷이 전부 유한 숫자일 때만 4개, 아니면 {}.
// **부분 전송은 없다** (D-30: 넷 다 없으면 신선도를 판단할 수 없다). iOS가 accuracy를
// null로 주는 일이 있어 하나라도 비면 전부 버린다.
export function gpsParams(fix) {
  if (!fix) return {};
  const { lat, lng, accuracy_m, fixed_at_ms } = fix;
  const all = [lat, lng, accuracy_m, fixed_at_ms];
  if (!all.every((v) => typeof v === "number" && Number.isFinite(v))) return {};
  return { lat, lng, gps_accuracy_m: accuracy_m, gps_fixed_at_ms: fixed_at_ms };
}

// 순수: 배지 한 벌. 문구(note)와 탭 가능 여부를 여기서 정한다 — 두 스킨이 같은 말을 하도록
// (format.js와 같은 이유, D-50). 라벨 본문("GPS 실측"/"시각표 추정")은 스킨 어휘라 스킨이 붙인다.
//   반환: { gps, note, tappable }
//     gps      — 서버가 GPS로 판정했는가 (배지 색/문구 본문 선택)
//     note     — 배지 옆 작은 글씨 (없으면 null)
//     tappable — 배지를 눌러 권한을 요청할 수 있는가
export function positionBadge({ geoState, positionSource, positionNote, stale }) {
  // 오프라인 캐시본을 보는 중엔 위치 사유를 겹쳐 말하지 않는다 — "오프라인" 배지가 이미
  // 다른 진실을 말하고 있고, 캐시된 gps 라벨 옆에 실시간 GPS 사유가 붙으면 모순이다.
  if (stale) return { gps: positionSource === "gps", note: null, tappable: false };

  const gps = positionSource === "gps";
  if (gps) return { gps: true, note: null, tappable: false };

  // 여기부터는 시각표 추정(schedule). geoState로 왜 그런지 안내한다.
  switch (geoState) {
    case "acquiring":
      return { gps: false, note: "GPS 확인 중…", tappable: false };
    case "prompt":
      return { gps: false, note: "탭하면 위치 권한을 요청합니다", tappable: true };
    case "denied":
      return { gps: false, note: "위치 권한 꺼짐 — 설정에서 이 앱의 위치를 허용한 뒤 탭", tappable: true };
    case "timeout":
      return { gps: false, note: "GPS 응답 없음 — ↻로 다시 시도", tappable: true };
    case "unavailable":
      return { gps: false, note: "위치를 확인할 수 없음 (터널·실내) — 다음 조회 때 다시 시도", tappable: false };
    default:
      // ok(서버가 거부)·unsupported·idle: 서버 사유가 있으면 그대로, 없으면 조용히.
      return { gps: false, note: positionNote || null, tappable: false };
  }
}
