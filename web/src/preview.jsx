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
window.fetch = async (url) => {
  const path = String(url).split("?")[0];
  const hit = Object.keys(CANNED).find((k) => path.endsWith(k));
  return {
    ok: !!hit,
    status: hit ? 200 : 404,
    json: async () => (hit ? CANNED[hit] : { detail: "preview" }),
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

// 뷰포트에 흔들리지 않게 393×852 프레임을 좌상단에 고정한다
createRoot(document.getElementById("root")).render(
  <>
    <style>{skin.css}</style>
    {/* transform이 있으면 position:fixed가 뷰포트가 아니라 이 프레임을 기준으로 잡힌다 —
        시트(설정·역 검색·지금 상태)를 실기기와 같은 위치로 보려면 이게 필요하다 */}
    <style>{`html,body{margin:0;padding:0} .frame{width:393px;height:852px;overflow:hidden;position:absolute;top:0;left:0;transform:translateZ(0)} .frame > *{min-height:852px !important}`}</style>
    <div className="frame">
      <Screen {...(PROPS[name] || {})} />
    </div>
  </>
);
