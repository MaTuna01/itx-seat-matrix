// FastAPI 호출 래퍼. 세션 쿠키를 항상 함께 보낸다 (PLAN 6절).
// 401이면 UnauthorizedError를 던져 App이 로그인 화면으로 라우팅한다.

export class UnauthorizedError extends Error {}

async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new UnauthorizedError("세션이 만료되었습니다");
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* 본문이 JSON이 아니면 상태 코드만 */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  me: () => request("/api/me"),
  // remember=true면 지속 쿠키 30일, 아니면 브라우저 세션 쿠키 + 12시간 (D-23)
  login: (email, password, remember) =>
    request("/api/auth/login", { method: "POST", body: { email, password, remember } }),
  signup: (email, password, display_name, remember) =>
    request("/api/auth/signup", {
      method: "POST",
      body: { email, password, display_name, remember },
    }),
  logout: () => request("/api/auth/logout", { method: "POST" }),

  // 코레일 계정 연결 (D-22). 응답은 MeOut — 자격증명은 절대 되돌아오지 않는다.
  // 저장 시점에 실제 로그인 검증은 하지 않는다(호출 예절) — 틀린 자격증명은
  // 첫 매트릭스 조회에서 드러난다.
  linkKorail: (korail_id, korail_pw) =>
    request("/api/me/korail", { method: "PUT", body: { korail_id, korail_pw } }),
  unlinkKorail: () => request("/api/me/korail", { method: "DELETE" }),

  // 관리자 전용 (D-24). 비관리자는 403
  adminSettings: () => request("/api/admin/settings"),
  setSignupEnabled: (signup_enabled) =>
    request("/api/admin/settings", { method: "PATCH", body: { signup_enabled } }),

  // 역 드롭다운 소스 (D-25). Phase 2에서 station 테이블로 소스만 바뀐다
  stations: () => request("/api/stations"),
  // time은 "이 시각 이후 출발" 하한 (HH:MM)
  searchTrains: ({ date, from, to, time }) => {
    const params = new URLSearchParams({ date, from, to });
    if (time) params.set("time", time);
    return request(`/api/trains/search?${params}`);
  },

  subscriptions: () => request("/api/subscriptions"),
  createSubscription: (payload) =>
    request("/api/subscriptions", { method: "POST", body: payload }),
  // 앉음 / 이동 / 일어남 — 전이는 전부 이 하나로 (D-15)
  patchSubscription: (id, payload) =>
    request(`/api/subscriptions/${id}`, { method: "PATCH", body: payload }),
  deleteSubscription: (id) => request(`/api/subscriptions/${id}`, { method: "DELETE" }),

  matrix: ({ train_no, date, board_at, alight_at, my_seat }) => {
    const params = new URLSearchParams({ date, board_at, alight_at });
    if (my_seat) params.set("my_seat", my_seat);
    return request(`/api/trains/${train_no}/matrix?${params}`);
  },
};

// 열차 안은 회선이 자주 끊긴다 — 마지막 매트릭스를 로컬에 캐시해 두고
// 조회 실패 시 빈 화면 대신 캐시본을 보여준다 (PLAN 10절).
const CACHE_KEY = "itx.matrix.last";

export function cacheMatrix(data) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(data));
  } catch {
    /* 저장 실패는 무시 — 캐시는 보조 장치다 */
  }
}

export function readCachedMatrix() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
