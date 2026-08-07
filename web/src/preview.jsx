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
  "/api/push/config": { vapid_public_key: "preview" },
  "/api/push/devices": [
    { id: 1, label: "iPhone · Safari", created_at: "2026-07-28T09:00:00+09:00" },
    { id: 2, label: "Mac · Chrome", created_at: "2026-08-02T09:00:00+09:00" },
  ],
  "/api/stations": ["수원", "안양", "영등포", "용산", "청량리", "천안", "평택"].map((name) => ({ name })),
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
  position_source: "timetable", delay_minutes: null, failed_seg_idxs: [],
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

// `?state=long` — 정차역이 많은 노선. 393pt 안에 구간 열이 몇 개까지 들어가는지 보려면
// 5개짜리 기본 픽스처로는 부족하다 (실기기에서 헤더가 뭉개진 것이 여기서 재현된다).
// 좌석도 넉넉히 둬서 문서가 스크롤되게 만든다 — 고정 액션 바를 확인하려면 필요하다.
// 실기기에서 깨진 그 노선이다 (IMG_8311). 구간 11개 + **네 글자 역**(`창원중앙`)이 함께 있다.
const LONG_STOPS = [
  "창원", "창원중앙", "진영", "밀양", "동대구", "대구", "구미", "김천", "영동", "대전", "천안", "수원",
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

const mode = new URLSearchParams(location.search).get("state");
const seatedMode = mode === "seated";

window.fetch = async (url) => {
  const path = String(url).split("?")[0];
  const hit = Object.keys(CANNED).find((k) => path.endsWith(k));
  const matrix = seatedMode ? SEATED_MATRIX : mode === "long" ? LONG_MATRIX : CANNED["/matrix"];
  const body = hit === "/matrix" ? matrix : hit && CANNED[hit];
  return {
    ok: !!hit,
    status: hit ? 200 : 404,
    json: async () => (hit ? body : { detail: "preview" }),
  };
};

const USER = {
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
