import { useEffect, useState } from "react";
import { describeUser, isDeletable } from "../../core/admin";
import { api } from "../../core/api";
import {
  guessDeviceLabel,
  pushBlockedReason,
  subscribeThisDevice,
  unsubscribeThisDevice,
} from "../../core/push";
import { st } from "./styles";

// 설정 화면 (PLAN 10절). 계정/가입 관리 + 코레일 연동 + 알림 기기·디스코드 (Phase 3).
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
        <PushDevices setError={setError} />
        <DiscordLink user={user} onUserChange={onUserChange} setError={setError} />

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
            <AdminUsers user={user} setError={setError} />
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

// 알림 기기 등록 (Phase 3 항목 E, D-9/D-20/D-21).
//
// ★ 권한 요청은 **버튼 탭 핸들러 안에서만** 일어난다. 화면이 뜰 때 자동으로 요청하면
// iOS에서 조용히 실패한다 — 예외도 프롬프트도 없다. 그래서 이 컴포넌트는 마운트 시
// 목록과 공개키만 읽고, 권한은 사용자가 누를 때까지 건드리지 않는다.
function PushDevices({ setError }) {
  const [devices, setDevices] = useState(null);
  const [vapidKey, setVapidKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const blocked = pushBlockedReason();

  const reload = () => api.pushDevices().then(setDevices).catch((e) => setError(e.message));

  useEffect(() => {
    api.pushConfig()
      .then((c) => setVapidKey(c.vapid_public_key))
      .catch((e) => setError(e.message));
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const enable = async () => {
    setBusy(true);
    setError(null);
    setTestResult(null);
    try {
      // 이 await 체인 전체가 탭 핸들러 안이다 (D-21)
      const subscription = await subscribeThisDevice(vapidKey);
      await api.registerPushDevice({ ...subscription, label: guessDeviceLabel() });
      await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    setBusy(true);
    try {
      await api.deletePushDevice(id);
      // 이 기기를 지웠을 수도 있으니 브라우저 구독도 함께 정리한다 —
      // 남겨두면 다시 켤 때 옛 endpoint가 그대로 살아 있어 상태가 어긋난다
      await unsubscribeThisDevice();
      await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setError(null);
    try {
      setTestResult(await api.pushTest());
      await reload(); // 410으로 정리된 기기가 있으면 목록에서 사라진다
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <label style={st.label}>알림 기기</label>

      {devices === null ? (
        <p style={st.dim}>불러오는 중…</p>
      ) : devices.length === 0 ? (
        <p style={{ ...st.dim, marginTop: 0 }}>등록된 기기가 없습니다. 알림이 오지 않습니다.</p>
      ) : (
        devices.map((d) => (
          <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <span style={{ ...st.pill, ...st.pillGps }}>{d.label || "기기"}</span>
            <span style={{ ...st.dim, flex: 1 }}>
              {new Date(d.created_at).toLocaleDateString("ko-KR")} 등록
            </span>
            <button style={st.ghostBtn} disabled={busy} onClick={() => remove(d.id)}>
              해제
            </button>
          </div>
        ))
      )}

      {blocked ? (
        <p style={{ ...st.dim, marginTop: 8 }}>{blocked}</p>
      ) : (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button style={{ ...st.primaryBtn, flex: 1, marginTop: 0 }} disabled={busy} onClick={enable}>
            {busy ? "…" : "이 기기에 알림 켜기"}
          </button>
          <button style={st.filterBtn} disabled={busy} onClick={test}>
            테스트 발송
          </button>
        </div>
      )}

      {testResult && (
        <p style={{ ...st.dim, marginTop: 8 }}>
          {testResult.sent > 0
            ? `${testResult.sent}대에 발송했습니다 · 폰에 알림이 떴는지 확인하세요`
            : "발송되지 않았습니다"}
          {testResult.errors.length > 0 && ` — ${testResult.errors.join(" · ")}`}
        </p>
      )}
    </>
  );
}

// 디스코드 웹훅 (Phase 3 항목 A, D-11).
// opt-in 2단계: ① 웹훅 연동 + ② 토글 on. 둘 다 켜야 발송된다.
// iOS 웹푸시가 미덥지 않을 때의 보완 채널이다 (D-9).
function DiscordLink({ user, onUserChange, setError }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      onUserChange(await fn());
      setUrl("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (user.discord_linked) {
    return (
      <>
        <label style={st.label}>디스코드 알림</label>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            disabled={busy}
            onClick={() => run(() => api.setDiscordEnabled(!user.discord_enabled))}
            style={{
              ...st.filterBtn,
              background: user.discord_enabled ? "#1a3a6b" : "#fff",
              color: user.discord_enabled ? "#fff" : "#1a3a6b",
            }}
          >
            {user.discord_enabled ? "켜짐" : "꺼짐"}
          </button>
          <span style={{ ...st.dim, flex: 1 }}>
            켜두면 웹푸시와 <b>함께</b> 발송됩니다.
          </span>
          <button style={st.ghostBtn} disabled={busy} onClick={() => run(api.unlinkDiscord)}>
            해제
          </button>
        </div>
      </>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(() => api.linkDiscord(url));
      }}
    >
      <label style={st.label} htmlFor="discord_url">
        디스코드 웹훅 URL (선택)
      </label>
      <input
        id="discord_url"
        style={st.input}
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://discord.com/api/webhooks/…"
        autoComplete="off"
      />
      <button style={{ ...st.primaryBtn, marginTop: 12 }} type="submit" disabled={busy || !url}>
        {busy ? "…" : "디스코드 연동"}
      </button>
      <p style={{ ...st.dim, marginTop: 8 }}>
        서버 채널 설정 → 연동 → 웹훅에서 URL을 만들어 붙여넣으세요. 저장할 때 테스트
        메시지를 한 건 보내 URL을 검증하며, 실패하면 저장하지 않습니다. URL은 암호화해
        저장하고 다시 표시되지 않습니다.
      </p>
    </form>
  );
}

// 관리자 사용자 관리 (D-53, 이슈 #54).
//
// 삭제는 **비밀번호 재입력을 거쳐야만** 실행된다. 목록에서 바로 지워지지 않고 한 행이
// "확인 모드"로 펼쳐지므로 잘못 누른 것을 되돌릴 자리가 한 번 생긴다.
// 자기 자신·관리자에는 버튼을 그리지 않지만 그건 편의일 뿐이고, 진짜 거절은 서버가 한다.
function AdminUsers({ user, setError }) {
  const [rows, setRows] = useState(null);
  const [pending, setPending] = useState(null); // 확인 모드로 펼친 행
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = () => api.adminUsers().then(setRows).catch((e) => setError(e.message));

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cancel = () => {
    setPending(null);
    setPassword("");
  };

  const confirm = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.deleteUser(pending.id, password);
      cancel();
      await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <label style={st.label}>가입한 사용자</label>
      {rows === null ? (
        <p style={st.dim}>불러오는 중…</p>
      ) : (
        rows.map((row) => (
          <div key={row.id} style={{ borderTop: "1px solid #f0f2f5", padding: "8px 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14 }}>
                  {row.display_name}
                  {row.is_admin && (
                    <span style={{ ...st.pill, ...st.pillSeated, marginLeft: 6 }}>관리자</span>
                  )}
                  {row.id === user.id && (
                    <span style={{ ...st.pill, ...st.pillEst, marginLeft: 6 }}>나</span>
                  )}
                </div>
                <div style={st.dim}>{row.email} · {describeUser(row)}</div>
              </div>
              {isDeletable(row, user) && pending?.id !== row.id && (
                <button
                  style={{ ...st.filterBtn, color: "#c0392b", borderColor: "#eab5ad" }}
                  onClick={() => { setPending(row); setPassword(""); }}
                >
                  삭제
                </button>
              )}
            </div>

            {pending?.id === row.id && (
              <form onSubmit={confirm} style={{ marginTop: 8 }}>
                <p style={{ ...st.dim, color: "#c0392b", margin: "0 0 6px" }}>
                  {row.email} 계정과 그 사람의 구독·알림 기기가 전부 사라집니다. 되돌릴 수 없습니다.
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    style={{ ...st.input, flex: 1 }}
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="확인을 위해 내 비밀번호"
                    autoComplete="current-password"
                    required
                    autoFocus
                  />
                  <button
                    type="submit"
                    style={{ ...st.filterBtn, background: "#c0392b", color: "#fff", borderColor: "#c0392b" }}
                    disabled={busy || !password}
                  >
                    {busy ? "…" : "삭제"}
                  </button>
                  <button type="button" style={st.filterBtn} onClick={cancel} disabled={busy}>
                    취소
                  </button>
                </div>
              </form>
            )}
          </div>
        ))
      )}
    </>
  );
}
