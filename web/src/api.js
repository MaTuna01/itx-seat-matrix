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
  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: { email, password } }),
  signup: (email, password, display_name) =>
    request("/api/auth/signup", { method: "POST", body: { email, password, display_name } }),
  logout: () => request("/api/auth/logout", { method: "POST" }),

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
