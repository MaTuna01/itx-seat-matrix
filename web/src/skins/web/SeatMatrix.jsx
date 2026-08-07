import { useCallback, useEffect, useMemo, useState } from "react";
import { api, cacheMatrix, readCachedMatrix } from "../../core/api";
import { buildRows, failureSummary, minutesAgo, summarize } from "../../core/format";
import { st } from "./styles";

// 프로토타입(seat-matrix.jsx)을 API 연동으로 바꾼 화면.
// 목업 상수(MOCK_RESPONSE)는 GET /api/trains/{train_no}/matrix 응답으로 대체됐다.
//
// **판정 문구는 이 파일이 만들지 않는다** — core/format.js가 문장 조각을 주고 여기서는
// 강조를 어떻게 그릴지만 정한다 (→ D-50). 스킨마다 문장을 조립하면 web과 iOS가 갈리고,
// 그러면 뒤처진 쪽이 틀린 정보를 보여주게 된다.

const TONE = {
  ok: "#0e7a4a",
  warn: "#a05a00",
  danger: "#c0392b",
  muted: "#6b7686",
  navy: "#1a3a6b",
};

// 문장 조각 배열을 그린다. 강조(em)를 <b>로 그리는 것이 web 스킨의 선택이다.
function Segs({ parts }) {
  return parts.map((p, i) => (p.em ? <b key={i}>{p.t}</b> : <span key={i}>{p.t}</span>));
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
    // 캐시본조차 없는 실패. 여기서 나갈 길을 반드시 남겨야 한다 —
    // "설정에서 계정을 등록하라"는 에러를 띄우면서 설정으로 갈 수단이 없으면
    // 재시도만 반복하는 막다른 골목이 된다 (실사용 중 발견).
    return (
      <div style={{ ...st.page, paddingTop: 48 }}>
        <div style={st.card}>
          <p style={st.dim}>{error ? `조회 실패: ${error}` : "좌석 정보를 불러오는 중…"}</p>
          {error && (
            <>
              <button style={st.primaryBtn} onClick={load}>다시 시도</button>
              <div style={{ ...st.toggleRow, marginTop: 8 }}>
                <button style={{ ...st.ghostBtn, flex: 1 }} onClick={onOpenSettings}>설정</button>
                <button style={{ ...st.ghostBtn, flex: 1 }} onClick={onReset}>다른 열차</button>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  const { stops, seats, verdict, position_source, delay_minutes } = data;
  const boardIdx = stops.indexOf(data.board_at);
  const alightIdx = stops.indexOf(data.alight_at);
  // 실효 시작 = max(팔 수 있는 첫 구간, board_idx) — 서버가 이미 적용해 verdict에 담아준다 (D-18/D-47).
  // 열차 위치(data.current_seg_idx)와 다르다 — 주행 중이면 이 값이 한 구간 앞선다
  const startIdx = verdict.start_seg_idx;
  // 진행바는 **열차 위치**를 그린다 — 판정 시작(startIdx)이 아니다 (→ D-47).
  // 주행 중에는 startIdx가 한 구간 앞서므로 그대로 쓰면 열차가 한 역 앞에 있는 것처럼 보인다.
  const posIdx = data.current_seg_idx ?? startIdx;
  // 조회에 실패한 구간 (→ D-48). **매진과 반드시 구분해서 그린다** — 셀은 bool 하나라
  // 실패 구간도 '판매됨'으로 내려오므로, 이 집합 없이는 화면이 둘을 구분할 수 없다.
  // 관측하지 않은 값이 관측값처럼 읽히는 것이 D-31·#35가 밟은 함정이다.
  const failedSegs = new Set(data.failed_seg_idxs || []);
  const myKey = data.my_seat_no ? `${data.my_car}-${data.my_seat_no}` : null;
  // 표시 범위는 **내 구간(탑승~하차)뿐이다.** `stops`는 전체 노선이지만(D-18 인덱스 규칙)
  // 내 구간 밖은 애초에 조회하지 않으므로 셀이 UNQUERIED_CELL(=판매됨)로 채워져 있다.
  // 그대로 그리면 관측하지 않은 값이 관측값처럼 보인다 — 특히 하차역 이후는 흐림 처리도
  // 걸리지 않아(startIdx는 항상 하차역 앞) 실조회한 "전부 매진"처럼 읽힌다.
  // 인덱스는 전체 노선 기준을 그대로 쓴다 — 슬라이스해서 재번호를 매기면 D-18과 어긋난다.
  const segments = stops
    .slice(boardIdx, alightIdx)
    .map((s, i) => ({ from: s, to: stops[boardIdx + i + 1], idx: boardIdx + i }));
  const seated = data.sub_status === "SEATED";

  // 행 순서와 필터 예외는 core가 정한다 (→ D-49/D-50). myPinned가 true면 최상단이 "내 자리"라
  // 구분선으로 갈라야 한다 — 안 그러면 내 자리가 1순위 추천으로 읽힌다.
  const { rows, myPinned } = buildRows({
    seats, startIdx, alightIdx, seated, myCar: data.my_car, myKey, onlyClear,
  });

  const selectedSeat = rows.find((s) => s.key === selected);

  // 판정 문구 일체 — 문장은 core가 만든다 (→ D-50)
  const summary = summarize({ verdict, data, stops, startIdx });
  const failed = failureSummary(failedSegs, stops);

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

        {/* ── 노선 진행바 (매트릭스와 같은 범위 = 내 구간) ──
            전체 노선을 그리면 28정차 열차에서 역 이름이 뭉개진다. 인덱스는
            전체 노선 기준을 유지해 startIdx 비교가 그대로 맞아떨어진다. */}
        <div style={st.routeBar}>
          {stops.slice(boardIdx, alightIdx + 1).map((name, offset) => {
            const i = boardIdx + offset;
            return (
            <div key={name} style={st.routeStop}>
              <div style={st.routeLineWrap}>
                {i > boardIdx && (
                  <div style={{ ...st.routeLine, background: i <= posIdx ? "#1a3a6b" : "#d8dee9" }} />
                )}
                <div
                  style={{
                    ...st.routeDot,
                    background: i <= posIdx ? "#1a3a6b" : "#fff",
                    borderColor: i <= posIdx ? "#1a3a6b" : "#b7c1d1",
                  }}
                />
                {i === posIdx + 1 && <div className="trainPulse" />}
              </div>
              <span
                style={{
                  ...st.routeName,
                  fontWeight: i === posIdx + 1 ? 700 : 400,
                  color: i === posIdx + 1 ? "#1a3a6b" : "#6b7686",
                }}
              >
                {name}
              </span>
            </div>
            );
          })}
        </div>
      </header>

      {/* ── 판정 카드 (문장은 core/format.js, 여기서는 그리기만) ── */}
      <section style={st.verdict}>
        <div style={st.verdictLine}>
          {summary.chip && (
            <span
              style={
                summary.chip.tone === "warn"
                  ? { ...st.seatChip, background: "#fdf3e7", color: TONE.warn }
                  : st.seatChip
              }
            >
              {summary.chip.text}
            </span>
          )}
          {summary.status && (
            <span style={{ color: TONE[summary.status.tone], fontWeight: 700 }}>
              {summary.status.text}
            </span>
          )}
          {summary.showStandButton && (
            <button onClick={() => transition({ status: "STANDING" })} style={st.standBtn} disabled={busy}>
              일어남
            </button>
          )}
        </div>
        <p style={st.verdictSub}><Segs parts={summary.detail} /></p>

        {/* 지연 착석 목록 — 지금 앉을 수 있는 좌석과 **분리해서** 보여준다 (D-46).
            섞으면 "지금 앉을 수 있는 자리"인지 구분이 사라진다. */}
        {summary.later && (
          <p style={st.verdictSub}>
            {summary.later.label}: {summary.later.seats}
          </p>
        )}
        {/* 조회 실패 요약 (→ D-48). ⚠는 이 스킨의 어휘라 여기서 붙인다 */}
        {failed && (
          <p style={{ ...st.verdictSub, color: TONE.warn }}>
            ⚠ <Segs parts={failed} />
          </p>
        )}
        {data.next_poll && (
          <p style={st.nextPoll}>
            다음 자동 조회: {data.next_poll.station} 도착 {data.next_poll.offset_min}분 전
          </p>
        )}
        {error && <p style={{ ...st.nextPoll, color: TONE.danger }}>갱신 실패: {error}</p>}
      </section>

      {/* ── 필터 + 수동 갱신 + 매트릭스 ── */}
      {/* 판단할 것이 없으면 아무것도 그리지 않는다 — 조회 자체를 하지 않아 좌석이 0개다.
          빈 표를 그리면 "실제로 조회해 보니 전부 매진"으로 읽힌다 (→ D-47).
          그 판단도 core가 내린다 (summary.showMatrix) — 스킨이 응답 필드를 해석하지 않는다 */}
      {summary.showMatrix && (
      <>
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
            {failedSegs.size > 0 && (
              <>
                <i style={{ ...st.sw, background: "#fdf3e7", borderColor: "#e8c9a0", marginLeft: 8 }} />
                조회 실패
              </>
            )}
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
                  <div style={st.thArrow}>{failedSegs.has(seg.idx) ? "?" : "↓"}</div>
                  <div>{seg.to}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const isMine = s.key === myKey;
              const isSel = s.key === selected;
              const sep = myPinned && isMine ? { borderBottom: "2px solid #c6d4ea" } : null;
              return (
                <tr
                  key={s.key}
                  onClick={() => setSelected(isSel ? null : s.key)}
                  style={{ background: isSel ? "#eef3fb" : "transparent", cursor: "pointer" }}
                >
                  <td style={{ ...st.tdSeat, ...sep }}>
                    <span style={{ fontWeight: isMine ? 800 : 600 }}>{s.car}-{s.seat_no}</span>
                    {isMine && <span style={st.mineTag}>내자리</span>}
                    {s.clear_all && !isMine && <span style={st.okTag}>END</span>}
                  </td>
                  {segments.map((seg) => {
                    const sold = s.cells[seg.idx];
                    const past = seg.idx < startIdx;
                    // 실패는 지나온 구간보다 먼저 본다 — 조회 범위 안에서만 실패가 생긴다
                    const unknown = failedSegs.has(seg.idx);
                    return (
                      <td key={seg.idx} style={{ ...st.tdCell, ...sep }}>
                        <div
                          style={{
                            ...st.cell,
                            ...(unknown ? st.cellUnknown : null),
                            background: unknown
                              ? "#fdf3e7"
                              : past
                              ? "#f0f2f5"
                              : sold
                              ? "#f6d5d0"
                              : "#e9f7ef",
                            borderColor: unknown
                              ? "#e8c9a0"
                              : past
                              ? "#e2e6eb"
                              : sold
                              ? "#eab5ad"
                              : "#bfe5cf",
                          }}
                        >
                          {unknown ? "?" : ""}
                        </div>
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
