import { useEffect, useState } from "react";
import { api } from "./api";
import { st } from "./styles";

// 설정 화면 (PLAN 10절). Phase 1에는 계정/가입 관리만 있다.
// 코레일 연동은 Phase 2, 알림 기기·디스코드 웹훅은 Phase 3에서 여기에 붙는다.
export default function Settings({ user, onBack, onLoggedOut }) {
  const [signupEnabled, setSignupEnabled] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user.is_admin) return;
    api.adminSettings()
      .then((s) => setSignupEnabled(s.signup_enabled))
      .catch((err) => setError(err.message));
  }, [user.is_admin]);

  const toggleSignup = async () => {
    setBusy(true);
    try {
      const next = await api.setSignupEnabled(!signupEnabled);
      setSignupEnabled(next.signup_enabled);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ ...st.page, paddingTop: 32 }}>
      <div style={st.card}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <h1 style={{ ...st.h1, flex: 1 }}>설정</h1>
          <button style={st.ghostBtn} onClick={onBack}>닫기</button>
        </div>

        <p style={{ ...st.dim, marginTop: 8 }}>
          {user.display_name} · {user.email}
          {user.is_admin && (
            <span style={{ ...st.pill, ...st.pillSeated, marginLeft: 6 }}>관리자</span>
          )}
        </p>

        {user.is_admin && (
          <>
            <label style={st.label}>회원가입 허용</label>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button
                onClick={toggleSignup}
                disabled={busy || signupEnabled === null}
                style={{
                  ...st.filterBtn,
                  background: signupEnabled ? "#1a3a6b" : "#fff",
                  color: signupEnabled ? "#fff" : "#1a3a6b",
                }}
              >
                {signupEnabled === null ? "…" : signupEnabled ? "열림" : "잠김"}
              </button>
              <span style={{ ...st.dim, flex: 1 }}>
                필요할 때만 잠깐 열고 바로 다시 잠그세요.
              </span>
            </div>
          </>
        )}

        <button
          style={{ ...st.primaryBtn, background: "#fff", color: "#c0392b", border: "1.5px solid #eab5ad" }}
          onClick={async () => {
            await api.logout();
            onLoggedOut();
          }}
        >
          로그아웃
        </button>

        {error && <div style={st.error}>{error}</div>}
      </div>
    </div>
  );
}
