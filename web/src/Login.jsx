import { useState } from "react";
import { api } from "./api";
import { st } from "./styles";

// 최초 1회 로그인 후 세션 쿠키가 유지되므로 홈화면 앱에서 매번 로그인할 일은 없다 (PLAN 6절).
export default function Login({ onLoggedIn }) {
  const [mode, setMode] = useState("login"); // "login" | "signup" (첫 계정이거나 관리자가 가입을 열어둔 경우만 성공, D-24)
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  // 기본값 해제 — 보안 기본값은 안전한 쪽에 둔다 (D-23).
  // 내 폰 홈화면 앱에서는 한 번 체크해두면 30일 유지된다
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user =
        mode === "login"
          ? await api.login(email, password, remember)
          : await api.signup(email, password, displayName, remember);
      onLoggedIn(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ ...st.page, paddingTop: 48 }}>
      <div style={st.card}>
        <h1 style={st.h1}>ITX 좌석 매트릭스</h1>
        <p style={st.dim}>{mode === "login" ? "로그인" : "계정 만들기 (부트스트랩 1회)"}</p>

        <form onSubmit={submit}>
          <label style={st.label} htmlFor="email">이메일</label>
          <input
            id="email" style={st.input} type="email" value={email} autoComplete="username"
            onChange={(e) => setEmail(e.target.value)} required
          />

          <label style={st.label} htmlFor="password">비밀번호</label>
          <input
            id="password" style={st.input} type="password" value={password}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            onChange={(e) => setPassword(e.target.value)} required minLength={8}
          />

          {mode === "signup" && (
            <>
              <label style={st.label} htmlFor="display_name">표시 이름</label>
              <input
                id="display_name" style={st.input} value={displayName}
                onChange={(e) => setDisplayName(e.target.value)} required
              />
            </>
          )}

          <label
            htmlFor="remember"
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, fontSize: 13 }}
          >
            <input
              id="remember" type="checkbox" checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              style={{ width: 16, height: 16 }}
            />
            로그인 유지
            <span style={{ ...st.dim, fontSize: 11.5 }}>
              (해제하면 브라우저를 닫을 때 로그아웃)
            </span>
          </label>

          <button style={st.primaryBtn} type="submit" disabled={busy}>
            {busy ? "…" : mode === "login" ? "로그인" : "계정 만들기"}
          </button>
        </form>

        {error && <div style={st.error}>{error}</div>}

        <p style={{ ...st.dim, marginTop: 14, textAlign: "center" }}>
          <button
            style={{ ...st.ghostBtn, border: "none", background: "none", color: "#1a3a6b" }}
            onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(null); }}
          >
            {mode === "login" ? "계정 만들기" : "로그인으로"}
          </button>
        </p>
      </div>
    </div>
  );
}
