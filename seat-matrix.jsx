import { useState, useMemo } from "react";

// ═══════════════════════════════════════════════════════════════
// MOCK: GET /api/trains/1004/matrix?date=...&board_at=천안&alight_at=서울
//       [&my_seat=3-7A]&lat=...&lng=...
// 응답 스키마는 PLAN.md 7절과 1:1. 구현 시 이 상수를 fetch로 대체하면 끝.
//
// v7 프로토타입 변경점:
//  - 구독 상태 기계(STANDING/SEATED) + 전이 UI (D-15)
//    · 좌석 행 선택 → "이 자리에 앉음" (첫 착석·자리 이동 겸용)
//    · "일어남" (SEATED → STANDING)
//    · 구현 시 전부 PATCH /api/subscriptions/{id} 한 엔드포인트
//  - 판정을 클라이언트에서 재계산해 전이가 목업에서도 살아 움직임
//    (실구현에서는 서버 verdict를 신뢰하고, 전이 후 /matrix 재요청으로 대체)
//  - 실효 시작 = max(current_seg_idx, board_idx) (D-18 인덱스 규칙)
//  - 알림 5종 안내 문구 갱신 (D-16, D-20)
// ═══════════════════════════════════════════════════════════════
const MOCK_RESPONSE = {
  train_no: "1004",
  train_name: "ITX-마음",
  date: "2026-08-05",
  stops: ["천안", "평택", "수원", "안양", "영등포", "서울"], // 전체 노선 (D-18)
  current_seg_idx: 1,          // 평택→수원 주행 중
  position_source: "gps",      // "gps" | "schedule"  (D-13: GPS 포그라운드 보정)
  delay_minutes: 4,            // DelayPort 결과. null이면 정보 없음 (D-12)
  board_at: "천안",
  alight_at: "서울",
  // 구독 초기값 (구현 시 구독 API에서). 데모: 착석 상태로 시작
  sub_status: "SEATED",        // "STANDING" | "SEATED" (D-15)
  my_car: 3,
  my_seat_no: "7A",
  seats: [
    { car: 3, seat_no: "5A", cells: [true, true, true, true, true] },
    { car: 3, seat_no: "5B", cells: [true, true, true, true, false] },
    { car: 3, seat_no: "6A", cells: [false, false, true, true, true] },
    { car: 3, seat_no: "6B", cells: [false, false, true, true, false] },
    { car: 3, seat_no: "7A", cells: [true, true, true, false, false] }, // 내 자리
    { car: 3, seat_no: "7B", cells: [true, true, false, true, true] },
    { car: 3, seat_no: "8A", cells: [true, false, false, false, false] },
    { car: 3, seat_no: "8B", cells: [false, false, false, false, false] },
    { car: 3, seat_no: "9A", cells: [true, true, true, true, true] },
    { car: 3, seat_no: "9B", cells: [true, true, true, true, true] },
    { car: 4, seat_no: "1A", cells: [false, false, false, true, true] },
    { car: 4, seat_no: "1B", cells: [false, false, false, false, false] },
    { car: 4, seat_no: "2A", cells: [true, true, true, true, false] },
    { car: 4, seat_no: "2B", cells: [true, true, false, false, false] },
    { car: 4, seat_no: "3A", cells: [false, true, true, true, true] },
    { car: 4, seat_no: "3B", cells: [true, true, true, true, true] },
    { car: 4, seat_no: "4A", cells: [true, true, true, false, true] },
    { car: 4, seat_no: "4B", cells: [false, false, false, false, true] },
  ],
  next_poll: { station: "수원", offset_min: 4 },  // 스케줄러 다음 자동 조회 (9절)
  fetched_at: Date.now() - 3 * 60 * 1000,          // 데모: 3분 전 조회
};

// ─── 유틸 ─────────────────────────────────────────────────────
const seatKey = (s) => `${s.car}-${s.seat_no}`;

function minutesAgo(ts) {
  const m = Math.floor((Date.now() - ts) / 60000);
  return m <= 0 ? "방금" : `${m}분 전`;
}

