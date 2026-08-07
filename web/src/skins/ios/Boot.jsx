import { st } from "./styles";

// 부팅 중 / 부팅 실패. 피그마 ios 페이지에는 별도 화면이 없다 — web 페이지의 01·02에
// 해당하는 순간이 iOS에서는 앱 실행 직후 잠깐이라 화면으로 그리지 않았기 때문이다.
// 그래도 코드에는 두 상태가 존재하므로 스킨 어휘로 최소한만 그린다.

export function Loading() {
  return (
    <div style={st.screen}>
      <div style={st.body}>
        <p style={{ ...st.subtitle, margin: 0 }}>불러오는 중…</p>
      </div>
    </div>
  );
}

export function ErrorScreen({ message, onRetry }) {
  return (
    <div style={st.screen}>
      <div style={st.body}>
        <p style={st.title}>연결할 수 없습니다</p>
        <p style={{ ...st.subtitle }}>{message}</p>
      </div>
      <div style={st.bottomBar}>
        <button style={st.primaryBtn} onClick={onRetry}>다시 시도</button>
      </div>
    </div>
  );
}
