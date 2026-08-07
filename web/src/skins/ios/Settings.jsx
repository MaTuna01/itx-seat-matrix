import { useEffect, useState } from "react";
import { api } from "../../core/api";
import {
  guessDeviceLabel,
  pushBlockedReason,
  subscribeThisDevice,
  unsubscribeThisDevice,
} from "../../core/push";
import { st } from "./styles";

// 피그마 ios `30:172`(미연결) / `30:238`(연결됨). iOS에서는 **모달 시트**다.
//
// web 스킨과 동작이 완전히 같다 — 표현만 iOS 그룹 리스트로 옮겼다.
// 특히 **웹푸시 권한 요청은 탭 핸들러 안에서만** 일어나야 한다 (D-21). 그 체인을
// 건드리지 않았다.

const Group = ({ children }) => <div style={st.group}>{children}</div>;

// 그룹 안의 행 사이 구분선. 마지막 행 뒤에는 넣지 않는다
const rowsWithSeps = (rows) =>
  rows.filter(Boolean).flatMap((r, i) => (i === 0 ? [r] : [<div key={`s${i}`} style={st.sep} />, r]));

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
    <div style={st.screen}>
      <div style={st.sheetBackdrop} onClick={onBack} />
      <div style={st.sheet} role="dialog" aria-label="설정">
        <div style={st.grabber} />
        <div style={st.sheetBar}>
          <span style={{ minWidth: 56 }} />
          <span style={st.sheetTitle}>설정</span>
          <button style={{ ...st.sheetAction, textAlign: "right" }} onClick={onBack}>완료</button>
        </div>

        <div style={st.sheetBody}>
          <p style={st.sectionLabel}>계정</p>
          <Group>
            {rowsWithSeps([
              <div key="who" style={st.row}>
                <span style={st.rowLabel}>{user.display_name}</span>
                <span style={st.rowValue}>{user.email}</span>
              </div>,
              user.is_admin && (
                <div key="admin" style={st.row}>
                  <span style={st.rowLabel}>권한</span>
                  <span style={{ ...st.chip, ...st.chipNavy }}>관리자</span>
                </div>
              ),
            ])}
          </Group>

          <KorailLink user={user} onUserChange={onUserChange} setError={setError} />
          <PushDevices setError={setError} />
          <DiscordLink user={user} onUserChange={onUserChange} setError={setError} />

          {user.is_admin && (
            <>
              <p style={st.sectionLabel}>관리자</p>
              <Group>
                <label className="iosRow" style={st.row} htmlFor="signup_enabled">
                  <span style={st.rowLabel}>회원가입 허용</span>
                  <input
                    id="signup_enabled" className="iosSwitch" type="checkbox"
                    checked={!!signupEnabled} disabled={busy || signupEnabled === null}
                    onChange={toggleSignup}
                  />
                </label>
              </Group>
              <p style={st.footnote}>필요할 때만 잠깐 열고 바로 다시 잠그세요.</p>
            </>
          )}

          <div style={{ ...st.group, marginTop: 24 }}>
            <button
              style={{ ...st.actionRow, ...st.destructiveRow }}
              onClick={async () => {
                await api.logout();
                onLoggedOut();
              }}
            >
              로그아웃
            </button>
          </div>

          {error && <p style={st.footnoteError}>{error}</p>}
        </div>
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
        <p style={st.sectionLabel}>좌석 조회</p>
        <Group>
          {rowsWithSeps([
            <div key="state" style={st.row}>
              <span style={st.rowLabel}>코레일 계정</span>
              <span style={{ ...st.chip, ...st.chipOK }}>연결됨</span>
            </div>,
            <button key="unlink" style={{ ...st.actionRow, ...st.destructiveRow }}
              disabled={busy} onClick={() => run(api.unlinkKorail)}>
              {busy ? "…" : "연결 해제"}
            </button>,
          ])}
        </Group>
        <p style={st.footnote}>좌석 조회에 이 계정을 씁니다. 해제하면 조회가 멈춥니다.</p>
      </>
    );
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); run(() => api.linkKorail(korailId, korailPw)); }}>
      <p style={st.sectionLabel}>좌석 조회 (필수)</p>
      <Group>
        {rowsWithSeps([
          <div key="id" style={st.fieldRow}>
            <label style={st.fieldLabel} htmlFor="korail_id">아이디</label>
            <input
              id="korail_id" style={st.fieldInput} value={korailId}
              onChange={(e) => setKorailId(e.target.value)}
              placeholder="회원번호 / 휴대폰번호"
              // 앱 계정 정보가 자동완성으로 섞여 들어오면 조용히 틀린 값이 저장된다
              autoComplete="off" required
            />
          </div>,
          <div key="pw" style={st.fieldRow}>
            <label style={st.fieldLabel} htmlFor="korail_pw">비밀번호</label>
            <input
              id="korail_pw" style={st.fieldInput} type="password" value={korailPw}
              onChange={(e) => setKorailPw(e.target.value)} autoComplete="new-password" required
            />
          </div>,
          <button key="link" type="submit" style={st.actionRow} disabled={busy}>
            {busy ? "…" : "코레일 계정 연결"}
          </button>,
        ])}
      </Group>
      <p style={st.footnote}>
        암호화해 저장하며 다시 표시되지 않습니다. 연결 시점에는 코레일에 접속하지 않으므로,
        아이디·비밀번호가 틀렸다면 첫 좌석 조회에서 드러납니다.
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

  const deviceRows =
    devices === null
      ? [<div key="loading" style={st.row}><span style={st.rowValue}>불러오는 중…</span></div>]
      : devices.length === 0
      ? [
          <div key="empty" style={st.row}>
            <span style={st.rowLabel}>알림 기기</span>
            <span style={st.rowValue}>없음</span>
          </div>,
        ]
      : devices.map((d) => (
          <div key={d.id} style={st.row}>
            <span style={st.rowLabel}>{d.label || "기기"}</span>
            <span style={st.rowValue}>
              {new Date(d.created_at).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })}
            </span>
            <button style={st.rowBtn} disabled={busy} onClick={() => remove(d.id)}>해제</button>
          </div>
        ));

  return (
    <>
      <p style={st.sectionLabel}>알림 기기</p>
      <Group>
        {rowsWithSeps([
          ...deviceRows,
          !blocked && (
            <button key="enable" style={st.actionRow} disabled={busy} onClick={enable}>
              {busy ? "…" : "이 기기에 알림 켜기"}
            </button>
          ),
          !blocked && (
            <button key="test" style={st.actionRow} disabled={busy} onClick={test}>테스트 발송</button>
          ),
        ])}
      </Group>
      {blocked ? (
        <p style={st.footnoteWarn}>{blocked}</p>
      ) : (
        <p style={st.footnote}>
          등록된 기기가 없으면 알림이 오지 않습니다. 권한 요청은 이 버튼을 눌렀을 때만 뜹니다.
        </p>
      )}
      {testResult && (
        <p style={st.footnote}>
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
        <p style={st.sectionLabel}>보조 채널</p>
        <Group>
          {rowsWithSeps([
            <label key="toggle" className="iosRow" style={st.row} htmlFor="discord_enabled">
              <span style={st.rowLabel}>디스코드 알림</span>
              <input
                id="discord_enabled" className="iosSwitch" type="checkbox"
                checked={!!user.discord_enabled} disabled={busy}
                onChange={() => run(() => api.setDiscordEnabled(!user.discord_enabled))}
              />
            </label>,
            <button key="unlink" style={{ ...st.actionRow, ...st.destructiveRow }}
              disabled={busy} onClick={() => run(api.unlinkDiscord)}>
              연결 해제
            </button>,
          ])}
        </Group>
        <p style={st.footnote}>켜두면 웹푸시와 함께 발송됩니다.</p>
      </>
    );
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); run(() => api.linkDiscord(url)); }}>
      <p style={st.sectionLabel}>보조 채널 (선택)</p>
      <Group>
        {rowsWithSeps([
          <div key="url" style={st.fieldRow}>
            <label style={st.fieldLabel} htmlFor="discord_url">웹훅 URL</label>
            <input
              id="discord_url" style={st.fieldInput} value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://discord.com/api/webhooks/…" autoComplete="off"
            />
          </div>,
          <button key="link" type="submit" style={st.actionRow} disabled={busy || !url}>
            {busy ? "…" : "디스코드 연동"}
          </button>,
        ])}
      </Group>
      <p style={st.footnote}>
        서버 채널 설정 → 연동 → 웹훅에서 URL을 만들어 붙여넣으세요. 저장할 때 테스트 메시지를
        한 건 보내 URL을 검증하며, 실패하면 저장하지 않습니다. URL은 암호화해 저장하고 다시
        표시되지 않습니다.
      </p>
    </form>
  );
}
