// web 스킨 — 480px 폭, 마우스 기준. 맥 브라우저의 기본값이자 개발·디버깅 경로다 (→ D-50).
//
// **"동결"이 아니라 "기능 패리티 유지"다.** 동결이라고 부르는 순간 조용히 썩고, 정작
// 맥에서 디버깅할 때 못 쓰게 된다. 기능이 늘면 여기도 최소한으로 배선한다.

import { Loading, ErrorScreen } from "./Boot";
import Login from "./Login";
import SeatMatrix from "./SeatMatrix";
import Settings from "./Settings";
import Setup from "./Setup";
import { css } from "./styles";

export default { css, Loading, ErrorScreen, Login, Setup, SeatMatrix, Settings };
