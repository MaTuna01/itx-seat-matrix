// core/format.js 스모크 — `npm run smoke` (node 내장만 쓴다, 의존성 없음).
//
// 프론트 자동 테스트가 0개인데(PLAN 13절) format.js는 **두 스킨이 공유하는 유일한 문구
// 원천**이라 여기가 틀리면 web과 iOS가 같이 틀린다. 판정 분기 전부를 문자열로 고정해 둔다.
// 문구를 고칠 때는 이 파일도 함께 고쳐야 한다 — 그게 이 파일의 목적이다.
//
// CI에는 아직 붙어 있지 않다 (test 잡이 파이썬 전용). 붙이는 것은 별도 판단이다.

import { summarize, buildRows, failureSummary, seatWindow } from "../src/core/format.js";
import { skinForDevice } from "../src/core/skin.js";

const stops = ["수원", "안양", "영등포", "용산", "청량리"];
const txt = (segs) => segs.map((s) => s.t).join("");
let fail = 0;
const eq = (name, got, want) => {
  const ok = got === want;
  if (!ok) fail++;
  console.log(`${ok ? "ok  " : "FAIL"} ${name}\n       got=${JSON.stringify(got)}\n      want=${JSON.stringify(want)}`);
};

const rec = (car, no, from, until, all) =>
  ({ car, seat_no: no, clear_from_idx: from, clear_until_idx: until, clear_all: all });
const base = { alight_at: "청량리", sub_status: "STANDING", my_car: 3, my_seat_no: "7A" };

// 1. 입석 · 지금 앉을 수 있다 + 지연도 있다
let s = summarize({
  stops, startIdx: 0, data: { ...base },
  verdict: { move_to: [rec(4, "12C", 0, 4, true)], move_to_later: [rec(1, "2B", 2, 4, true)],
             all_sold_after_current: false, decision_needed: true },
});
eq("입석/bestMove 상태", s.status.text, "수원부터 착석 가능");
eq("입석/bestMove 본문", txt(s.detail),
   '추천 4호차 12C (청량리까지 빈 좌석) · 좌석을 선택해 "이 자리에 앉음"을 누르면 이후 알림이 그 자리 기준으로 옵니다');
eq("지연 접두어(move_to 있음)", s.later.label, "지금은 아니지만 뒤 구간에 빈 자리");
eq("지연 목록", s.later.seats, "1-2B(영등포부터 청량리까지)");

// 2. 입석 · 지금은 못 앉는다 (퇴근길 모양)
s = summarize({
  stops, startIdx: 0, data: { ...base },
  verdict: { move_to: [], move_to_later: [rec(4, "1A", 0, 4, true), rec(4, "1B", 1, 4, true)],
             all_sold_after_current: false, decision_needed: true },
});
eq("입석/laterOnly 상태", s.status.text, "수원부터 착석 가능");
eq("입석/laterOnly 톤", s.status.tone, "warn");
eq("지연 접두어(move_to 없음)", s.later.label, "빈 자리");
eq("지연 목록 2건", s.later.seats, "4-1A(수원부터 청량리까지), 4-1B(안양부터 청량리까지)");

// 3. 착석 · 내 자리 팔림 + 지금 옮길 곳 없음
s = summarize({
  stops, startIdx: 1, data: { ...base, sub_status: "SEATED" },
  verdict: { move_to: [], move_to_later: [rec(4, "12C", 2, 4, true)], my_seat_status: "SOLD_FROM",
             my_seat_sold_from: "용산", all_sold_after_current: false, decision_needed: true },
});
eq("착석 칩", s.chip.text, "내 자리 3호차 7A");
eq("착석 상태", s.status.text, "용산부터 판매됨");
eq("착석/laterOnly 본문", txt(s.detail), "지금 옮길 자리는 없음 · 영등포부터 4호차 12C (영등포부터 청량리까지)");
eq("일어남 버튼", s.showStandButton, true);

// 4. 매진 → 환승 권유 (D-45: 이때만)
s = summarize({
  stops, startIdx: 0, data: { ...base },
  verdict: { move_to: [], move_to_later: [], all_sold_after_current: true, decision_needed: true },
});
eq("매진 본문", txt(s.detail), "남은 구간 잔여 좌석 없음 · 지하철 환승이 나을 수 있음");
eq("매진이면 지연 목록 없음", s.later, null);

// 5. 판단 불필요 (D-47)
s = summarize({
  stops, startIdx: 3, data: { ...base },
  verdict: { move_to: [], move_to_later: [], all_sold_after_current: false, decision_needed: false },
});
eq("판단 불필요 · 매트릭스 숨김", s.showMatrix, false);
eq("판단 불필요 상태", s.status.text, "곧 청량리 도착");

