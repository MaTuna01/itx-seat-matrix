import { useState } from "react";
import { api } from "../../core/api";
import { st } from "./styles";

// 피그마 ios `21:2` (01 로그인). 계정 만들기는 별도 화면이 아니라 이 화면의 모드다 —
// web 스킨은 04 계정 만들기를 따로 뒀지만 iOS는 하단 링크로 접었다.
//
// 최초 1회 로그인 후 세션 쿠키가 유지되므로 홈화면 앱에서 매번 로그인할 일은 없다 (PLAN 6절).
export default function Login({ onLoggedIn }) {
  const [mode, setMode] = useState("login"); // "login" | "signup" (첫 계정이거나 관리자가 가입을 열어둔 경우만 성공, D-24)
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  // 기본값 해제 — 보안 기본값은 안전한 쪽에 둔다 (D-23).
  // 내 폰 홈화면 앱에서는 한 번 켜두면 30일 유지된다
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const signup = mode === "signup";

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = signup
        ? await api.signup(email, password, displayName, remember)
        : await api.login(email, password, remember);
      onLoggedIn(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form style={st.screen} onSubmit={submit}>
      <div style={st.body}>
        <h1 style={st.title}>코레일 좌석<br />매트릭스</h1>
        <p style={st.subtitle}>
          {signup ? "계정 만들기 (부트스트랩 1회)" : "통근 열차 자유석 좌석을 구간별로 확인합니다"}
        </p>

        <div style={st.group}>
          <div style={st.fieldRow}>
            <label style={st.fieldLabel} htmlFor="email">이메일</label>
            <input
              id="email" style={st.fieldInput} type="email" value={email}
              autoComplete="username" inputMode="email" placeholder="you@example.com"
              onChange={(e) => setEmail(e.target.value)} required
            />
          </div>
          <div style={st.sep} />
          <div style={st.fieldRow}>
            <label style={st.fieldLabel} htmlFor="password">비밀번호</label>
            <input
              id="password" style={st.fieldInput} type="password" value={password}
              autoComplete={signup ? "new-password" : "current-password"}
              onChange={(e) => setPassword(e.target.value)} required minLength={8}
            />
          </div>
          {signup && (
            <>
              <div style={st.sep} />
              <div style={st.fieldRow}>
                <label style={st.fieldLabel} htmlFor="display_name">표시 이름</label>
                <input
                  id="display_name" style={st.fieldInput} value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)} required
                />
              </div>
            </>
          )}
        </div>

        <div style={st.group}>
          {/* 행 전체가 탭 타깃이다 — 스위치만 51×31이면 최소 44pt 규칙에 못 미친다 */}
          <label className="iosRow" style={st.listRow} htmlFor="remember">
            <span style={st.listLabel}>로그인 유지</span>
            <input
              id="remember" className="iosSwitch" type="checkbox" checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
          </label>
        </div>
        <p style={st.note}>
          해제하면 브라우저를 닫을 때 로그아웃됩니다. 홈 화면에 추가한 앱에서는 한 번 켜두면 30일 유지됩니다.
        </p>

        {error && <p style={st.errorNote}>{error}</p>}
      </div>

      <div style={st.bottomBar}>
        <button
          type="button" style={st.linkBtn}
          onClick={() => { setMode(signup ? "login" : "signup"); setError(null); }}
        >
          {signup ? "로그인으로" : "계정 만들기"}
        </button>
        <button type="submit" style={st.primaryBtn} disabled={busy}>
          {busy ? "…" : signup ? "계정 만들기" : "로그인"}
        </button>
      </div>
    </form>
  );
}
