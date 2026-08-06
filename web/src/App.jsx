import { useCallback, useEffect, useState } from "react";
import { api, UnauthorizedError } from "./api";
import Login from "./Login";
import SeatMatrix from "./SeatMatrix";
import Settings from "./Settings";
import Setup from "./Setup";
import { css, st } from "./styles";

// 알림 탭 딥링크 (D-20). service worker가 `/?sub=<id>`로 열어주면 그 구독을 띄운다 —
// 알림을 눌렀는데 홈이나 다른 열차가 뜨면 "앱을 열 시점을 알리는 장치"의 절반이 무용해진다.
function deepLinkedSubId() {
  const raw = new URLSearchParams(window.location.search).get("sub");
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

// 라우팅: 세션 확인 → (없으면) 로그인 → (활성 구독 없으면) 탑승 등록 → 매트릭스.
// 401은 어디서 나든 로그인 화면으로 되돌린다 (PLAN 6절).
export default function App() {
  const [state, setState] = useState({ phase: "loading" });

  const bootstrap = useCallback(async () => {
    try {
      const user = await api.me();
      const subs = await api.subscriptions();
      const wanted = deepLinkedSubId();
      // 딥링크가 가리키는 구독이 이미 만료됐으면(하차 후 알림을 늦게 봤을 때)
      // 조용히 최신 구독으로 떨어진다 — 빈 화면보다 낫다
      const subscription = subs.find((s) => s.id === wanted) ?? subs[0] ?? null;
      setState({ phase: subscription ? "matrix" : "setup", user, subscription });
    } catch (err) {
      if (err instanceof UnauthorizedError) setState({ phase: "login" });
      else setState({ phase: "error", error: err.message });
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  const guard = (fn) => async (...args) => {
    try {
      await fn(...args);
    } catch (err) {
      if (err instanceof UnauthorizedError) setState({ phase: "login" });
      else throw err;
    }
  };

  const openSettings = () => setState({ ...state, phase: "settings", from: state.phase });

  // 전역 리셋(box-sizing 등)은 모든 화면에 한 번만 주입한다 —
  // 매트릭스 화면에서만 주입하면 폼 화면의 input이 padding만큼 넘친다
  const screen = renderScreen();
  return (
    <>
      <style>{css}</style>
      {screen}
    </>
  );

  function renderScreen() {
  if (state.phase === "loading") {
    return <div style={{ ...st.page, paddingTop: 48 }}><p style={st.dim}>불러오는 중…</p></div>;
  }

  if (state.phase === "error") {
    return (
      <div style={{ ...st.page, paddingTop: 48 }}>
        <div style={st.card}>
          <p style={st.error}>{state.error}</p>
          <button style={st.primaryBtn} onClick={bootstrap}>다시 시도</button>
        </div>
      </div>
    );
  }

  if (state.phase === "login") return <Login onLoggedIn={bootstrap} />;

  if (state.phase === "settings") {
    return (
      <Settings
        user={state.user}
        onBack={() => setState({ ...state, phase: state.from ?? "setup" })}
        onLoggedOut={() => setState({ phase: "login" })}
        // 코레일 연결/해제는 MeOut을 돌려준다 — korail_linked 표시를 즉시 갱신한다
        onUserChange={(user) => setState((s) => ({ ...s, user }))}
      />
    );
  }

  if (state.phase === "setup") {
    return (
      <Setup
        onCreated={(subscription) => setState({ ...state, phase: "matrix", subscription })}
        onOpenSettings={openSettings}
      />
    );
  }

  return (
    <SeatMatrix
      subscription={state.subscription}
      onSubscriptionChange={(subscription) => setState({ ...state, subscription })}
      onOpenSettings={openSettings}
      onReset={guard(async () => {
        await api.deleteSubscription(state.subscription.id);
        setState({ ...state, phase: "setup", subscription: null });
      })}
    />
  );
  }
}
