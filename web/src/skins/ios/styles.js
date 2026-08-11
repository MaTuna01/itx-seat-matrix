// iOS 스킨 토큰 — 피그마 `ios` 페이지(iPhone 14 Pro 393×852pt)에서 그대로 가져왔다.
// 값의 근거는 피그마 `31:200` "iOS 설계 규칙" 보드에 있다.
//
// **StatusBar / HomeIndicator는 그리지 않는다.** 피그마의 그 두 요소는 OS 크롬을 표현한
// 목업이라, 코드에서는 `env(safe-area-inset-*)`로 자리만 비운다. 그려버리면 실기기에서
// 두 겹이 된다.
//
// 폰트도 피그마와 다르다 — 파일에 SF Pro / Apple SD Gothic Neo가 없어 Noto Sans KR로
// 대체해 그렸을 뿐이고, 실기기에서는 시스템 폰트를 쓴다 (설계 규칙 보드 각주).

export const tk = {
  bgGrouped: "#f2f2f7",
  surface: "#ffffff",
  separator: "#d8d8dd",
  fillTrack: "#e9e9ef",
  borderStrong: "#b7c1d1",
  textPrimary: "#1c2433",
  textMuted: "#6b7686",
  textFaint: "#9aa4b2",
  brandNavy: "#1a3a6b",
  onBrand: "#ffffff",
  ok: "#0e7a4a",
  warn: "#a05a00",
  danger: "#c0392b",
};

const FONT =
  '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Apple SD Gothic Neo", "Pretendard", "Noto Sans KR", sans-serif';

export const css = `
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { margin: 0; background: ${tk.bgGrouped}; }
  input, button { font-family: inherit; }
  /* iOS 스위치 — 51×31 트랙 + 27 노브 (설계 규칙: 스위치 51×31) */
  .iosSwitch { appearance: none; -webkit-appearance: none; margin: 0; flex: 0 0 auto;
    width: 51px; height: 31px; border-radius: 16px; background: ${tk.fillTrack};
    position: relative; transition: background .2s ease; cursor: pointer; }
  .iosSwitch:checked { background: ${tk.brandNavy}; }
  .iosSwitch::after { content: ""; position: absolute; top: 2px; left: 2px;
    width: 27px; height: 27px; border-radius: 50%; background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,.2); transition: transform .2s ease; }
  .iosSwitch:checked::after { transform: translateX(20px); }
  .iosSwitch:focus-visible { outline: 2px solid ${tk.brandNavy}; outline-offset: 2px; }
  /* 행 전체가 탭 타깃이다 (최소 44pt 규칙) */
  .iosRow:active { background: #ececf1; }
  /* 좌석 선택 액션 바 — 시트처럼 화면 아래에서 올라온다.
     translateX(-50%)를 유지해야 393 프레임 가운데에 남는다 */
  @keyframes iosBarUp {
    from { transform: translate(-50%, 100%); }
    to   { transform: translate(-50%, 0); }
  }
  .iosActionBar { animation: iosBarUp .22s cubic-bezier(.32,.72,0,1); }
  @media (prefers-reduced-motion: reduce) {
    .iosSwitch, .iosSwitch::after { transition: none; }
    .iosActionBar { animation: none; }
  }
`;

