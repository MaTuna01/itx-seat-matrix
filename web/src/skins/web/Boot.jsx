import { st } from "./styles";

// 부팅 중 화면과 부팅 실패 화면 (피그마 web 페이지의 01·02).
// App.jsx가 인라인으로 갖고 있던 것을 스킨으로 내렸다 — 이 두 화면도 스킨마다 다르게 생겼다.

export function Loading() {
  return (
    <div style={{ ...st.page, paddingTop: 48 }}>
      <p style={st.dim}>불러오는 중…</p>
    </div>
  );
}

export function ErrorScreen({ message, onRetry }) {
  return (
    <div style={{ ...st.page, paddingTop: 48 }}>
      <div style={st.card}>
        <p style={st.error}>{message}</p>
        <button style={st.primaryBtn} onClick={onRetry}>다시 시도</button>
      </div>
    </div>
  );
}
