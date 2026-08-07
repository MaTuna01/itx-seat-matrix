// 임시 프리뷰 — 백엔드 없이 스킨 화면 하나만 렌더한다. 커밋하지 않는다.
import { createRoot } from "react-dom/client";
import ios from "./skins/ios";

const which = new URLSearchParams(location.search).get("screen") || "Login";
const Screen = ios[which];

// 뷰포트에 흔들리지 않게 393×852 프레임을 좌상단에 고정한다
createRoot(document.getElementById("root")).render(
  <>
    <style>{ios.css}</style>
    <style>{`html,body{margin:0;padding:0} .frame{width:393px;height:852px;overflow:hidden;position:absolute;top:0;left:0} .frame > *{min-height:852px !important}`}</style>
    <div className="frame">
      <Screen onLoggedIn={() => {}} />
    </div>
  </>
);
