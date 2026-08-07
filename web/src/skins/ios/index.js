// iOS 스킨 — iPhone 14 Pro 393×852pt. 피그마 `ios` 페이지가 설계본이다 (→ D-50).
//
// **아직 비어 있다.** Phase 5(#25)에서 화면 단위로 채운다 — 낮은 위험 순서대로
// 01 로그인 → 10·11 설정 → 02·03·04 → 06·07 매트릭스.
//
// 채워지지 않은 화면은 아래 전개(spread)로 web 스킨에 그대로 폴백한다. 그래서 이 파일에
// 화면을 하나 추가할 때마다 그 화면만 iOS로 바뀌고 나머지는 건드리지 않아도 된다.
// 폴백을 두지 않으면 "iOS 스킨을 만드는 동안 아이폰에서 앱이 반쪽이 되는" 기간이 생긴다.

import web from "../web";

export default {
  ...web,
  // Phase 5에서 여기에 하나씩 추가한다:
  // Login, Setup, SeatMatrix, Settings, Loading, ErrorScreen, css
};
