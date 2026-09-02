// 개발 전용 프리뷰 — 백엔드 없이 스킨 화면 하나만 렌더한다. 빌드에 포함되지 않는다
// (vite 기본 엔트리는 index.html뿐이라 dist/에 나타나지 않는다).
//
// PLAN 11절이 "화면마다 눈으로 확인"을 요구하는데 실기기는 배포 후에나 가능해서 만들었다.
// 실기기 확인을 대체하지는 못한다 — 레이아웃이 깨진 채로 쌓이는 것을 막을 뿐이다.
import { createRoot } from "react-dom/client";
import ios from "./skins/ios";
import web from "./skins/web";

// API를 흉내 낸다. 화면이 로딩/에러 상태로만 보이면 레이아웃을 볼 수 없다.
const CANNED = {
  "/api/admin/settings": { signup_enabled: false },
  // D-53. 자기 자신(id 1)과 관리자에는 삭제 버튼이 안 그려지는지 눈으로 본다
  "/api/admin/users": [
    { id: 1, email: "me@example.com", display_name: "나", is_admin: true,
      created_at: "2026-07-20T09:00:00+09:00", korail_linked: true, discord_linked: true,
      subscription_count: 12 },
    { id: 2, email: "friend@example.com", display_name: "지인", is_admin: false,
      created_at: "2026-08-07T09:00:00+09:00", korail_linked: false, discord_linked: false,
      subscription_count: 0 },
  ],
  "/api/push/config": { vapid_public_key: "preview" },
  "/api/push/devices": [
    { id: 1, label: "iPhone · Safari", created_at: "2026-07-28T09:00:00+09:00" },
    { id: 2, label: "Mac · Chrome", created_at: "2026-08-02T09:00:00+09:00" },
  ],
  "/api/stations": ["수원", "안양", "영등포", "용산", "청량리", "천안", "평택"].map((name) => ({ name })),
  // 즐겨찾기 노선 (D-56) — 피그마 05(web)·02(ios) 목업과 같은 3개
  "/api/presets": [
    { id: 1, from_station: "수원", to_station: "용산" },
    { id: 2, from_station: "용산", to_station: "수원" },
    { id: 3, from_station: "수원", to_station: "청량리" },
  ].map((p) => ({ ...p, name: `${p.from_station} → ${p.to_station}`, usual_train_nos: [], poll_offsets_min: [10, 4] })),
  "/api/subscriptions": [{ board_at: "수원", alight_at: "청량리" }],
  "/api/trains/search": [
    { train_no: "1073", train_name: "ITX-마음", dep_time: "2026-08-06T07:12:00+09:00", arr_time: "2026-08-06T08:24:00+09:00" },
    { train_no: "1075", train_name: "ITX-새마을", dep_time: "2026-08-06T07:41:00+09:00", arr_time: "2026-08-06T08:58:00+09:00" },
    { train_no: "4202", train_name: "무궁화", dep_time: "2026-08-06T08:05:00+09:00", arr_time: "2026-08-06T09:31:00+09:00" },
  ],
};

// 06 입석 — 두 목록(D-46)이 다 보이는 상태로 만든다.
// 4-12C는 끝까지 비고, 1-2B는 앞 두 구간이 팔려 영등포부터 빈다 = move_to_later
const STOPS = ["수원", "안양", "영등포", "용산", "청량리"];
const rec = (car, seat_no, from, until, clear_all) =>
  ({ car, seat_no, clear_from_idx: from, clear_until_idx: until, clear_all });
CANNED["/matrix"] = {
  train_no: "1073", train_name: "ITX-마음", date: "2026-08-07",
  board_at: "수원", alight_at: "청량리", stops: STOPS,
  sub_status: "STANDING", current_seg_idx: 0, fetched_at: new Date(Date.now() - 120000).toISOString(),
  // 서버 리터럴과 맞춘다 — "schedule"|"gps" (D-59). position_note는 GPS 미사용 사유(없으면 null)
  position_source: "schedule", position_note: null, delay_minutes: null, failed_seg_idxs: [],
  next_poll: { station: "안양", offset_min: 3 },
  seats: [
    { car: 4, seat_no: "12C", cells: [false, false, false, false] },
    { car: 2, seat_no: "3A", cells: [false, false, false, true] },
    { car: 1, seat_no: "2B", cells: [true, true, false, false] },
    { car: 3, seat_no: "9C", cells: [true, true, true, true] },
  ],
  verdict: {
    start_seg_idx: 0, decision_needed: true, all_sold_after_current: false,
    my_seat_status: null, my_seat_sold_from: null,
    move_to: [rec(4, "12C", 0, 4, true), rec(2, "3A", 0, 3, false)],
    move_to_later: [rec(1, "2B", 2, 4, true)],
  },
};