// clear_until: 실효 시작 구간부터 연속으로 비어있는 마지막 역 인덱스 (verdict.py와 동일 규칙)
function clearUntil(seat, startIdx, alightIdx) {
  let until = startIdx;
  for (let i = startIdx; i < alightIdx; i++) {
    if (seat.cells[i]) break;
    until = i + 1;
  }
  return until;
}

// ─── 판정 (domain/verdict.py 규칙의 프로토타입 재현) ──────────────
// 실구현에서는 서버가 계산해 verdict로 내려준다. 여기서는 상태 전이 데모를 위해
// 클라이언트에서 재계산. 규칙은 PLAN.md 5절과 동일하게 유지할 것.
function computeVerdict({ seats, startIdx, alightIdx, subStatus, myKey, myCar, stops }) {
  const enriched = seats.map((s) => {
    const until = clearUntil(s, startIdx, alightIdx);
    return { ...s, key: seatKey(s), clear_until: until, clear_all: until >= alightIdx };
  });

  // 추천 정렬 (D-18/D-17: SEATED는 내 호차 근접순, STANDING은 clear_until 내림차순)
  const candidates = enriched.filter((s) => s.key !== myKey);
  const clearAllSeats = candidates.filter((s) => s.clear_all);
  const ranked = (clearAllSeats.length > 0 ? clearAllSeats : candidates)
    .slice()
    .sort((a, b) => {
      if (b.clear_until !== a.clear_until) return b.clear_until - a.clear_until;
      if (subStatus === "SEATED" && myCar != null)
        return Math.abs(a.car - myCar) - Math.abs(b.car - myCar);
      return a.car - b.car;
    });
  const move_to = ranked
    .filter((s) => s.clear_until > startIdx)
    .slice(0, 3)
    .map((s) => ({ car: s.car, seat_no: s.seat_no, clear_until_idx: s.clear_until, clear_all: s.clear_all }));

  const all_sold_after_current = enriched.every((s) => s.clear_until <= startIdx);

  // ── SEATED 전용 판정 ──
  let my_seat_status = null, my_seat_sold_from = null, my_seat_clear_until_idx = null;
  if (subStatus === "SEATED") {
    const mine = enriched.find((s) => s.key === myKey);
    if (!mine) {
      // D-18 내 좌석 부재 규칙: 잔여 전 구간 판매로 간주
      my_seat_status = "SOLD_FROM";
      my_seat_sold_from = stops[startIdx + 1] ?? stops[alightIdx];
      my_seat_clear_until_idx = startIdx;
    } else {
      my_seat_clear_until_idx = mine.clear_until;
      if (mine.clear_all) my_seat_status = "CLEAR_ALL";
      else {
        my_seat_status = "SOLD_FROM";
        my_seat_sold_from = stops[mine.clear_until];
      }
    }
  }

  return {
    sub_status: subStatus,
    my_seat_status,
    my_seat_sold_from,
    my_seat_clear_until_idx,
    move_to,
    all_sold_after_current,
    current_seg_idx: startIdx,
    _enriched: enriched, // 매트릭스 렌더용 (API 응답에는 없음)
  };
}

