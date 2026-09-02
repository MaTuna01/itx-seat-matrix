import { useCallback, useEffect, useRef, useState } from "react";
import { api, cacheMatrix, readCachedMatrix } from "../../core/api";
import {
  acquireFix,
  geoSupported,
  gpsParams,
  hasOptedIn,
  positionBadge,
  queryPermission,
  setOptedIn,
  shouldAutoAcquire,
} from "../../core/geo";
import {
  asOfLabel,
  buildRows,
  buildSnapshotIndex,
  failureSummary,
  minutesAgo,
  nextPollLabel,
  seatWindow,
  snapshotRows,
  snapshotSeatWindow,
  summarize,
} from "../../core/format";
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

// 매트릭스 열 폭. `tableLayout: fixed`와 짝이다 — 구간 열을 균등하게 만들고,
// 정차역이 많아 다 못 들어가면 줄이는 대신 가로로 스크롤한다.
// 112 = "12-12C" + `내 자리` 태그가 잘리지 않는 폭. 태그가 없으면 72로 좁혀 그만큼을
// 구간에 넘긴다 — 한 열이 더 보인다. 38 = 세 글자 역 이름이 11pt로 들어가는 폭.
const SEAT_COL = 112;
const SEAT_COL_NARROW = 72;
const SEG_MIN = 40;

// `창원중앙`처럼 네 글자가 넘는 역은 한 열에 안 들어간다. 중간에서 접어 두 줄로 만든다 —
// CSS 줄바꿈에 맡기면 폭이 닿는 데서 끊겨 `창원중`/`앙`이 되고, 그건 읽히지 않는다.
// 열 폭을 역 이름에 맞춰 넓히는 쪽은 구간이 11개인 노선(창원→수원)에서 가로 스크롤이 배가 된다.
const wrapStop = (name) => {
  if (name.length <= 3) return [name];
  const half = Math.ceil(name.length / 2);
  return [name.slice(0, half), name.slice(half)];
};

const StopLabel = ({ name }) =>
  wrapStop(name).map((line, i) => <div key={i}>{line}</div>);
// iOS 스킨은 393pt에 갇혀 있고 body 좌우 여백이 16씩이다 (styles.js `screen`·`body`)
const BODY_W = 393 - 32;

const CELL = {
  unknown: { background: "#fdf3e7", borderColor: "#e8c9a0" },
  past: { background: "#f0f2f5", borderColor: "#e2e6eb" },
  sold: { background: "#f6d5d0", borderColor: "#eab5ad" },
  empty: { background: "#e9f7ef", borderColor: "#bfe5cf" },
  // 갭 구간 스냅샷 (→ D-57, 피그마 iOS/Cell-Snap-*). 색상 유지 + 채움 55% +
  // **점선 테두리** — 색만으로 실시간과 구분하지 않는다 (색각 안전)
  snapEmpty: { background: "rgba(233,247,239,0.55)", borderColor: "#8fcaa8", borderStyle: "dashed" },
  snapSold: { background: "rgba(246,213,208,0.55)", borderColor: "#d9a099", borderStyle: "dashed" },
};

// "07:11 조회" 배지 (피그마 iOS/Badge-AsOf)
const asOfBadge = {
  display: "inline-block",
  marginTop: 3,
  padding: "1px 7px",
  fontSize: 10,
  fontWeight: 700,
  color: "#6b7686",
  background: "#fff",
  border: "1px dashed #b7c1d1",
  borderRadius: 11,
  whiteSpace: "nowrap",
};

