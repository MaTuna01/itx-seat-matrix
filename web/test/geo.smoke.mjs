// core/geo.js 스모크 — `npm run smoke` (node 내장만, 의존성 없음).
//
// geo.js의 순수 함수는 두 스킨이 공유하는 위치 정책·문구 원천이라(format.js와 같은 이유,
// D-59) 여기가 틀리면 web과 iOS가 같이 틀린다. `navigator` 없이 순수 함수만 검증한다.

import {
  gpsParams,
  shouldAutoAcquire,
  classifyError,
  positionBadge,
} from "../src/core/geo.js";

let fail = 0;
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fail++;
  console.log(`${ok ? "ok  " : "FAIL"} ${name}\n       got=${JSON.stringify(got)}\n      want=${JSON.stringify(want)}`);
};

// 1. gpsParams — 넷 다 유한 숫자일 때만 4개, 아니면 {} (부분 전송 없음)
const fix = { lat: 36.8, lng: 127.1, accuracy_m: 20, fixed_at_ms: 1_700_000_000_000 };
eq("gpsParams 전부", gpsParams(fix), {
  lat: 36.8, lng: 127.1, gps_accuracy_m: 20, gps_fixed_at_ms: 1_700_000_000_000,
});
eq("gpsParams null → {}", gpsParams(null), {});
eq("gpsParams accuracy null → {} (절대 3개 안 보낸다)", gpsParams({ ...fix, accuracy_m: null }), {});
eq("gpsParams NaN → {}", gpsParams({ ...fix, lat: NaN }), {});
eq("gpsParams undefined 필드 → {}", gpsParams({ lat: 36.8, lng: 127.1 }), {});

// 2. shouldAutoAcquire — 진리표
const A = (o) => shouldAutoAcquire(o);
eq("미지원 → false", A({ supported: false, permission: "granted", optedIn: true, last: null }), false);
eq("denied → false", A({ supported: true, permission: "denied", optedIn: true, last: null }), false);
eq("granted → true", A({ supported: true, permission: "granted", optedIn: false, last: null }), true);
eq("optedIn → true", A({ supported: true, permission: "prompt", optedIn: true, last: null }), true);
eq("prompt+첫시도 → true", A({ supported: true, permission: "prompt", optedIn: false, last: null }), true);
eq("이 세션 거절 후 → false", A({ supported: true, permission: "prompt", optedIn: false, last: "denied" }), false);
eq("이 세션 무응답 후 → false", A({ supported: true, permission: "prompt", optedIn: false, last: "prompt" }), false);
eq("timeout 후 재시도 → true", A({ supported: true, permission: "unknown", optedIn: false, last: "timeout" }), true);

// 3. classifyError — code 1은 맥락으로 갈린다
eq("code1 자동 → prompt", classifyError(1, { permission: "unknown", viaTap: false }), "prompt");
eq("code1 탭 → denied", classifyError(1, { permission: "unknown", viaTap: true }), "denied");
eq("code1 권한 denied → denied", classifyError(1, { permission: "denied", viaTap: false }), "denied");
eq("code2 → unavailable", classifyError(2, {}), "unavailable");
eq("code3 → timeout", classifyError(3, {}), "timeout");

// 4. positionBadge — 상태별 문구
const B = (o) => positionBadge(o);
eq("gps 채택 → 사유 없음/탭 없음",
  B({ geoState: "ok", positionSource: "gps", positionNote: null, stale: false }),
  { gps: true, note: null, tappable: false });
eq("서버 거부 → position_note 그대로",
  B({ geoState: "ok", positionSource: "schedule", positionNote: "GPS 정확도 500m — 100m 초과", stale: false }),
  { gps: false, note: "GPS 정확도 500m — 100m 초과", tappable: false });
eq("acquiring → 확인 중",
  B({ geoState: "acquiring", positionSource: "schedule", positionNote: null, stale: false }),
  { gps: false, note: "GPS 확인 중…", tappable: false });
eq("prompt → 탭 가능",
  B({ geoState: "prompt", positionSource: "schedule", positionNote: null, stale: false }),
  { gps: false, note: "탭하면 위치 권한을 요청합니다", tappable: true });
eq("denied → 설정 안내 + 탭",
  B({ geoState: "denied", positionSource: "schedule", positionNote: null, stale: false }).tappable, true);
eq("unavailable → 탭 불가",
  B({ geoState: "unavailable", positionSource: "schedule", positionNote: null, stale: false }).tappable, false);
eq("stale(오프라인 캐시)면 위치 사유 억제",
  B({ geoState: "prompt", positionSource: "schedule", positionNote: "x", stale: true }),
  { gps: false, note: null, tappable: false });
eq("stale이어도 캐시가 gps면 gps 라벨 유지",
  B({ geoState: "idle", positionSource: "gps", positionNote: null, stale: true }).gps, true);

console.log(fail === 0 ? "\n전부 통과" : `\n${fail}건 실패`);
process.exit(fail === 0 ? 0 : 1);