// 07 착석 — 내 자리(3-7A)가 용산부터 팔렸고 지금 옮길 자리가 없다 = laterOnly.
// 최상단 고정과 구분선(D-49)은 그리기 쪽이라 스모크가 못 잡는다.
const SEATED_MATRIX = {
  ...CANNED["/matrix"],
  sub_status: "SEATED", my_car: 3, my_seat_no: "7A", current_seg_idx: 1,
  seats: [
    { car: 4, seat_no: "12C", cells: [false, true, false, false] },
    { car: 3, seat_no: "7A", cells: [false, false, false, true] },
    { car: 3, seat_no: "9C", cells: [true, true, true, true] },
  ],
  verdict: {
    start_seg_idx: 1, decision_needed: true, all_sold_after_current: false,
    my_seat_status: "SOLD_FROM", my_seat_sold_from: "용산",
    move_to: [], move_to_later: [rec(4, "12C", 2, 4, true)],
  },
};

// 정차역이 많은 노선. 5개짜리 기본 픽스처로는 아무것도 재현되지 않는다 —
// **목업이 짧으면 목업만 통과한다.** 실기기에서 깨진 두 노선을 그대로 옮겨 뒀다.
// 좌석도 넉넉히 둬서 문서가 스크롤되게 만든다 — 고정 액션 바는 스크롤이 있어야 드러난다.
//
//   `?state=long`    창원→수원 12개역 — 구간 11개 + **네 글자 역**(`창원중앙`)
//   `?state=longest` 무궁화 용산→광주송정 16개역 — **출발역과 현재 향하는 역이 인접**하다.
//                    12개역으로는 이 인접이 안 만들어져 진행바 라벨 겹침을 못 봤다.
//                    (실제 노선은 20개역쯤이고 정차역 목록은 근사값이다 — 겹침 재현이 목적)
const LONG_STOPS = [
  "창원", "창원중앙", "진영", "밀양", "동대구", "대구", "구미", "김천", "영동", "대전", "천안", "수원",
];
const LONGEST_STOPS = [
  "용산", "영등포", "수원", "평택", "천안", "조치원", "부강", "신탄진", "서대전", "계룡",
  "논산", "익산", "김제", "정읍", "장성", "광주송정",
];
const LONG_MATRIX = {
  ...CANNED["/matrix"],
  stops: LONG_STOPS,
  board_at: "창원",
  alight_at: "수원",
  current_seg_idx: 1,
  next_poll: { station: "창원중앙", offset_min: 10 },
  seats: Array.from({ length: 12 }, (_, i) => ({
    car: (i % 4) + 1,
    seat_no: `${10 + i}${"ABCD"[i % 4]}`,
    cells: LONG_STOPS.slice(0, -1).map((_, j) => (i + j) % 3 === 0),
  })),
  verdict: {
    ...CANNED["/matrix"].verdict,
    start_seg_idx: 1,
    move_to: [rec(4, "12C", 1, 5, false)],
    move_to_later: [rec(2, "17D", 4, 9, false)],
  },
};

const LONGEST_MATRIX = {
  ...CANNED["/matrix"],
  train_no: "1451", train_name: "무궁화호",
  stops: LONGEST_STOPS,
  board_at: "용산",
  alight_at: "광주송정",
  current_seg_idx: 0,
  next_poll: { station: "영등포", offset_min: 10 },
  // 1-1은 실기기 화면과 같은 모양으로 고정한다 — 지금 구간부터 팔려 있고 조치원~서대전만
  // 빈다. `move_to_later`와 반드시 일치해야 한다: 어긋나면 판정 카드와 액션 바가 다른 역을
  // 말하고, 그건 **고치려는 버그와 똑같이 생긴 픽스처 버그**라 확인이 무의미해진다.
  seats: Array.from({ length: 14 }, (_, i) => ({
    car: 1,
    seat_no: `${i + 1}`,
    cells: LONGEST_STOPS.slice(0, -1).map((_, j) =>
      i === 0 ? j < 5 || j > 7 : j < 5 || (i + j) % 4 !== 0
    ),
  })),
  verdict: {
    ...CANNED["/matrix"].verdict,
    start_seg_idx: 0,
    move_to: [],
    move_to_later: [rec(1, "1", 5, 8, false)],
  },
};

const mode = new URLSearchParams(location.search).get("state");
const seatedMode = mode === "seated";

// GPS 배지 상태 (D-59). `?state=gps` = 서버가 GPS로 판정, `?state=gpsnote` = 좌표를
// 보냈으나 거부돼 사유가 붙은 상태. 배지·사유 문구를 눈으로 본다.
const GPS_MATRIX = { ...CANNED["/matrix"], position_source: "gps", current_seg_idx: 1, position_note: null };
const GPSNOTE_MATRIX = { ...CANNED["/matrix"], position_source: "schedule", position_note: "GPS 정확도 500m — 100m 초과" };

