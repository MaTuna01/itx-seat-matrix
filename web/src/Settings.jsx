import { useEffect, useState } from "react";
import { api } from "./api";
import { st } from "./styles";

// 설정 화면 (PLAN 10절). 계정/가입 관리 + 코레일 연동 (Phase 2).
// 알림 기기·디스코드 웹훅은 Phase 3에서 여기에 붙는다.
export default function Settings({ user, onBack, onLoggedOut, onUserChange }) {
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

        <KorailLink user={user} onUserChange={onUserChange} setError={setError} />

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

// 코레일 계정 연결 (Phase 2 항목 C, D-22).
// 저장된 자격증명은 API가 절대 되돌려주지 않으므로(절대규칙 9) 화면도
// "연결됨/미연결"만 안다 — 아이디를 다시 보여줄 방법도, 그럴 이유도 없다.
function KorailLink({ user, onUserChange, setError }) {
  const [korailId, setKorailId] = useState("");
  const [korailPw, setKorailPw] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      onUserChange(await fn());
      setKorailId("");
      setKorailPw("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (user.korail_linked) {
    return (
      <>
        <label style={st.label}>코레일 계정</label>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ ...st.pill, ...st.pillGps }}>연결됨</span>
          <span style={{ ...st.dim, flex: 1 }}>좌석 조회에 이 계정을 씁니다.</span>
          <button
            style={st.ghostBtn}
            disabled={busy}
            onClick={() => run(api.unlinkKorail)}
          >
            {busy ? "…" : "해제"}
          </button>
        </div>
      </>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(() => api.linkKorail(korailId, korailPw));
      }}
    >
      <label style={st.label} htmlFor="korail_id">코레일 아이디 (회원번호 / 휴대폰번호)</label>
      <input
        id="korail_id"
        style={st.input}
        value={korailId}
        onChange={(e) => setKorailId(e.target.value)}
        // 앱 계정 정보가 자동완성으로 섞여 들어오면 조용히 틀린 값이 저장된다
        autoComplete="off"
        required
      />

      <label style={st.label} htmlFor="korail_pw">코레일 비밀번호</label>
      <input
        id="korail_pw"
        style={st.input}
        type="password"
        value={korailPw}
        onChange={(e) => setKorailPw(e.target.value)}
        autoComplete="new-password"
        required
      />

      <button style={{ ...st.primaryBtn, marginTop: 12 }} type="submit" disabled={busy}>
        {busy ? "…" : "코레일 계정 연결"}
      </button>
      <p style={{ ...st.dim, marginTop: 8 }}>
        암호화해서 저장하며 다시 표시되지 않습니다. 연결 시점에는 코레일에 접속하지
        않으므로, 아이디·비밀번호가 틀렸다면 첫 좌석 조회에서 드러납니다.
      </p>
    </form>
  );
}
