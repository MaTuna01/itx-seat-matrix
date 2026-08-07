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
  @media (prefers-reduced-motion: reduce) {
    .iosSwitch, .iosSwitch::after { transition: none; }
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
  // 값 옆의 작은 텍스트 버튼 (해제 등)
  rowBtn: {
    border: "none", background: "none", color: tk.brandNavy, fontSize: 15,
    cursor: "pointer", padding: "8px 0 8px 8px", flex: "0 0 auto",
  },

  chip: {
    fontSize: 13, fontWeight: 700, height: 28, lineHeight: "28px",
    padding: "0 10px", borderRadius: 14, border: "1px solid", flex: "0 0 auto",
  },
  chipOK: { background: "#eef8f2", color: tk.ok, borderColor: "#bfe5cf" },
  chipNavy: { background: "#eef3fb", color: tk.brandNavy, borderColor: "#c6d4ea" },
  chipMuted: { background: "#f0f2f5", color: tk.textMuted, borderColor: "#e2e6eb" },
};
