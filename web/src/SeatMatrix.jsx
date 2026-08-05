import { useCallback, useEffect, useMemo, useState } from "react";
import { api, cacheMatrix, readCachedMatrix } from "./api";
import { st } from "./styles";

// 프로토타입(seat-matrix.jsx)을 API 연동으로 바꾼 화면.
// 목업 상수(MOCK_RESPONSE)는 GET /api/trains/{train_no}/matrix 응답으로 대체됐고,
// **판정은 서버(domain/verdict.py)가 계산한 verdict를 그대로 신뢰한다.**
// 여기서 계산하는 clear_until은 행 정렬·END 태그용 표시 값일 뿐이다.

const seatKey = (s) => `${s.car}-${s.seat_no}`;

function minutesAgo(iso) {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  return m <= 0 ? "방금" : `${m}분 전`;
}

// verdict.py의 clear_until과 같은 규칙 (표시 전용)
function clearUntil(seat, startIdx, alightIdx) {
  let until = startIdx;
  for (let i = startIdx; i < alightIdx; i++) {
    if (seat.cells[i]) break;
    until = i + 1;
  }
  return until;
}

export default function SeatMatrix({ subscription, onSubscriptionChange, onReset, onOpenSettings }) {
  const [data, setData] = useState(null);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [onlyClear, setOnlyClear] = useState(false);
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = await api.matrix({
        train_no: subscription.train_no,
        date: subscription.date,
        board_at: subscription.board_at,
        alight_at: subscription.alight_at,
        my_seat:
          subscription.status === "SEATED"
            ? `${subscription.my_car}-${subscription.my_seat_no}`
            : undefined,
      });
      setData(res);
      setStale(false);
      setError(null);
      cacheMatrix(res);
    } catch (err) {
      // 열차 안 회선 불안정 — 빈 화면 대신 캐시본을 보여준다 (PLAN 10절)
      const cached = readCachedMatrix();
      if (cached && cached.train_no === subscription.train_no) {
        setData(cached);
        setStale(true);
      }
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }, [subscription]);

  useEffect(() => {
    load();
  }, [load]);

  const transition = async (payload) => {
    setBusy(true);
    try {
      onSubscriptionChange(await api.patchSubscription(subscription.id, payload));
      setSelected(null);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <div style={{ ...st.page, paddingTop: 48 }}>
        <div style={st.card}>
          <p style={st.dim}>{error ? `조회 실패: ${error}` : "좌석 정보를 불러오는 중…"}</p>
          {error && (
            <button style={st.primaryBtn} onClick={load}>다시 시도</button>
          )}
        </div>
      </div>
    );
  }

  const { stops, seats, verdict, position_source, delay_minutes } = data;
  const alightIdx = stops.indexOf(data.alight_at);
  // 실효 시작 = max(current_seg_idx, board_idx) — 서버가 이미 적용해 verdict에 담아준다 (D-18)
  const startIdx = verdict.current_seg_idx;
  const myKey = data.my_seat_no ? `${data.my_car}-${data.my_seat_no}` : null;
  const segments = stops.slice(0, -1).map((s, i) => ({ from: s, to: stops[i + 1], idx: i }));
  const seated = data.sub_status === "SEATED";

  const rows = (() => {
    const enriched = seats.map((s) => {
      const until = clearUntil(s, startIdx, alightIdx);
      return { ...s, key: seatKey(s), clear_until: until, clear_all: until >= alightIdx };
    });
    const sorted = enriched.sort(
      (a, b) =>
        b.clear_until - a.clear_until ||
        (seated ? Math.abs(a.car - data.my_car) - Math.abs(b.car - data.my_car) : a.car - b.car) ||
        a.seat_no.localeCompare(b.seat_no)
    );
    return onlyClear ? sorted.filter((s) => s.clear_all) : sorted;
  })();

  const bestMove = verdict.move_to.find((m) => m.clear_all);
  const clearAllCount = verdict.move_to.filter((m) => m.clear_all).length;
  const selectedSeat = rows.find((s) => s.key === selected);

  return (
    <div style={st.page}>
      {/* ── 헤더: 열차 + 상태 배지 ── */}
      <header style={st.header}>
        <div style={st.trainRow}>
          <span style={st.badge}>{data.train_name} {data.train_no}</span>
          <span style={st.dim}>{data.board_at} → {data.alight_at} · 자유석</span>
          <button style={{ ...st.ghostBtn, marginLeft: "auto", padding: "4px 8px" }} onClick={onReset}>
            탑승 종료
          </button>
          <button style={{ ...st.ghostBtn, padding: "4px 8px" }} onClick={onOpenSettings}>
            설정
          </button>
        </div>
        <div style={st.statusRow}>
          <span style={{ ...st.pill, ...(seated ? st.pillSeated : st.pillStanding) }}>
            {seated ? "착석 중" : "입석 · 자리 찾는 중"}
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
        {seated ? (
          <>
            <div style={st.verdictLine}>
              <span style={st.seatChip}>내 자리 {data.my_car}호차 {data.my_seat_no}</span>
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
              <button onClick={() => transition({ status: "STANDING" })} style={st.standBtn} disabled={busy}>
                일어남
              </button>
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
        {data.next_poll && (
          <p style={st.nextPoll}>
            다음 자동 조회: {data.next_poll.station} 도착 {data.next_poll.offset_min}분 전
          </p>
        )}
        {error && <p style={{ ...st.nextPoll, color: "#c0392b" }}>갱신 실패: {error}</p>}
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
          <button style={st.refreshBtn} title="지금 조회" onClick={load} disabled={busy}>↻</button>
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
          <button
            onClick={() =>
              transition({
                status: "SEATED",
                my_car: selectedSeat.car,
                my_seat_no: selectedSeat.seat_no,
              })
            }
            style={st.sitBtn}
            disabled={busy}
          >
            이 자리에 앉음
          </button>
        </div>
      )}

      <p style={st.foot}>
        위치 권한을 끄면 시각표 추정으로 표시됩니다 · 자리를 옮기면 좌석을 선택해 "이 자리에 앉음"으로 갱신하세요
        <br />
        알림: {seated ? "내 자리 판매 / 구간 연장 / " : "착석 가능 좌석 / "}
        전량 매진 / 갱신 실패 — 폴링당 1건으로 합성 발송 (Phase 3)
      </p>
    </div>
  );
}
