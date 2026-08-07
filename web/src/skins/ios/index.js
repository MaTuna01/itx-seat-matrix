// iOS 스킨 — iPhone 14 Pro 393×852pt. 피그마 `ios` 페이지가 설계본이다 (→ D-50).
//
// Phase 5(#25)에서 화면 단위로 채운다 — 낮은 위험 순서대로
// **01 로그인 → 10·11 설정 → 02·03·04 → 06·07 매트릭스.**
//
// 채워지지 않은 화면은 아래 전개(spread)로 web 스킨에 그대로 폴백한다. 그래서 화면을 하나
// 추가할 때마다 그 화면만 iOS로 바뀌고 나머지는 건드리지 않아도 된다.
// 폴백을 두지 않으면 "iOS 스킨을 만드는 동안 아이폰에서 앱이 반쪽이 되는" 기간이 생긴다.
//
// `css`는 **합친다** — 아직 web 화면이 섞여 있어서 그쪽 전역 스타일(.trainPulse, tr:active)이
// 여전히 필요하다. iOS 규칙이 뒤에 와서 이긴다. 전부 iOS로 바뀌면 web 쪽을 떼면 된다.

import web from "../web";
import Login from "./Login";
import Settings from "./Settings";
import Setup from "./Setup";
import { css as iosCss } from "./styles";

export default {
  ...web,
  css: web.css + iosCss,
  Login,
  Settings,
  Setup,
  // Phase 5 남은 화면: SeatMatrix, Loading, ErrorScreen
};