export default function SeatMatrixApp() {
  // 구현 시: useState(null) + useEffect(fetch) + 로컬 캐시 폴백 (10절 오프라인 대응)
  const [data] = useState(MOCK_RESPONSE);
  const [onlyClear, setOnlyClear] = useState(false);
  const [selected, setSelected] = useState(null);
  const [stale] = useState(false); // 구현 시: fetch 실패로 캐시본 표시 중이면 true

  // ── 구독 상태 (D-15). 구현 시: 구독 API 응답 + PATCH로 서버와 동기화 ──
  const [subStatus, setSubStatus] = useState(data.sub_status);
  const [mySeat, setMySeat] = useState(
    data.sub_status === "SEATED" ? { car: data.my_car, seat_no: data.my_seat_no } : null
  );

  const { stops, seats, position_source, delay_minutes } = data;
  const boardIdx = stops.indexOf(data.board_at);
  const alightIdx = stops.indexOf(data.alight_at);
  // D-18 인덱스 규칙: 실효 시작 = max(현재 구간, 탑승역)
  const startIdx = Math.max(data.current_seg_idx, boardIdx);
  const myKey = mySeat ? `${mySeat.car}-${mySeat.seat_no}` : null;
  const segments = stops.slice(0, -1).map((s, i) => ({ from: s, to: stops[i + 1], idx: i }));

  const verdict = useMemo(
    () =>
      computeVerdict({
        seats, startIdx, alightIdx, subStatus, myKey,
        myCar: mySeat?.car ?? null, stops,
      }),
    [seats, startIdx, alightIdx, subStatus, myKey, mySeat, stops]
  );

  const rows = useMemo(() => {
    const sorted = [...verdict._enriched].sort(
      (a, b) =>
        b.clear_until - a.clear_until ||
        (mySeat ? Math.abs(a.car - mySeat.car) - Math.abs(b.car - mySeat.car) : a.car - b.car)
    );
    return onlyClear ? sorted.filter((s) => s.clear_all) : sorted;
  }, [verdict, onlyClear, mySeat]);

  const bestMove = verdict.move_to.find((m) => m.clear_all);
  const clearAllCount = verdict.move_to.filter((m) => m.clear_all).length;
  const selectedSeat = rows.find((s) => s.key === selected);

  // ── 상태 전이 (D-15). 구현 시: PATCH /api/subscriptions/{id} 후 재조회 ──
  const sitHere = (seat) => {
    setMySeat({ car: seat.car, seat_no: seat.seat_no });
    setSubStatus("SEATED");
    setSelected(null);
  };
  const standUp = () => {
    setMySeat(null);
    setSubStatus("STANDING");
  };

  return (
    <div style={st.page}>
      <style>{css}</style>

      {/* ── 헤더: 열차 + 상태 배지 ── */}
      <header style={st.header}>
        <div style={st.trainRow}>
          <span style={st.badge}>{data.train_name} {data.train_no}</span>
          <span style={st.dim}>{data.board_at} → {data.alight_at} · 자유석</span>
        </div>
        <div style={st.statusRow}>
          <span style={{ ...st.pill, ...(subStatus === "SEATED" ? st.pillSeated : st.pillStanding) }}>
            {subStatus === "SEATED" ? "착석 중" : "입석 · 자리 찾는 중"}
          </span>
          <span style={{ ...st.pill, ...(position_source === "gps" ? st.pillGps : st.pillEst) }}>
            {position_source === "gps" ? "◉ GPS 실측 위치" : "시각표 추정 위치"}
          </span>
          {delay_minutes != null && delay_minutes > 0 && (
            <span style={{ ...st.pill, ...st.pillDelay }}>지연 {delay_minutes}분 반영</span>
          )}
          <span style={{ ...st.pill, ...(stale ? st.pillStale : st.pillFresh) }}>
            {stale ? "⚠ 오프라인 캐시 · " : ""}{minutesAgo(data.fetched_at)} 조회
          </span>
        </div>

        {/* ── 노선 진행바 ── */}
        <div style={st.routeBar}>
          {stops.map((name, i) => (
            <div key={name} style={st.routeStop}>
              <div style={st.routeLineWrap}>
                {i > 0 && (
                  <div style={{ ...st.routeLine, background: i <= startIdx ? "#1a3a6b" : "#d8dee9" }} />
                )}
                <div
                  style={{
                    ...st.routeDot,
                    background: i <= startIdx ? "#1a3a6b" : "#fff",
                    borderColor: i <= startIdx ? "#1a3a6b" : "#b7c1d1",
                  }}
                />
                {i === startIdx + 1 && <div className="trainPulse" />}
              </div>
              <span
                style={{
                  ...st.routeName,
                  fontWeight: i === startIdx + 1 ? 700 : 400,
                  color: i === startIdx + 1 ? "#1a3a6b" : "#6b7686",
                }}
              >
                {name}
              </span>
            </div>
          ))}
        </div>
      </header>

      {/* ── 판정 카드 (상태별 분기, D-15/D-16) ── */}
      <section style={st.verdict}>
        {subStatus === "SEATED" ? (
          <>
            <div style={st.verdictLine}>
              <span style={st.seatChip}>내 자리 {mySeat.car}호차 {mySeat.seat_no}</span>
              {verdict.my_seat_status === "CLEAR_ALL" && (
                <span style={{ color: "#0e7a4a", fontWeight: 700 }}>{data.alight_at}까지 안전</span>
              )}
              {verdict.my_seat_status === "SOLD_FROM" && (
                <span style={{ color: "#c0392b", fontWeight: 700 }}>
                  {verdict.my_seat_sold_from}부터 판매됨
                </span>
              )}
              {verdict.my_seat_status === "UNKNOWN" && (
                <span style={{ color: "#6b7686", fontWeight: 700 }}>상태 확인 불가</span>
              )}
              <button onClick={standUp} style={st.standBtn}>일어남</button>
            </div>
            <p style={st.verdictSub}>
              {verdict.all_sold_after_current ? (
                <>남은 구간 잔여 좌석 없음 · <b>지하철 환승</b>이 나을 수 있음</>
              ) : verdict.my_seat_status === "CLEAR_ALL" ? (
                <>이동 불필요 · 자리가 팔리면 알림으로 알려드립니다</>
              ) : bestMove ? (
                <>
                  {stops[startIdx + 1]} 도착 전 이동 권장 → <b>{bestMove.car}호차 {bestMove.seat_no}</b>
                  {clearAllCount > 1 && ` 외 ${clearAllCount - 1}석이 ${data.alight_at}까지 빈 좌석`}
                </>
              ) : (
                <>끝까지 비는 좌석 없음 · 아래에서 최장 구간 좌석 확인</>
              )}
            </p>
          </>
        ) : (
          <>
            <div style={st.verdictLine}>
              <span style={{ ...st.seatChip, background: "#fdf3e7", color: "#a05a00" }}>입석</span>
              {verdict.all_sold_after_current ? (
                <span style={{ color: "#c0392b", fontWeight: 700 }}>앉을 좌석 없음</span>
              ) : bestMove ? (
                <span style={{ color: "#0e7a4a", fontWeight: 700 }}>
                  {stops[startIdx + 1]}부터 착석 가능
                </span>
              ) : (
                <span style={{ color: "#a05a00", fontWeight: 700 }}>일부 구간만 착석 가능</span>
              )}
            </div>
            <p style={st.verdictSub}>
              {verdict.all_sold_after_current ? (
                <>남은 구간 잔여 좌석 없음 · <b>지하철 환승</b>이 나을 수 있음</>
              ) : bestMove ? (
                <>
                  추천 <b>{bestMove.car}호차 {bestMove.seat_no}</b> ({data.alight_at}까지 빈 좌석)
                  {clearAllCount > 1 && ` 외 ${clearAllCount - 1}석`} ·
                  좌석을 선택해 "이 자리에 앉음"을 누르면 이후 알림이 그 자리 기준으로 옵니다
                </>
              ) : (
                <>끝까지 비는 좌석은 없음 · 아래에서 최장 구간 좌석을 골라 앉으세요</>
              )}
            </p>
          </>
        )}
        <p style={st.nextPoll}>
          다음 자동 조회: {data.next_poll.station} 도착 {data.next_poll.offset_min}분 전
        </p>
      </section>

      {/* ── 필터 + 수동 갱신 ── */}
      <div style={st.filterRow}>
        <button
          onClick={() => setOnlyClear(!onlyClear)}
          style={{
            ...st.filterBtn,
            background: onlyClear ? "#1a3a6b" : "#fff",
            color: onlyClear ? "#fff" : "#1a3a6b",
          }}
        >
          {data.alight_at}까지 빈 좌석만
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={st.legend}>
            <i style={{ ...st.sw, background: "#e9f7ef", borderColor: "#bfe5cf" }} />빈자리
            <i style={{ ...st.sw, background: "#f6d5d0", borderColor: "#eab5ad", marginLeft: 8 }} />판매
          </span>
          {/* 구현 시: onClick에서 /matrix 재요청 (60초 서버 캐시가 연타를 흡수) */}
          <button style={st.refreshBtn} title="지금 조회">↻</button>
        </div>
      </div>

      {/* ── 좌석 × 구간 매트릭스 ── */}
      <div style={st.matrixWrap}>
        <table style={st.table}>
          <thead>
            <tr>
              <th style={st.thSeat}>좌석</th>
              {segments.map((seg) => (
                <th key={seg.idx} style={{ ...st.thSeg, opacity: seg.idx < startIdx ? 0.35 : 1 }}>
                  <div>{seg.from}</div>
                  <div style={st.thArrow}>↓</div>
                  <div>{seg.to}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const isMine = s.key === myKey;
              const isSel = s.key === selected;
              return (
                <tr
                  key={s.key}
                  onClick={() => setSelected(isSel ? null : s.key)}
                  style={{ background: isSel ? "#eef3fb" : "transparent", cursor: "pointer" }}
                >
                  <td style={st.tdSeat}>
                    <span style={{ fontWeight: isMine ? 800 : 600 }}>{s.car}-{s.seat_no}</span>
                    {isMine && <span style={st.mineTag}>내자리</span>}
                    {s.clear_all && !isMine && <span style={st.okTag}>END</span>}
                  </td>
                  {segments.map((seg) => {
                    const sold = s.cells[seg.idx];
                    const past = seg.idx < startIdx;
                    return (
                      <td key={seg.idx} style={st.tdCell}>
                        <div
                          style={{
                            ...st.cell,
                            background: past ? "#f0f2f5" : sold ? "#f6d5d0" : "#e9f7ef",
                            borderColor: past ? "#e2e6eb" : sold ? "#eab5ad" : "#bfe5cf",
                          }}
                        />
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ── 좌석 선택 액션 바 (D-15 전이 입력) ── */}
      {selectedSeat && selectedSeat.key !== myKey && (
        <div style={st.actionBar}>
          <div style={{ fontSize: 13 }}>
            <b>{selectedSeat.car}-{selectedSeat.seat_no}</b>
            <span style={{ color: "#6b7686", marginLeft: 6 }}>
              {selectedSeat.clear_all
                ? `${data.alight_at}까지 빈 좌석`
                : `${stops[selectedSeat.clear_until]}까지 빈 좌석`}
            </span>
          </div>
          {/* 구현 시: PATCH /api/subscriptions/{id} { status:"SEATED", my_car, my_seat_no } */}
          <button onClick={() => sitHere(selectedSeat)} style={st.sitBtn}>
            이 자리에 앉음
          </button>
        </div>
      )}

      <p style={st.foot}>
        위치 권한을 끄면 시각표 추정으로 표시됩니다 · 자리를 옮기면 좌석을 선택해 "이 자리에 앉음"으로 갱신하세요
        <br />
        알림: {subStatus === "SEATED" ? "내 자리 판매 / 구간 연장 / " : "착석 가능 좌석 / "}
        전량 매진 / 갱신 실패 — 폴링당 1건으로 합성 발송
      </p>
    </div>
  );
}

const css = `
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

const st = {
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
  actionBar: {
    position: "sticky", bottom: 12, marginTop: 12,
    display: "flex", alignItems: "center", justifyContent: "space-between",
    background: "#fff", border: "1px solid #c6d4ea", borderRadius: 12,
    padding: "10px 12px", boxShadow: "0 4px 16px rgba(20,30,50,.12)",
  },
  sitBtn: {
    background: "#1a3a6b", color: "#fff", border: "none", borderRadius: 8,
    fontSize: 13, fontWeight: 700, padding: "8px 14px", cursor: "pointer",
  },
  foot: { textAlign: "center", fontSize: 11.5, color: "#9aa4b2", marginTop: 14, lineHeight: 1.6 },
};
