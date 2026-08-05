import { useCallback, useEffect, useState } from "react";
import { api, UnauthorizedError } from "./api";
import Login from "./Login";
import SeatMatrix from "./SeatMatrix";
import Setup from "./Setup";
import { st } from "./styles";

// 라우팅: 세션 확인 → (없으면) 로그인 → (활성 구독 없으면) 탑승 등록 → 매트릭스.
// 401은 어디서 나든 로그인 화면으로 되돌린다 (PLAN 6절).
export default function App() {
  const [state, setState] = useState({ phase: "loading" });

  const bootstrap = useCallback(async () => {
    try {
      const user = await api.me();
      const subs = await api.subscriptions();
      setState({ phase: subs.length ? "matrix" : "setup", user, subscription: subs[0] ?? null });
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

  if (state.phase === "setup") {
    return (
      <Setup
        onCreated={(subscription) =>
          setState({ ...state, phase: "matrix", subscription })
        }
      />
    );
  }

  return (
    <SeatMatrix
      subscription={state.subscription}
      onSubscriptionChange={(subscription) => setState({ ...state, subscription })}
      onReset={guard(async () => {
        await api.deleteSubscription(state.subscription.id);
        setState({ ...state, phase: "setup", subscription: null });
      })}
    />
  );
}