// 6. 조회 실패 (D-48) — ⚠ 글리프는 core가 붙이지 않는다
eq("실패 요약", txt(failureSummary(new Set([1, 2]), stops)),
   "안양→영등포, 영등포→용산 구간 조회 실패 · 그 구간은 매진이 아니라 알 수 없음입니다");
eq("실패 없으면 null", failureSummary(new Set(), stops), null);

// 7. 행 순서 (D-49)
const seat = (car, no, cells) => ({ car, seat_no: no, cells });
const seats = [
  seat(4, "12C", [false, false, false, false]),   // 끝까지 빈다
  seat(3, "7A", [false, false, false, true]),     // 내 자리 (용산부터 판매)
  seat(3, "9C", [true, true, true, true]),        // 전 구간 매진
];
let r = buildRows({ seats, startIdx: 0, alightIdx: 4, seated: true, myCar: 3, myKey: "3-7A", onlyClear: false });
eq("내 자리가 1행", r.rows[0].key, "3-7A");
eq("myPinned", r.myPinned, true);
r = buildRows({ seats, startIdx: 0, alightIdx: 4, seated: true, myCar: 3, myKey: "3-7A", onlyClear: true });
eq("필터를 켜도 내 자리는 남는다", r.rows.map((x) => x.key).join(","), "3-7A,4-12C");
r = buildRows({ seats, startIdx: 0, alightIdx: 4, seated: false, myCar: null, myKey: null, onlyClear: false });
eq("입석이면 고정 없음", r.myPinned, false);
eq("입석 1행 = 가장 오래 앉는 좌석", r.rows[0].key, "4-12C");
r = buildRows({ seats, startIdx: 0, alightIdx: 4, seated: true, myCar: 3, myKey: "3-없음", onlyClear: false });
eq("내 좌석이 매트릭스에 없으면 조용히 통과 (D-18)", r.myPinned, false);

// 8. 선택한 좌석의 구간 문구 (→ D-52 ⑥)
// 실기기에서 발견한 버그: 지금 팔린 좌석에 "{탑승역}까지 빈 좌석"이라는 **길이 0인 구간**이
// 찍혔다. 같은 화면의 판정 카드는 그 좌석을 "조치원부터 서대전까지"로 맞게 말하고 있었다.
const win = (cells, startIdx = 0) => txt(seatWindow({ cells }, { stops, startIdx, alightIdx: 4 }));
eq("끝까지 빈 좌석", win([false, false, false, false]), "청량리까지 빈 좌석");
eq("도중까지 빈 좌석", win([false, false, true, true]), "영등포까지 빈 좌석");
eq("★ 지금 팔렸고 뒤에 빈다", win([true, true, false, false]), "지금은 빈 자리가 아님 · 영등포부터 청량리까지");
eq("지금 팔렸고 중간만 빈다", win([true, false, false, true]), "지금은 빈 자리가 아님 · 안양부터 용산까지");
eq("한 구간만 비어도 말한다", win([true, true, true, false]), "지금은 빈 자리가 아님 · 용산부터 청량리까지");
eq("남은 구간 전부 팔림", win([true, true, true, true]), "남은 구간 전부 판매됨");
// 실효 시작이 뒤로 밀린 경우 — 지나온 구간의 판매 여부는 문구에 끼어들면 안 된다 (D-18/D-47)
eq("실효 시작 뒤에서 시작", win([true, false, true, false], 2), "지금은 빈 자리가 아님 · 용산부터 청량리까지");
eq("실효 시작부터 비면 그냥 빈 좌석", win([true, true, false, false], 2), "청량리까지 빈 좌석");

// 9. 스킨 판별 (D-50) — 기준은 "iOS 기기냐 아니냐"다. 맥이냐 아니냐가 아니다.
const UA = {
  winChrome: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
  linux: "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
  android: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  iphonePwa: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
};
eq("윈도우 크롬 → web", skinForDevice(UA.winChrome, 0), "web");
eq("터치 윈도우 노트북 → web (오검출 방지)", skinForDevice(UA.winChrome, 10), "web");
eq("맥 → web", skinForDevice(UA.mac, 0), "web");
eq("리눅스 → web", skinForDevice(UA.linux, 0), "web");
eq("안드로이드 폰 → web (480px가 곧 폰 폭이다)", skinForDevice(UA.android, 5), "web");
eq("아이폰 → ios", skinForDevice(UA.iphone, 5), "ios");
eq("아이폰 홈화면 PWA → ios", skinForDevice(UA.iphonePwa, 5), "ios");
eq("아이패드(맥 UA 위장) → ios", skinForDevice(UA.mac, 5), "ios");

console.log(fail === 0 ? "\n전부 통과" : `\n${fail}건 실패`);
process.exit(fail === 0 ? 0 : 1);
