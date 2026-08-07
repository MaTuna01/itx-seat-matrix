// iOS 스킨 — iPhone 14 Pro 393×852pt. 피그마 `ios` 페이지가 설계본이다 (→ D-50).
//
// **11화면이 모두 채워졌다** (Phase 5, 이슈 #25). 더 이상 web으로 폴백하는 화면이 없다.
// 전개(`...web`)는 그대로 둔다 — 앞으로 web에 화면이 추가되면 iOS가 비는 것보다
// 폴백되는 편이 낫고, 이 파일이 "무엇이 iOS로 덮였는지"의 목록 역할을 한다.
//
// `css`는 아직 web + ios를 합친다. web 스킨의 전역 스타일 중 `.trainPulse`(진행바 펄스)를
// iOS 매트릭스도 쓰기 때문이다. 그 하나를 iOS 쪽으로 옮기면 web 부분을 뗄 수 있다.

import web from "../web";
import { ErrorScreen, Loading } from "./Boot";
import Login from "./Login";
import SeatMatrix from "./SeatMatrix";
import Settings from "./Settings";
import Setup from "./Setup";
import { css as iosCss } from "./styles";

export default {
  ...web,
  css: web.css + iosCss,
  Loading,
  ErrorScreen,
  Login,
  Setup,
  SeatMatrix,
  Settings,
};