window.fetch = async (url) => {
  const path = String(url).split("?")[0];
  const hit = Object.keys(CANNED).find((k) => path.endsWith(k));
  const matrix = seatedMode
    ? SEATED_MATRIX
    : mode === "long"
    ? LONG_MATRIX
    : mode === "longest"
    ? LONGEST_MATRIX
    : mode === "gps"
    ? GPS_MATRIX
    : mode === "gpsnote"
    ? GPSNOTE_MATRIX
    : CANNED["/matrix"];
  const body = hit === "/matrix" ? matrix : hit && CANNED[hit];
  return {
    ok: !!hit,
    status: hit ? 200 : 404,
    json: async () => (hit ? body : { detail: "preview" }),
  };
};

// `?geo=ok|denied|timeout` — geolocation을 결정적으로 스텁한다 (D-59). 프리뷰는 백엔드도
// 권한 프롬프트도 없어야 하므로, 실제 navigator.geolocation을 부르면 헤드리스에서 멈춘다.
const geoMode = new URLSearchParams(location.search).get("geo");
if (geoMode) {
  const stub = {
    getCurrentPosition(ok, err) {
      if (geoMode === "ok") ok({ coords: { latitude: 36.9, longitude: 127.1, accuracy: 20 }, timestamp: Date.now() });
      else if (geoMode === "denied") err({ code: 1 });
      else err({ code: 3 }); // timeout
    },
  };
  Object.defineProperty(navigator, "geolocation", { value: stub, configurable: true });
}

const USER = {
  id: 1, // D-53. "나" 표시와 자기 삭제 금지가 이 값으로 갈린다
  display_name: "마찬영",
  email: "ma775100@gmail.com",
  is_admin: true,
  korail_linked: true,
  discord_linked: true,
  discord_enabled: true,
};

const PROPS = {
  Login: { onLoggedIn: () => {} },
  Settings: { user: USER, onBack: () => {}, onLoggedOut: () => {}, onUserChange: () => {} },
  Setup: { onCreated: () => {}, onOpenSettings: () => {} },
  SeatMatrix: {
    subscription: {
      id: 1, train_no: "1073", date: "2026-08-07", board_at: "수원", alight_at: "청량리",
      status: "STANDING",
    },
    onSubscriptionChange: () => {},
    onReset: () => {},
    onOpenSettings: () => {},
  },
};

const q = new URLSearchParams(location.search);
const skin = q.get("skin") === "web" ? web : ios;
const name = q.get("screen") || "Login";
const Screen = skin[name];

// `?click=sel1|sel2` — 하위 단계 화면(04 열차 선택, 05 지금 상태)을 보려면 조작이 필요하다.
// 헤드리스 스크린샷은 클릭을 못 하므로 하네스가 순서대로 눌러준다.
const clicks = (q.get("click") || "").split("|").filter(Boolean);
if (clicks.length) {
  let i = 0;
  const tick = () => {
    if (i >= clicks.length) return;
    document.querySelector(clicks[i++])?.click();
    setTimeout(tick, 120);
  };
  setTimeout(tick, 200);
}

// `?scroll=<px>` — 프레임을 그만큼 내린 상태로 찍는다. 고정 요소(내비바 sticky ·
// 액션 바 fixed)는 **스크롤해야 비로소 드러난다** — 맨 위에서는 흐름에 둔 것과 구분되지 않는다.
const scrollY = Number(q.get("scroll") || 0);
if (scrollY) {
  setTimeout(() => document.querySelector(".frame")?.scrollTo(0, scrollY), 300);
}

// 뷰포트에 흔들리지 않게 393×852 프레임을 좌상단에 고정한다
createRoot(document.getElementById("root")).render(
  <>
    <style>{skin.css}</style>
    {/* transform이 있으면 position:fixed가 뷰포트가 아니라 이 프레임을 기준으로 잡힌다 —
        시트(설정·역 검색·지금 상태)를 실기기와 같은 위치로 보려면 이게 필요하다.
        `?scroll`을 주면 프레임 자체가 스크롤 컨테이너가 되어 sticky도 여기에 걸린다 */}
    <style>{`html,body{margin:0;padding:0} .frame{width:393px;height:852px;overflow-x:hidden;overflow-y:${scrollY ? "auto" : "hidden"};position:absolute;top:0;left:0;transform:translateZ(0)} .frame > *{min-height:852px !important} .frame::-webkit-scrollbar{display:none}`}</style>
    <div className="frame">
      <Screen {...(PROPS[name] || {})} />
    </div>
  </>
);
