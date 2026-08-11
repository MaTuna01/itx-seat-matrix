// 프로토타입(seat-matrix.jsx)의 인라인 스타일을 그대로 옮긴 것. 바닐라 CSS 유지 (PLAN 10절).

export const css = `
  * { box-sizing: border-box; }
  body { margin: 0; background: #f7f8fa; }
  .trainPulse {
    position:absolute; top:-3px; left:50%; transform:translateX(-50%);
    width:14px; height:14px; border-radius:50%;
    background:rgba(26,58,107,.25); animation:pulse 1.6s infinite;
  }
  @keyframes pulse {
    0% { transform:translateX(-50%) scale(.7); opacity:.9; }
    100% { transform:translateX(-50%) scale(2); opacity:0; }
  }
  @media (prefers-reduced-motion: reduce) { .trainPulse { animation:none; } }
  tr:active { background:#eef3fb !important; }
`;

export const st = {
  page: {
    fontFamily: '-apple-system, "Apple SD Gothic Neo", "Pretendard", "Noto Sans KR", sans-serif',
    background: "#f7f8fa",
    minHeight: "100vh",
    maxWidth: 480,
    margin: "0 auto",
    padding: "16px 14px 32px",
    color: "#1c2433",
  },
  header: { marginBottom: 14 },
  trainRow: { display: "flex", alignItems: "center", gap: 8, marginBottom: 8 },
  badge: {
    background: "#1a3a6b", color: "#fff", fontWeight: 800, fontSize: 13,
    padding: "4px 10px", borderRadius: 6, letterSpacing: "0.02em",
  },
  dim: { fontSize: 12.5, color: "#6b7686" },
  statusRow: { display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 },
  pill: { fontSize: 10.5, fontWeight: 700, padding: "3px 8px", borderRadius: 20, border: "1px solid" },
  pillSeated: { background: "#eef3fb", color: "#1a3a6b", borderColor: "#c6d4ea" },
  pillStanding: { background: "#fdf3e7", color: "#a05a00", borderColor: "#f0d9b5" },
  pillGps: { background: "#eef8f2", color: "#0e7a4a", borderColor: "#bfe5cf" },
  pillEst: { background: "#f0f2f5", color: "#6b7686", borderColor: "#e2e6eb" },
  pillDelay: { background: "#fdf3e7", color: "#a05a00", borderColor: "#f0d9b5" },
  pillFresh: { background: "#f0f2f5", color: "#6b7686", borderColor: "#e2e6eb" },
  pillStale: { background: "#fdecea", color: "#c0392b", borderColor: "#eab5ad" },
  routeBar: { display: "flex" },
  routeStop: { flex: 1, textAlign: "center", position: "relative" },
  routeLineWrap: { position: "relative", height: 10, marginBottom: 5 },
  routeLine: { position: "absolute", top: 4, left: "-50%", width: "100%", height: 2 },
  routeDot: {
    position: "absolute", top: 1, left: "50%", transform: "translateX(-50%)",
    width: 8, height: 8, borderRadius: "50%", border: "2px solid",
    boxSizing: "border-box", zIndex: 1,
  },
  routeName: { fontSize: 11.5 },
  verdict: {
    background: "#fff", border: "1px solid #e2e6eb", borderRadius: 12,
    padding: "13px 14px", marginBottom: 12, boxShadow: "0 1px 2px rgba(20,30,50,.04)",
  },
  verdictLine: { display: "flex", alignItems: "center", gap: 10, fontSize: 14, flexWrap: "wrap" },
  seatChip: {
    background: "#eef3fb", color: "#1a3a6b", fontWeight: 700, fontSize: 12.5,
    padding: "3px 8px", borderRadius: 6,
  },
  standBtn: {
    marginLeft: "auto", border: "1.5px solid #b7c1d1", background: "#fff",
    color: "#3d4657", borderRadius: 16, fontSize: 11.5, fontWeight: 700,
    padding: "4px 10px", cursor: "pointer",
  },
  verdictSub: { margin: "8px 0 0", fontSize: 13.5, lineHeight: 1.55, color: "#3d4657" },
  nextPoll: { margin: "8px 0 0", fontSize: 11.5, color: "#9aa4b2" },
  filterRow: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  filterBtn: {
    border: "1.5px solid #1a3a6b", borderRadius: 20, fontSize: 12.5,
    fontWeight: 700, padding: "6px 12px", cursor: "pointer",
  },
  refreshBtn: {
    border: "1.5px solid #b7c1d1", background: "#fff", color: "#3d4657",
    borderRadius: "50%", width: 30, height: 30, fontSize: 15, cursor: "pointer", lineHeight: 1,
  },
  legend: { fontSize: 11.5, color: "#6b7686", display: "flex", alignItems: "center" },
  sw: { display: "inline-block", width: 12, height: 12, borderRadius: 3, border: "1px solid", marginRight: 4 },
  matrixWrap: { background: "#fff", border: "1px solid #e2e6eb", borderRadius: 12, overflow: "hidden" },
  table: { width: "100%", borderCollapse: "collapse" },
  thSeat: {
    textAlign: "left", fontSize: 11, color: "#6b7686",
    padding: "10px 10px 8px", borderBottom: "1px solid #e2e6eb",
  },
  thSeg: {
    fontSize: 10.5, fontWeight: 600, color: "#3d4657",
    padding: "8px 2px", borderBottom: "1px solid #e2e6eb", lineHeight: 1.25,
  },
  thArrow: { color: "#b7c1d1", fontSize: 9 },
  tdSeat: {
    padding: "7px 10px", fontSize: 13, whiteSpace: "nowrap",
    borderBottom: "1px solid #f0f2f5", fontVariantNumeric: "tabular-nums",
  },
  mineTag: {
    marginLeft: 6, fontSize: 9.5, fontWeight: 800, color: "#fff",
    background: "#c0392b", borderRadius: 4, padding: "2px 5px", verticalAlign: "1px",
  },
  okTag: {
    marginLeft: 6, fontSize: 9, fontWeight: 800, color: "#0e7a4a",
    background: "#e9f7ef", border: "1px solid #bfe5cf", borderRadius: 4,
    padding: "1px 4px", verticalAlign: "1px",
  },
  tdCell: { padding: "5px 3px", borderBottom: "1px solid #f0f2f5" },
  cell: { height: 22, borderRadius: 5, border: "1px solid" },
  // 조회 실패 셀 (→ D-48). 색만으로 구분하면 색각 이상·흑백 스크린샷에서 매진과 뭉개진다.
  // 물음표를 함께 찍어 "모른다"를 글자로도 말한다
  cellUnknown: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 700,
    color: "#a05a00",
    lineHeight: 1,
  },
  actionBar: {
    position: "sticky", bottom: 12, marginTop: 12,
    display: "flex", alignItems: "center", justifyContent: "space-between",
    background: "#fff", border: "1px solid #c6d4ea", borderRadius: 12,
    padding: "10px 12px", boxShadow: "0 4px 16px rgba(20,30,50,.12)",
  },
  // `whiteSpace`/`flex` — 설명 문구가 길어지면 버튼이 먼저 눌려 두 줄로 깨진다.
  // 줄어드는 쪽은 설명이고 CTA는 아니다 (→ D-52 ⑥)
  sitBtn: {
    background: "#1a3a6b", color: "#fff", border: "none", borderRadius: 8,
    fontSize: 13, fontWeight: 700, padding: "8px 14px", cursor: "pointer",
    whiteSpace: "nowrap", flex: "0 0 auto",
  },
  foot: { textAlign: "center", fontSize: 11.5, color: "#9aa4b2", marginTop: 14, lineHeight: 1.6 },

  // ── 폼 (로그인 / 탑승 등록) ──────────────────────────────────────
  card: {
    background: "#fff", border: "1px solid #e2e6eb", borderRadius: 12,
    padding: "18px 16px", boxShadow: "0 1px 2px rgba(20,30,50,.04)",
  },
  h1: { fontSize: 18, fontWeight: 800, margin: "0 0 4px" },
  label: { display: "block", fontSize: 12, color: "#6b7686", margin: "12px 0 4px", fontWeight: 700 },
  input: {
    width: "100%", border: "1.5px solid #d8dee9", borderRadius: 8,
    padding: "9px 10px", fontSize: 14, background: "#fff", color: "#1c2433",
  },
  primaryBtn: {
    width: "100%", marginTop: 16, background: "#1a3a6b", color: "#fff",
    border: "none", borderRadius: 8, fontSize: 14, fontWeight: 700,
    padding: "11px 14px", cursor: "pointer",
  },
  ghostBtn: {
    border: "1.5px solid #b7c1d1", background: "#fff", color: "#3d4657",
    borderRadius: 8, fontSize: 12.5, fontWeight: 700, padding: "7px 12px", cursor: "pointer",
  },
  error: {
    marginTop: 12, fontSize: 12.5, color: "#c0392b", background: "#fdecea",
    border: "1px solid #eab5ad", borderRadius: 8, padding: "8px 10px",
  },
  // ── 역 선택 콤보박스 (D-32) ──────────────────────────────────────
  pickerWrap: { position: "relative" },
  pickerList: {
    position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20,
    margin: "4px 0 0", padding: 0, listStyle: "none",
    maxHeight: 220, overflowY: "auto",
    background: "#fff", border: "1.5px solid #d8dee9", borderRadius: 8,
    boxShadow: "0 6px 20px rgba(20,30,50,.14)",
  },
  pickerItem: { padding: "9px 10px", fontSize: 14, cursor: "pointer" },

  // ── 즐겨찾기 노선 칩 (D-56). 피그마 web `Chip/Route`·`Chip/RouteAdd` ──
  favRow: { display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12 },
  favCount: { fontSize: 11, color: "#9aa4b2" },
  favChips: { display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 },
  favChip: {
    display: "inline-flex", alignItems: "center", gap: 6,
    background: "#eef3fb", border: "1px solid #c6d4ea", borderRadius: 20,
    padding: "5px 8px 5px 10px",
  },
  favRoute: {
    border: "none", background: "none", padding: 0, cursor: "pointer",
    fontSize: 12, fontWeight: 700, color: "#1a3a6b", fontFamily: "inherit",
  },
  favDel: {
    border: "none", background: "none", padding: 0, cursor: "pointer",
    fontSize: 13, lineHeight: 1, color: "#9aa4b2",
  },
  favAddChip: {
    background: "#fff", border: "1.5px dashed #b7c1d1", borderRadius: 20,
    padding: "4px 10px", fontSize: 12, fontWeight: 700, color: "#3d4657",
    cursor: "pointer", fontFamily: "inherit",
  },

  segRow: { display: "flex", gap: 8 },
  // native date/time input은 min-width:auto라 flex로 줄지 않는다 → 겹침 방지
  segCol: { flex: 1, minWidth: 0 },
  // 출발/도착역 스왑 (#67) — 피그마 web `Btn/Swap`(78:113). 라벨 줄을 건너뛰고
  // 38px 입력칸의 세로 중앙에 오도록 행 바닥 기준으로 3px 띄운다
  swapCol: { flex: "0 0 auto", alignSelf: "flex-end", marginBottom: 3 },
  swapBtn: {
    width: 32, height: 32, borderRadius: 16, border: "1.5px solid #d8dee9",
    background: "#fff", color: "#1a3a6b", cursor: "pointer", padding: 0,
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  toggleRow: { display: "flex", gap: 8, marginTop: 6 },
};
