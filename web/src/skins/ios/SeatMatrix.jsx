import { useCallback, useEffect, useState } from "react";
import { api, cacheMatrix, readCachedMatrix } from "../../core/api";
import { buildRows, failureSummary, minutesAgo, summarize } from "../../core/format";
import { st, tk } from "./styles";

// 피그마 ios `26:110`(06 입석) · `26:227`(07 착석) · `28:142`(08 오프라인) · `28:258`(09 실패).
//
// ★ **판정 문구는 이 파일이 만들지 않는다.** core/format.js가 문장 조각을 주고 여기서는
// 강조를 어떻게 그릴지만 정한다 (→ D-50). 스킨이 응답을 해석하기 시작하면 web과 iOS가
// 갈리고, 그러면 뒤처진 쪽이 틀린 정보를 보여준다 — D-43 결정 ③이 경고한 실패다.

const TONE = { ok: tk.ok, warn: tk.warn, danger: tk.danger, muted: tk.textMuted, navy: tk.brandNavy };

// 문장 조각 배열을 그린다. 강조(em)를 굵게 그리는 것이 이 스킨의 선택이다.
const Segs = ({ parts }) =>
  parts.map((p, i) => (p.em ? <b key={i}>{p.t}</b> : <span key={i}>{p.t}</span>));

