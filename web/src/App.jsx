import { useCallback, useEffect, useState } from "react";
import { api, UnauthorizedError } from "./core/api";
import { resolveSkin } from "./core/skin";
import iosSkin from "./skins/ios";
import webSkin from "./skins/web";

const SKINS = { web: webSkin, ios: iosSkin };

// 스킨은 로드 시점에 한 번만 정해진다 — 실행 중에 기기가 바뀌지 않는다 (→ D-50).
// `?ui=ios` / `?ui=web` / `?ui=auto`로 강제할 수 있다.
const skin = SKINS[resolveSkin()] ?? webSkin;

// 알림 탭 딥링크 (D-20). service worker가 `/?sub=<id>`로 열어주면 그 구독을 띄운다 —
// 알림을 눌렀는데 홈이나 다른 열차가 뜨면 "앱을 열 시점을 알리는 장치"의 절반이 무용해진다.
function deepLinkedSubId() {
  const raw = new URLSearchParams(window.location.search).get("sub");
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

// 라우팅: 세션 확인 → (없으면) 로그인 → (활성 구독 없으면) 탑승 등록 → 매트릭스.
// 401은 어디서 나든 로그인 화면으로 되돌린다 (PLAN 6절).
//
// **이 파일은 스킨을 모른다.** 화면 5개를 스킨에서 받아 쓸 뿐이라, iOS가 탑승 등록을
// 네 단계로 쪼개든 web이 한 카드로 그리든 여기는 그대로다 — 하위 단계는 스킨 안의 상태다.
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
  return (
    <>
      <style>{skin.css}</style>
      {renderScreen()}
    </>
  );

  function renderScreen() {
    if (state.phase === "loading") return <skin.Loading />;

    if (state.phase === "error") {
      return <skin.ErrorScreen message={state.error} onRetry={bootstrap} />;
    }

    if (state.phase === "login") return <skin.Login onLoggedIn={bootstrap} />;

    if (state.phase === "settings") {
      return (
        <skin.Settings
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
        <skin.Setup
          onCreated={(subscription) => setState({ ...state, phase: "matrix", subscription })}
          onOpenSettings={openSettings}
        />
      );
    }

    return (
      <skin.SeatMatrix
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