export const st = {
  // 화면 — 맥에서 `?ui=ios`로 열어도 실기기 폭으로 보이도록 393에 가둔다
  screen: {
    fontFamily: FONT,
    background: tk.bgGrouped,
    color: tk.textPrimary,
    minHeight: "100dvh",
    maxWidth: 393,
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    paddingTop: "env(safe-area-inset-top)",
    paddingBottom: "env(safe-area-inset-bottom)",
  },
  // 스크롤 영역. 좌우 여백 16pt (설계 규칙)
  body: { flex: 1, padding: "16px 16px 24px", overflowY: "auto" },
  // 하단 고정 CTA — 엄지 영역 (설계 규칙: 주요 CTA는 하단 고정)
  bottomBar: { padding: "8px 16px 16px", display: "flex", flexDirection: "column", gap: 20 },

  title: { fontSize: 34, fontWeight: 800, lineHeight: 1.35, letterSpacing: "-0.02em", margin: 0 },
  subtitle: { fontSize: 15, color: tk.textMuted, lineHeight: 1.35, margin: "8px 0 0" },
  note: { fontSize: 13, color: tk.textMuted, lineHeight: 1.35, margin: "8px 4px 0" },
  errorNote: { fontSize: 13, color: tk.danger, lineHeight: 1.35, margin: "8px 4px 0" },

  // 인셋 그룹 — 라운드 12, 흰 배경 (설계 규칙)
  group: { background: tk.surface, borderRadius: 12, overflow: "hidden", marginTop: 16 },
  sep: { height: 1, background: tk.separator, marginLeft: 16 },

  // 폼 행 50pt — 라벨 15pt 좌측 고정폭 88, 값 17pt (설계 규칙)
  fieldRow: { display: "flex", alignItems: "center", gap: 12, height: 50, padding: "0 16px" },
  fieldLabel: { fontSize: 15, color: tk.textMuted, width: 88, flex: "0 0 auto" },
  fieldInput: {
    flex: 1, minWidth: 0, fontSize: 17, color: tk.textPrimary,
    border: "none", outline: "none", background: "transparent", padding: 0,
  },
  // 리스트 행 50pt
  listRow: { display: "flex", alignItems: "center", gap: 8, height: 50, padding: "0 16px", fontSize: 17 },
  listLabel: { flex: 1, minWidth: 0 },

  // 주요 버튼 50pt · 라운드 12 · 폭 = 화면폭 - 32 (설계 규칙)
  primaryBtn: {
    display: "flex", alignItems: "center", justifyContent: "center",
    width: "100%", height: 50, borderRadius: 12, border: "none",
    background: tk.brandNavy, color: tk.onBrand, fontSize: 17, fontWeight: 700, cursor: "pointer",
  },
  linkBtn: {
    width: "100%", padding: "8px 0", border: "none", background: "none",
    color: tk.brandNavy, fontSize: 17, fontWeight: 700, cursor: "pointer",
  },

  // ── 모달 시트 (설정 등). 상단 56pt를 남겨 뒤 화면이 비쳐 보인다 ──
  sheetBackdrop: { position: "fixed", inset: 0, background: "rgba(0,0,0,.28)" },
  sheet: {
    position: "fixed", left: "50%", transform: "translateX(-50%)",
    top: 56, bottom: 0, width: "100%", maxWidth: 393,
    background: tk.bgGrouped, borderRadius: "12px 12px 0 0",
    display: "flex", flexDirection: "column", overflow: "hidden",
  },
  grabber: { width: 36, height: 5, borderRadius: 3, background: "#c9c9cf", margin: "8px auto 0" },
  sheetBar: {
    display: "flex", alignItems: "center", height: 44, padding: "0 16px", flex: "0 0 auto",
  },
  sheetTitle: { flex: 1, textAlign: "center", fontSize: 17, fontWeight: 700 },
  sheetAction: {
    minWidth: 56, border: "none", background: "none", color: tk.brandNavy,
    fontSize: 17, fontWeight: 700, cursor: "pointer", padding: 0,
  },
  sheetBody: { flex: 1, overflowY: "auto", padding: "0 16px 32px" },

  // ── 즐겨찾기 노선 칩 (D-56). 피그마 ios `iOS/Chip-Route`·`iOS/Chip-RouteAdd` ──
  favLabelRow: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "0 16px", margin: "0 0 8px",
  },
  favCount: { fontSize: 12, color: tk.textFaint },
  favChips: { display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 24 },
  favChip: {
    display: "inline-flex", alignItems: "center", gap: 6, height: 28,
    background: "#eef3fb", border: `1px solid #c6d4ea`, borderRadius: 14,
    padding: "0 10px 0 12px",
  },
  favRoute: {
    border: "none", background: "none", padding: 0, cursor: "pointer",
    fontSize: 13, fontWeight: 700, color: tk.brandNavy, fontFamily: "inherit",
  },
  favDel: {
    border: "none", background: "none", padding: 0, cursor: "pointer",
    fontSize: 14, lineHeight: 1, color: tk.textFaint,
  },
  favAddChip: {
    height: 28, background: tk.surface, border: `1.5px dashed ${tk.borderStrong}`,
    borderRadius: 14, padding: "0 12px", fontSize: 13, fontWeight: 700,
    color: tk.textMuted, cursor: "pointer", fontFamily: "inherit",
  },

  // ── 그룹 리스트 ──
  // 섹션 라벨은 그룹보다 16pt 더 안쪽이다 (화면 기준 32pt)
  sectionLabel: { fontSize: 13, color: tk.textMuted, padding: "0 16px", margin: "24px 0 8px" },
  footnote: { fontSize: 13, color: tk.textMuted, lineHeight: 1.35, padding: "0 16px", margin: "8px 0 0" },
  footnoteWarn: { fontSize: 13, color: tk.warn, lineHeight: 1.35, padding: "0 16px", margin: "8px 0 0" },
  footnoteError: { fontSize: 13, color: tk.danger, lineHeight: 1.35, padding: "0 16px", margin: "8px 0 0" },

  row: { display: "flex", alignItems: "center", gap: 12, minHeight: 50, padding: "0 16px", fontSize: 17 },
  rowLabel: { flex: 1, minWidth: 0 },
  rowValue: { color: tk.textMuted, fontSize: 17, flex: "0 0 auto" },
  // 전체가 눌리는 행 — 최소 44pt를 넘긴다
  actionRow: {
    display: "flex", alignItems: "center", width: "100%", minHeight: 50, padding: "0 16px",
    border: "none", background: "none", font: "inherit", fontSize: 17, textAlign: "left",
    color: tk.brandNavy, cursor: "pointer",
  },
  destructiveRow: { color: tk.danger },
  // 출발/도착역 스왑 (#67) — 피그마 ios `iOS/Btn-Swap`(78:280).
  // 탭 타깃 44pt(31:200 규칙), 비주얼은 28pt 원
  swapBtn: {
    width: 44, height: 44, flex: "0 0 auto", border: "none", background: "none",
    padding: 0, cursor: "pointer", color: tk.brandNavy,
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  swapCircle: {
    width: 28, height: 28, borderRadius: 14, background: tk.fillTrack,
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  // 값 옆의 작은 텍스트 버튼 (해제 등)
  rowBtn: {
    border: "none", background: "none", color: tk.brandNavy, fontSize: 15,
    cursor: "pointer", padding: "8px 0 8px 8px", flex: "0 0 auto",
  },

  // ── 내비게이션 바 44pt (설계 규칙) ──
  // **상단에 고정하고 상태바까지 덮는다.** 흐름에 두면 같이 스크롤돼서, 내리다 보면
  // 판정 문구가 시계·배터리 밑을 지나간다 (실기기에서 발견). 네이티브 iOS가 내비바를
  // 상태바 아래로 밀어 넣고 블러를 씌우는 것이 바로 이것 때문이다.
  //
  // `screen`이 이미 `padding-top: env(safe-area-inset-top)`을 갖고 있어서, 그만큼
  // 음수 마진으로 끌어올린 뒤 같은 값을 자기 패딩으로 되돌린다 — 다른 화면(로그인·부팅)의
  // 세이프 에어리어는 건드리지 않고 내비바만 상태바까지 올라간다.
  navBar: {
    position: "sticky", top: 0, zIndex: 10, flex: "0 0 auto",
    display: "flex", alignItems: "center",
    height: "calc(44px + env(safe-area-inset-top))",
    marginTop: "calc(-1 * env(safe-area-inset-top))",
    padding: "env(safe-area-inset-top) 16px 0",
    background: "rgba(242,242,247,.82)",
    backdropFilter: "saturate(180%) blur(20px)",
    WebkitBackdropFilter: "saturate(180%) blur(20px)",
  },
  navTitle: { flex: 1, textAlign: "center", fontSize: 17, fontWeight: 700 },
  navAction: {
    minWidth: 64, border: "none", background: "none", color: tk.brandNavy,
    fontSize: 17, cursor: "pointer", padding: 0,
  },

  // ── 세그먼트 44pt — 흔들리는 열차 안 오조작 방지 (설계 규칙) ──
  segment: { display: "flex", gap: 2, height: 44, padding: 3, borderRadius: 10, background: tk.fillTrack },
  segmentItem: {
    flex: 1, border: "none", borderRadius: 8, background: "transparent",
    color: tk.textPrimary, fontSize: 15, cursor: "pointer", padding: 0,
  },
  segmentItemOn: { background: tk.surface, fontWeight: 700, boxShadow: "0 1px 3px rgba(0,0,0,.12)" },

  // ── 검색 필드 (역 검색 시트) ──
  searchField: {
    display: "flex", alignItems: "center", height: 40, margin: "0 16px",
    padding: "0 12px", borderRadius: 10, background: tk.fillTrack,
  },
  searchInput: {
    flex: 1, minWidth: 0, border: "none", outline: "none", background: "transparent",
    fontSize: 17, color: tk.textPrimary, padding: 0,
  },
  // 검색 결과 행 — 좌우 여백 없이 시트 폭을 꽉 채운다
  pickItem: {
    display: "flex", alignItems: "center", width: "100%", minHeight: 50, padding: "0 16px",
    border: "none", background: "none", font: "inherit", fontSize: 17, textAlign: "left",
    color: tk.textPrimary, cursor: "pointer",
  },

  // ── 열차 행 ──
  trainRow: {
    display: "flex", alignItems: "center", gap: 10, width: "100%", minHeight: 68,
    padding: "0 16px", border: "none", background: "none", font: "inherit",
    textAlign: "left", cursor: "pointer",
  },
  trainBadge: {
    fontSize: 13, fontWeight: 800, color: tk.onBrand, background: tk.textMuted,
    borderRadius: 6, padding: "4px 8px", flex: "0 0 auto",
  },
  trainNo: { fontSize: 17, fontWeight: 700 },
  trainTime: { marginLeft: "auto", fontSize: 15, color: tk.textMuted, fontVariantNumeric: "tabular-nums" },

  // ── 노선 진행바 ──
  routeBar: { display: "flex", marginTop: 12 },
  routeStop: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", alignItems: "center" },
  routeLineWrap: { position: "relative", width: "100%", height: 10, display: "flex", justifyContent: "center" },
  routeLine: { position: "absolute", right: "50%", top: 4, width: "100%", height: 2 },
  routeDot: { width: 10, height: 10, borderRadius: "50%", border: "2px solid", zIndex: 1 },
  routeName: { fontSize: 11, marginTop: 6, whiteSpace: "nowrap" },

  // ── 판정 카드 ──
  verdict: { background: tk.surface, borderRadius: 12, padding: 14, marginTop: 12 },
  verdictLine: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  verdictStatus: { fontSize: 17, fontWeight: 700 },
  verdictSub: { fontSize: 15, lineHeight: 1.4, margin: "8px 0 0" },
  // 지연 착석 그룹 — 지금 앉을 수 있는 자리와 시각적으로 분리한다 (D-46 결정 ①)
  laterBlock: { background: "#fdf6ec", borderRadius: 10, padding: "8px 10px", marginTop: 8 },
  laterLabel: { fontSize: 13, color: "#966a30" },
  laterSeats: { fontSize: 15, marginTop: 4 },
  nextPoll: { fontSize: 13, color: tk.textMuted, margin: "8px 0 0" },
  standBtn: {
    marginLeft: "auto", border: `1px solid ${tk.borderStrong}`, background: tk.surface,
    borderRadius: 14, height: 28, padding: "0 12px", fontSize: 13, fontWeight: 700,
    color: tk.textPrimary, cursor: "pointer",
  },

  // ── 필터 + 범례 ──
  filterRow: { display: "flex", alignItems: "center", gap: 10, marginTop: 16 },
  filterBtn: {
    height: 36, padding: "0 14px", borderRadius: 18, border: `1px solid ${tk.brandNavy}`,
    fontSize: 15, fontWeight: 700, cursor: "pointer",
  },
  legend: { marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: tk.textMuted },
  swatch: { width: 12, height: 12, borderRadius: 3, border: "1px solid", display: "inline-block" },
  refreshBtn: {
    width: 36, height: 36, borderRadius: 18, border: `1px solid ${tk.borderStrong}`,
    background: tk.surface, fontSize: 17, cursor: "pointer", flex: "0 0 auto",
  },

  // ── 좌석 × 구간 매트릭스 ──
  // 정차역이 많은 노선에서 열 너비가 제각각이 되던 문제를 고쳤다 (실기기에서 발견).
  // 자동 폭이면 `영등포`(3자) 열이 `안양`(2자) 열보다 넓어져 격자로 읽히지 않는다.
  // → `tableLayout: fixed`로 구간 열을 균등하게 하고, 11pt가 뭉개지는 폭 아래로는
  //   줄이는 대신 **가로로 스크롤**한다. 좌석 열은 왼쪽에 고정해 항상 보인다.
  matrix: {
    background: tk.surface, borderRadius: 12, marginTop: 8,
    overflowX: "auto", WebkitOverflowScrolling: "touch",
  },
  table: { width: "100%", borderCollapse: "collapse", tableLayout: "fixed" },
  thSeat: { textAlign: "left", fontSize: 11, color: tk.textMuted, padding: "10px 12px 8px" },
  // 구간 헤더 11pt (설계 규칙: 웹 10.5 → 11). 줄바꿈되면 헤더 높이가 들쭉날쭉해진다
  thSeg: {
    fontSize: 11, color: tk.textMuted, padding: "8px 2px", lineHeight: 1.25,
    fontWeight: 400, whiteSpace: "nowrap",
  },
  tdSeat: { padding: "8px 12px", fontSize: 15, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" },
  // 가로 스크롤 중에도 어느 좌석인지 보여야 한다. 배경은 행 선택을 따라가야 하므로
  // 컴포넌트에서 넣는다 — 여기서 고정하면 선택 하이라이트를 덮는다
  stickySeat: { position: "sticky", left: 0, zIndex: 1, boxShadow: `1px 0 0 ${tk.separator}` },
  scrollHint: { fontSize: 13, color: tk.textMuted, textAlign: "right", margin: "6px 2px 0" },
  tdCell: { padding: "6px 3px" },
  cell: {
    height: 28, borderRadius: 6, border: "1px solid", fontSize: 13, fontWeight: 700,
    display: "flex", alignItems: "center", justifyContent: "center", color: tk.warn,
  },
  mineTag: {
    marginLeft: 6, fontSize: 10, fontWeight: 800, color: tk.onBrand,
    background: tk.danger, borderRadius: 4, padding: "2px 5px", verticalAlign: 2,
  },
  endTag: {
    marginLeft: 6, fontSize: 10, fontWeight: 800, color: tk.ok,
    background: "#eef8f2", borderRadius: 4, padding: "2px 5px", verticalAlign: 2,
  },

  // ── 하단 액션 바 (좌석 선택 시) ──
  // **뷰포트에 고정한다.** `screen`이 minHeight라 콘텐츠가 길면 문서가 통째로 스크롤되고,
  // 흐름에 두면 바가 매트릭스 맨 끝에 앉아 끝까지 내려야 보인다 (실기기에서 발견).
  // 배경 막(backdrop)은 두지 않는다 — 바를 띄운 채로 다른 좌석을 눌러 비교해야 한다.
  actionBar: {
    position: "fixed", left: "50%", transform: "translateX(-50%)", bottom: 0, zIndex: 20,
    width: "100%", maxWidth: 393,
    display: "flex", alignItems: "center", gap: 12,
    padding: "12px 16px calc(16px + env(safe-area-inset-bottom))",
    background: tk.surface, borderTop: `1px solid ${tk.separator}`,
    borderRadius: "14px 14px 0 0",
    boxShadow: "0 -4px 16px rgba(0,0,0,.12)",
  },
  // 선택 해제. 좌석 행을 다시 눌러도 닫히지만 그 행이 화면 밖일 수 있다
  actionClose: {
    width: 44, height: 44, marginLeft: -12, flex: "0 0 auto",
    border: "none", background: "none", color: tk.textMuted, fontSize: 17, cursor: "pointer",
  },
  // 문구가 길어지면(`지금은 빈 자리가 아님 · …`) 버튼이 먼저 눌려 두 줄로 깨진다.
  // **CTA는 한 줄이어야 한다** — 줄어드는 쪽은 설명이고, 버튼은 아니다.
  sitBtn: {
    marginLeft: "auto", flex: "0 0 auto", whiteSpace: "nowrap",
    height: 44, padding: "0 18px", borderRadius: 12, border: "none",
    background: tk.brandNavy, color: tk.onBrand, fontSize: 15, fontWeight: 700, cursor: "pointer",
  },
  hintBar: { padding: "12px 16px 16px", fontSize: 13, color: tk.textMuted, lineHeight: 1.4, flex: "0 0 auto" },

  chip: {
    fontSize: 13, fontWeight: 700, height: 28, lineHeight: "28px",
    padding: "0 10px", borderRadius: 14, border: "1px solid", flex: "0 0 auto",
  },
  chipOK: { background: "#eef8f2", color: tk.ok, borderColor: "#bfe5cf" },
  chipNavy: { background: "#eef3fb", color: tk.brandNavy, borderColor: "#c6d4ea" },
  chipMuted: { background: "#f0f2f5", color: tk.textMuted, borderColor: "#e2e6eb" },
};