const CELL = {
  unknown: { background: "#fdf3e7", borderColor: "#e8c9a0" },
  past: { background: "#f0f2f5", borderColor: "#e2e6eb" },
  sold: { background: "#f6d5d0", borderColor: "#eab5ad" },
  empty: { background: "#e9f7ef", borderColor: "#bfe5cf" },
};

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
        status: subscription.status,
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

  // ── 09 조회 실패: 캐시본조차 없다. 여기서 나갈 길을 반드시 남겨야 한다 —
  // "설정에서 계정을 등록하라"는 에러를 띄우면서 설정으로 갈 수단이 없으면
  // 재시도만 반복하는 막다른 골목이 된다 (실사용 중 발견).
  if (!data) {
    return (
      <div style={st.screen}>
        <div style={st.navBar}>
          <span style={{ minWidth: 64 }} />
          <span style={st.navTitle}>좌석 매트릭스</span>
          <span style={{ minWidth: 64 }} />
        </div>
        <div style={st.body}>
          <p style={{ ...st.subtitle, margin: 0 }}>
            {error ? `조회 실패: ${error}` : "좌석 정보를 불러오는 중…"}
          </p>
          {error && (
            <div style={st.group}>
              <button style={st.actionRow} onClick={load}>다시 시도</button>
              <div style={st.sep} />
              <button style={st.actionRow} onClick={onOpenSettings}>설정</button>
              <div style={st.sep} />
              <button style={st.actionRow} onClick={onReset}>다른 열차</button>
            </div>
          )}
        </div>
      </div>
    );
  }

  const { stops, seats, verdict, position_source, delay_minutes } = data;
  const boardIdx = stops.indexOf(data.board_at);
  const alightIdx = stops.indexOf(data.alight_at);
  // 실효 시작 = max(팔 수 있는 첫 구간, board_idx) — 서버가 이미 적용해 verdict에 담아준다 (D-18/D-47)
  const startIdx = verdict.start_seg_idx;
  // 진행바는 **열차 위치**를 그린다 — 판정 시작(startIdx)이 아니다 (→ D-47)
  const posIdx = data.current_seg_idx ?? startIdx;
  // 조회에 실패한 구간 (→ D-48). **매진과 반드시 구분해서 그린다**
  const failedSegs = new Set(data.failed_seg_idxs || []);
  const myKey = data.my_seat_no ? `${data.my_car}-${data.my_seat_no}` : null;
  // 표시 범위는 **내 구간(탑승~하차)뿐이다** (→ D-31). 인덱스는 전체 노선 기준을 유지한다
  const segments = stops
    .slice(boardIdx, alightIdx)
    .map((s, i) => ({ from: s, to: stops[boardIdx + i + 1], idx: boardIdx + i }));
  const seated = data.sub_status === "SEATED";

  const { rows, myPinned } = buildRows({
    seats, startIdx, alightIdx, seated, myCar: data.my_car, myKey, onlyClear,
  });
  const selectedSeat = rows.find((s) => s.key === selected);

  // 판정 문구 일체 — 문장은 core가 만든다 (→ D-50)
  const summary = summarize({ verdict, data, stops, startIdx });
  const failed = failureSummary(failedSegs, stops);

  return (
    <div style={st.screen}>
      <div style={st.navBar}>
        <button style={st.navAction} onClick={onReset}>종료</button>
        <span style={st.navTitle}>{data.train_name} {data.train_no}</span>
        <button style={{ ...st.navAction, textAlign: "right" }} onClick={onOpenSettings}>설정</button>
      </div>

      <div style={{ ...st.body, paddingTop: 8 }}>
        <p style={{ ...st.subtitle, margin: 0 }}>
          {data.board_at} → {data.alight_at} · 자유석
        </p>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12 }}>
          <span style={{ ...st.chip, ...(seated ? st.chipNavy : { background: "#fdf3e7", color: tk.warn, borderColor: "#f0d9b5" }) }}>
            {seated ? "착석 중" : "입석 · 자리 찾는 중"}
          </span>
          <span style={{ ...st.chip, ...(position_source === "gps" ? st.chipOK : st.chipMuted) }}>
            {position_source === "gps" ? "GPS 실측" : "시각표 추정"}
          </span>
          {delay_minutes != null && delay_minutes > 0 && (
            <span style={{ ...st.chip, background: "#fdf3e7", color: tk.warn, borderColor: "#f0d9b5" }}>
              지연 {delay_minutes}분
            </span>
          )}
          <span style={{ ...st.chip, ...(stale ? { background: "#fdecea", color: tk.danger, borderColor: "#eab5ad" } : st.chipMuted) }}>
            {stale ? "오프라인 캐시 · " : ""}{minutesAgo(data.fetched_at)} 조회
          </span>
        </div>

        {/* 노선 진행바 — 매트릭스와 같은 범위(내 구간)만 그린다 (→ D-31) */}
        <div style={st.routeBar}>
          {stops.slice(boardIdx, alightIdx + 1).map((name, offset) => {
            const i = boardIdx + offset;
            const passed = i <= posIdx;
            return (
              <div key={name} style={st.routeStop}>
                <div style={st.routeLineWrap}>
                  {i > boardIdx && (
                    <div style={{ ...st.routeLine, background: passed ? tk.brandNavy : "#d8dee9" }} />
                  )}
                  <div style={{
                    ...st.routeDot,
                    background: passed ? tk.brandNavy : tk.surface,
                    borderColor: passed ? tk.brandNavy : tk.borderStrong,
                  }} />
                  {i === posIdx + 1 && <div className="trainPulse" />}
                </div>
                <span style={{
                  ...st.routeName,
                  fontWeight: i === posIdx + 1 ? 700 : 400,
                  color: i === posIdx + 1 ? tk.brandNavy : tk.textMuted,
                }}>
                  {name}
                </span>
              </div>
            );
          })}
        </div>

        {/* ── 판정 카드 (문장은 core/format.js, 여기서는 그리기만) ── */}
        <section style={st.verdict}>
          <div style={st.verdictLine}>
            {summary.chip && (
              <span style={{
                ...st.chip,
                ...(summary.chip.tone === "warn"
                  ? { background: "#fdf3e7", color: tk.warn, borderColor: "#f0d9b5" }
                  : st.chipNavy),
              }}>
                {summary.chip.text}
              </span>
            )}
            {summary.status && (
              <span style={{ ...st.verdictStatus, color: TONE[summary.status.tone] }}>
                {summary.status.text}
              </span>
            )}
            {summary.showStandButton && (
              <button style={st.standBtn} disabled={busy}
                onClick={() => transition({ status: "STANDING" })}>
                일어남
              </button>
            )}
          </div>

          <p style={st.verdictSub}><Segs parts={summary.detail} /></p>

          {/* 지연 착석 그룹 — 지금 앉을 수 있는 좌석과 **분리해서** 보여준다 (D-46).
              섞으면 "지금 앉을 수 있는 자리"인지 구분이 사라진다. */}
          {summary.later && (
            <div style={st.laterBlock}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ ...st.chip, background: "#fdf3e7", color: tk.warn, borderColor: "#f0d9b5" }}>
                  {summary.later.fromStation}부터
                </span>
                <span style={st.laterLabel}>{summary.later.label}</span>
              </div>
              <div style={st.laterSeats}>{summary.later.seats}</div>
            </div>
          )}

          {/* 조회 실패 요약 (→ D-48). ⚠는 이 스킨의 어휘라 여기서 붙인다 */}
          {failed && (
            <p style={{ ...st.verdictSub, color: tk.warn }}>⚠ <Segs parts={failed} /></p>
          )}
          {data.next_poll && (
            <p style={st.nextPoll}>
              다음 자동 조회: {data.next_poll.station} 도착 {data.next_poll.offset_min}분 전
            </p>
          )}
          {error && <p style={{ ...st.nextPoll, color: tk.danger }}>갱신 실패: {error}</p>}
        </section>

        {/* 판단할 것이 없으면 매트릭스를 그리지 않는다 — 조회 자체를 하지 않아 좌석이 0개다.
            빈 표를 그리면 "실제로 조회해 보니 전부 매진"으로 읽힌다 (→ D-47).
            그 판단도 core가 내린다 (summary.showMatrix) */}
        {summary.showMatrix && (
          <>
            <div style={st.filterRow}>
              <button
                onClick={() => setOnlyClear(!onlyClear)}
                style={{
                  ...st.filterBtn,
                  background: onlyClear ? tk.brandNavy : tk.surface,
                  color: onlyClear ? tk.onBrand : tk.brandNavy,
                }}
              >
                {data.alight_at}까지 빈 좌석만
              </button>
              <span style={st.legend}>
                <i style={{ ...st.swatch, ...CELL.empty }} />빈자리
                <i style={{ ...st.swatch, ...CELL.sold, marginLeft: 4 }} />판매
                {failedSegs.size > 0 && (
                  <>
                    <i style={{ ...st.swatch, ...CELL.unknown, marginLeft: 4 }} />조회 실패
                  </>
                )}
              </span>
              <button style={st.refreshBtn} title="지금 조회" onClick={load} disabled={busy}>↻</button>
            </div>

            <div style={st.matrix}>
              <table style={st.table}>
                <thead>
                  <tr>
                    <th style={st.thSeat}>좌석</th>
                    {segments.map((seg) => (
                      <th key={seg.idx} style={{ ...st.thSeg, opacity: seg.idx < startIdx ? 0.35 : 1 }}>
                        <div>{seg.from}</div>
                        <div>{failedSegs.has(seg.idx) ? "?" : "↓"}</div>
                        <div>{seg.to}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => {
                    const isMine = s.key === myKey;
                    const isSel = s.key === selected;
                    // 최상단이 "내 자리"로 바뀌었으므로 구분선으로 가른다 — 안 그러면
                    // 내 자리가 1순위 추천으로 읽힌다 (D-49)
                    const sep = myPinned && isMine ? { borderBottom: `2px solid ${tk.borderStrong}` } : null;
                    return (
                      <tr key={s.key} className="iosRow"
                        onClick={() => setSelected(isSel ? null : s.key)}
                        style={{ background: isSel ? "#eef3fb" : "transparent", cursor: "pointer" }}>
                        <td style={{ ...st.tdSeat, ...sep }}>
                          <span style={{ fontWeight: isMine ? 800 : 600 }}>{s.car}-{s.seat_no}</span>
                          {isMine && <span style={st.mineTag}>내 자리</span>}
                          {s.clear_all && !isMine && <span style={st.endTag}>END</span>}
                        </td>
                        {segments.map((seg) => {
                          const sold = s.cells[seg.idx];
                          const past = seg.idx < startIdx;
                          // 실패는 지나온 구간보다 먼저 본다 — 조회 범위 안에서만 실패가 생긴다
                          const unknown = failedSegs.has(seg.idx);
                          const look = unknown ? CELL.unknown : past ? CELL.past : sold ? CELL.sold : CELL.empty;
                          return (
                            <td key={seg.idx} style={{ ...st.tdCell, ...sep }}>
                              <div style={{ ...st.cell, ...look }}>{unknown ? "?" : ""}</div>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {/* ── 좌석 선택 액션 바 (D-15 전이 입력) ── */}
      {selectedSeat && selectedSeat.key !== myKey ? (
        <div style={st.actionBar}>
          <div>
            <b style={{ fontSize: 15 }}>{selectedSeat.car}-{selectedSeat.seat_no}</b>
            <div style={{ fontSize: 13, color: tk.textMuted }}>
              {selectedSeat.clear_all
                ? `${data.alight_at}까지 빈 좌석`
                : `${stops[selectedSeat.clear_until]}까지 빈 좌석`}
            </div>
          </div>
          <button style={st.sitBtn} disabled={busy}
            onClick={() => transition({
              status: "SEATED",
              my_car: selectedSeat.car,
              my_seat_no: selectedSeat.seat_no,
            })}>
            이 자리에 앉음
          </button>
        </div>
      ) : (
        <p style={st.hintBar}>
          자리를 옮기면 좌석을 눌러 갱신하세요 · 알림:{" "}
          {seated ? "내 자리 판매 / 구간 연장 / " : "착석 가능 좌석 / "}
          전량 매진 / 갱신 실패
        </p>
      )}
    </div>
  );
}