export default function SeatMatrix({ subscription, onSubscriptionChange, onReset, onOpenSettings }) {
  const [data, setData] = useState(null);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [onlyClear, setOnlyClear] = useState(false);
  const [selected, setSelected] = useState(null);
  // GPS 취득 상태 (D-59) — 서버 position_source와 별개. web 스킨과 같은 정책·문구를 쓴다.
  const [geoState, setGeoState] = useState(geoSupported() ? "idle" : "unsupported");
  const permissionRef = useRef("unknown");
  const lastGeoRef = useRef(null);

  useEffect(() => {
    let alive = true;
    queryPermission().then((p) => {
      if (alive) permissionRef.current = p;
    });
    return () => {
      alive = false;
    };
  }, []);

  const load = useCallback(
    async (prefetched = null) => {
      setBusy(true);
      // GPS는 이 한 번의 /matrix 조회에 동반해서만 얻는다 — 추가 조회 없음 (규칙 10 / D-13).
      let fix = prefetched;
      if (
        !fix &&
        shouldAutoAcquire({
          supported: geoSupported(),
          permission: permissionRef.current,
          optedIn: hasOptedIn(),
          last: lastGeoRef.current,
        })
      ) {
        setGeoState("acquiring");
        const r = await acquireFix({ permission: permissionRef.current });
        lastGeoRef.current = r.state;
        setGeoState(r.state);
        fix = r.fix;
      }
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
          gps: gpsParams(fix),
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
    },
    [subscription]
  );

  useEffect(() => {
    load();
  }, [load]);

  // 칩 탭 — iOS는 권한 프롬프트를 제스처 안에서만 띄운다 (D-21).
  const enableGps = useCallback(async () => {
    setGeoState("acquiring");
    const r = await acquireFix({ viaTap: true, permission: permissionRef.current });
    lastGeoRef.current = r.state;
    setGeoState(r.state);
    if (r.state === "ok") {
      setOptedIn(true);
      await load(r.fix);
    } else if (r.state === "denied") {
      setOptedIn(false);
    }
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
              <button style={st.actionRow} onClick={() => load()}>다시 시도</button>
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
  // 위치 배지는 core가 정한다 (D-59) — web 스킨과 같은 사유·탭 규칙
  const posBadge = positionBadge({
    geoState,
    positionSource: position_source,
    positionNote: data.position_note ?? null,
    stale,
  });
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

  // 판정 문구 일체 — 문장은 core가 만든다 (→ D-50)
  const summary = summarize({ verdict, data, stops, startIdx });

  // 갭 구간(지금 타고 있는 구간)의 마지막 성공 조회 (→ D-57). **표시 전용**
  const snapshotIndex = buildSnapshotIndex(data.snapshots);
  // 마지막 구간 주행 중에는 live 좌석 유니버스가 비어 있다 — 행을 스냅샷에서 만든다
  const displayRows = summary.snapshotOnly && rows.length === 0 ? snapshotRows(data.snapshots) : rows;
  const selectedSeat = displayRows.find((s) => s.key === selected);
  // 내 자리는 옮길 대상이 아니므로 바를 띄우지 않는다
  const showActionBar = !!selectedSeat && selectedSeat.key !== myKey;

  // 좌석 열 폭은 태그(`내 자리`·`END`)가 있을 때만 넓힌다. 태그가 생겼다 사라지면 폭이
  // 한 번 바뀌지만, 그건 판정 자체가 바뀌는 순간이라 조용히 어긋나 보일 일이 없다.
  const hasTag = displayRows.some((s) => s.key === myKey || s.clear_all);
  const seatCol = hasTag ? SEAT_COL : SEAT_COL_NARROW;
  const tableW = seatCol + segments.length * SEG_MIN;
  const scrolls = tableW > BODY_W;
  // 역당 폭이 이름 하나를 못 담는 지점. 7개까지는 51pt씩 돌아가 세 글자가 들어간다
  const crowdedRoute = alightIdx - boardIdx + 1 > 7;
  // 많으면 **지금 향하는 역 하나만** 라벨한다. 출발·하차까지 세 개를 남겼더니 셋 중 둘이
  // 인접한 노선(용산→광주송정: 용산·영등포)에서 그대로 겹쳤다 — 정차역 20개면 노드 간격이
  // 18pt고 역 이름은 22~33pt다. 간격으로 풀 수 있는 문제가 아니다.
  // 출발·하차는 바로 위 줄(`용산 → 광주송정 · 자유석`)이 이미 말하므로 중복이었다.
  const namedIdx = Math.min(Math.max(posIdx + 1, boardIdx), alightIdx);

  const failed = failureSummary(failedSegs, stops);

  return (
    <div style={st.screen}>
      <div style={st.navBar}>
        <button style={st.navAction} onClick={onReset}>종료</button>
        <span style={st.navTitle}>{data.train_name} {data.train_no}</span>
        <button style={{ ...st.navAction, textAlign: "right" }} onClick={onOpenSettings}>설정</button>
      </div>

      {/* 액션 바는 고정이므로 그만큼 아래를 비워야 마지막 좌석 행이 가려지지 않는다 */}
      <div style={{ ...st.body, paddingTop: 8, paddingBottom: showActionBar ? 112 : 24 }}>
        <p style={{ ...st.subtitle, margin: 0 }}>
          {data.board_at} → {data.alight_at} · 자유석
        </p>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12 }}>
          <span style={{ ...st.chip, ...(seated ? st.chipNavy : { background: "#fdf3e7", color: tk.warn, borderColor: "#f0d9b5" }) }}>
            {seated ? "착석 중" : "입석 · 자리 찾는 중"}
          </span>
          {posBadge.tappable ? (
            <button
              type="button"
              onClick={enableGps}
              style={{ ...st.chip, ...(posBadge.gps ? st.chipOK : st.chipMuted), cursor: "pointer", font: "inherit" }}
            >
              {posBadge.gps ? "GPS 실측" : "시각표 추정 · GPS 켜기"}
            </button>
          ) : (
            <span style={{ ...st.chip, ...(posBadge.gps ? st.chipOK : st.chipMuted) }}>
              {posBadge.gps ? "GPS 실측" : "시각표 추정"}
            </span>
          )}
          {delay_minutes != null && delay_minutes > 0 && (
            <span style={{ ...st.chip, background: "#fdf3e7", color: tk.warn, borderColor: "#f0d9b5" }}>
              지연 {delay_minutes}분
            </span>
          )}
          <span style={{ ...st.chip, ...(stale ? { background: "#fdecea", color: tk.danger, borderColor: "#eab5ad" } : st.chipMuted) }}>
            {stale ? "오프라인 캐시 · " : ""}{minutesAgo(data.fetched_at)} 조회
          </span>
        </div>
        {/* GPS 미사용 사유 · 켜는 안내 (D-59) */}
        {posBadge.note && <p style={{ ...st.note, margin: "6px 0 0" }}>{posBadge.note}</p>}

        {/* 노선 진행바 — 매트릭스와 같은 범위(내 구간)만 그린다 (→ D-31).
            정차역이 많으면 이름이 서로 겹치므로 **지금 향하는 역 하나만 라벨한다**
            (용산→광주송정 20개역 = 역당 18pt, 역 이름은 22~33pt).
            읽는 사람이 잃는 것은 없다 — 시작·끝은 바로 위 줄이, 진행 정도는 채워진 점이,
            지나온 구간은 아래 매트릭스의 흐린 열이 말한다. */}
        <div style={st.routeBar}>
          {stops.slice(boardIdx, alightIdx + 1).map((name, offset) => {
            const i = boardIdx + offset;
            const passed = i <= posIdx;
            const named = !crowdedRoute || i === namedIdx;
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
                  {named ? name : ""}
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
          {data.next_poll && <p style={st.nextPoll}>{nextPollLabel(data.next_poll)}</p>}
          {error && <p style={{ ...st.nextPoll, color: tk.danger }}>갱신 실패: {error}</p>}
        </section>

        {/* 판단할 것이 없으면 매트릭스를 그리지 않는다 — 조회 자체를 하지 않아 좌석이 0개다.
            빈 표를 그리면 "실제로 조회해 보니 전부 매진"으로 읽힌다 (→ D-47).
            그 판단도 core가 내린다 (summary.showMatrix) */}
        {summary.showMatrix && (
          <>
            <div style={st.filterRow}>
              {/* 스냅샷 전용(마지막 구간)에는 live 관측이 없어 필터가 무의미하다 (→ D-57) */}
              {!summary.snapshotOnly && (
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
              )}
              <span style={{ ...st.legend, marginLeft: "auto" }}>
                <i style={{ ...st.swatch, ...CELL.empty }} />빈자리
                <i style={{ ...st.swatch, ...CELL.sold, marginLeft: 4 }} />판매
                {snapshotIndex.size > 0 && (
                  <>
                    <i style={{ ...st.swatch, background: "#fff", borderColor: "#b7c1d1", borderStyle: "dashed", marginLeft: 4 }} />
                    이전 조회
                  </>
                )}
                {failedSegs.size > 0 && (
                  <>
                    <i style={{ ...st.swatch, ...CELL.unknown, marginLeft: 4 }} />조회 실패
                  </>
                )}
              </span>
              <button style={st.refreshBtn} title="지금 조회" onClick={() => load()} disabled={busy}>↻</button>
            </div>

            <div style={st.matrix}>
              <table style={{ ...st.table, minWidth: tableW }}>
                <thead>
                  <tr>
                    <th style={{ ...st.thSeat, ...st.stickySeat, width: seatCol, background: tk.surface, zIndex: 2 }}>
                      좌석
                    </th>
                    {segments.map((seg) => {
                      const snap = snapshotIndex.get(seg.idx);
                      // 스냅샷 열은 흐리지 않는다 — 지금 타고 있는 구간이고, 배지가 낡음을 말한다
                      return (
                        <th key={seg.idx} style={{ ...st.thSeg, opacity: !snap && seg.idx < startIdx ? 0.35 : 1 }}>
                          <StopLabel name={seg.from} />
                          <div>{failedSegs.has(seg.idx) ? "?" : "↓"}</div>
                          <StopLabel name={seg.to} />
                          {snap && <span style={asOfBadge}>{asOfLabel(snap.asOf)}</span>}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {displayRows.map((s) => {
                    const isMine = s.key === myKey;
                    const isSel = s.key === selected;
                    // 최상단이 "내 자리"로 바뀌었으므로 구분선으로 가른다 — 안 그러면
                    // 내 자리가 1순위 추천으로 읽힌다 (D-49)
                    const sep = myPinned && isMine ? { borderBottom: `2px solid ${tk.borderStrong}` } : null;
                    return (
                      <tr key={s.key} className="iosRow"
                        onClick={() => setSelected(isSel ? null : s.key)}
                        style={{ background: isSel ? "#eef3fb" : "transparent", cursor: "pointer" }}>
                        <td style={{
                          ...st.tdSeat, ...st.stickySeat, ...sep,
                          background: isSel ? "#eef3fb" : tk.surface,
                        }}>
                          <span style={{ fontWeight: isMine ? 800 : 600 }}>{s.car}-{s.seat_no}</span>
                          {isMine && <span style={st.mineTag}>내 자리</span>}
                          {s.clear_all && !isMine && <span style={st.endTag}>END</span>}
                        </td>
                        {segments.map((seg) => {
                          // 실패 > 스냅샷 > 지나온 구간 > 실시간 순으로 본다.
                          // 스냅샷 셀은 live cells가 아니라 **스냅샷 관측**을 읽는다 — 갭 구간의
                          // live 셀은 조회하지 않은 채움값(판매됨)이라 그대로 그리면 거짓이다 (D-57)
                          const unknown = failedSegs.has(seg.idx);
                          const snap = !unknown && snapshotIndex.get(seg.idx);
                          const past = seg.idx < startIdx;
                          const sold = snap ? snap.bySeat.get(s.key) ?? true : s.cells[seg.idx];
                          const look = unknown
                            ? CELL.unknown
                            : snap
                            ? CELL[sold ? "snapSold" : "snapEmpty"]
                            : past
                            ? CELL.past
                            : sold
                            ? CELL.sold
                            : CELL.empty;
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
            {/* 오른쪽이 잘린 것만으로는 "밀 수 있다"가 안 읽힌다 — 못 본 구간을
                안 판 자리로 착각할 수 있어서 글자로 말한다 */}
            {scrolls && <p style={st.scrollHint}>옆으로 밀면 나머지 구간 →</p>}
          </>
        )}
      </div>

      {/* ── 좌석 선택 액션 바 (D-15 전이 입력) ── */}
      {showActionBar ? (
        <div style={st.actionBar} className="iosActionBar" role="group" aria-label="선택한 좌석">
          <button style={st.actionClose} aria-label="선택 해제" onClick={() => setSelected(null)}>
            ✕
          </button>
          <div style={{ minWidth: 0 }}>
            <b style={{ fontSize: 15 }}>{selectedSeat.car}-{selectedSeat.seat_no}</b>
            {/* 문장은 core가 만든다 — 지금 팔린 좌석에 "…까지 빈 좌석"을 찍으면
                판정 카드와 다른 말을 하게 된다 (→ D-52 ⑥) */}
            <div style={{ fontSize: 13, color: tk.textMuted }}>
              <Segs
                parts={
                  summary.snapshotOnly
                    ? snapshotSeatWindow(selectedSeat.key, snapshotIndex)
                    : seatWindow(selectedSeat, { stops, startIdx, alightIdx })
                }
              />
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
