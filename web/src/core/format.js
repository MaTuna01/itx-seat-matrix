// 판정 요약 문구는 **여기서만** 만든다 (→ D-50).
//
// 스킨이 각자 `move_to` / `move_to_later` / `clear_from_idx` / `decision_needed`를 해석해
// 문장을 조립하면 web과 iOS가 반드시 갈린다. 그러면 뒤처진 쪽이 "못생긴" 상태가 아니라
// **"틀린 정보를 보여주는" 상태**가 되고, 그건 D-43 결정 ③이 경고한 실패다 —
// 판정 규칙이 달라진 것을 디자인 차이로 흘려보내는 것.
//
// 반환은 **문장 조각 배열** `[{ t, em }]` 이다. 문장은 core가 만들고, 강조를 어떻게 그릴지만
// 스킨이 정한다. 글리프(⚠ 같은)도 넣지 않는다 — 그건 스킨의 어휘다.
//
// **판정 자체는 서버(domain/verdict.py)가 계산한 verdict를 그대로 신뢰한다.**
// 여기서 계산하는 clear_until은 행 정렬·END 태그용 표시 값일 뿐이다.

export const seatKey = (s) => `${s.car}-${s.seat_no}`;

export function minutesAgo(iso, now = Date.now()) {
  const m = Math.floor((now - new Date(iso).getTime()) / 60000);
  return m <= 0 ? "방금" : `${m}분 전`;
}

// verdict.py의 clear_until과 같은 규칙 (표시 전용)
export function clearUntil(seat, startIdx, alightIdx) {
  let until = startIdx;
  for (let i = startIdx; i < alightIdx; i++) {
    if (seat.cells[i]) break;
    until = i + 1;
  }
  return until;
}

// "언제부터 어디까지" — 좌석 라벨에 반드시 붙는다. 빠지면 지금 앉을 수 있다고 오해하고,
// 그건 추천을 안 하느니만 못하다 (D-46 결정 ③)
export function seatRange(rec, { stops, alightAt }) {
  const to = rec.clear_all ? alightAt : stops[rec.clear_until_idx];
  return `${stops[rec.clear_from_idx]}부터 ${to}까지`;
}

// 매트릭스 행 순서 (→ D-49). 스킨이 각자 정렬하면 web과 iOS가 다른 순서를 보여주게 되고,
// 그건 문구가 갈리는 것과 같은 종류의 사고다 — 그래서 여기서 한 번만 정한다.
//
// 순서: 내 자리(착석 시) → clear_until 내림차순 → 내 호차 근접순 → 좌석번호.
// `myPinned`는 최상단 행의 뜻이 "가장 오래 앉을 수 있는 좌석"에서 "내 자리"로 바뀌었음을
// 스킨에 알린다 — 구분선 없이 그리면 내 자리가 1순위 추천으로 읽힌다.
export function buildRows({ seats, startIdx, alightIdx, seated, myCar, myKey, onlyClear }) {
  const enriched = seats.map((s) => {
    const until = clearUntil(s, startIdx, alightIdx);
    return { ...s, key: seatKey(s), clear_until: until, clear_all: until >= alightIdx };
  });
  const sorted = enriched.sort(
    (a, b) =>
      b.clear_until - a.clear_until ||
      (seated ? Math.abs(a.car - myCar) - Math.abs(b.car - myCar) : a.car - b.car) ||
      a.seat_no.localeCompare(b.seat_no)
  );
  // 내 자리는 필터 대상이 아니다 (→ D-49). 필터를 켜는 상황이 곧 "내 자리가 팔려서 대안을
  // 찾는" 상황인데, 내 자리는 clear_all이 아니라 바로 그때 화면에서 사라진다 — 비교 기준이
  // 없어지므로 대안이 나은지 판단할 수가 없다.
  const visible = onlyClear ? sorted.filter((s) => s.clear_all || s.key === myKey) : sorted;
  if (!seated || !myKey) return { rows: visible, myPinned: false };

  const i = visible.findIndex((s) => s.key === myKey);
  // 내 좌석이 매트릭스에 없을 수 있다 — 잔여 전 구간이 팔리면 유니버스에서 사라진다 (D-18).
  // 그 경우는 판정이 SOLD_FROM으로 따로 답하므로 여기서는 조용히 넘어간다.
  if (i < 0) return { rows: visible, myPinned: false };
  const rows = i === 0 ? visible : [visible[i], ...visible.slice(0, i), ...visible.slice(i + 1)];
  return { rows, myPinned: rows.length > 1 };
}

const seg = (t, em) => (em ? { t, em: true } : { t });

export function summarize({ verdict, data, stops, startIdx }) {
  const alightAt = data.alight_at;
  const range = (r) => seatRange(r, { stops, alightAt });

  const bestMove = verdict.move_to.find((m) => m.clear_all);
  const clearAllCount = verdict.move_to.filter((m) => m.clear_all).length;

  // 지금은 못 앉지만 몇 정거장 뒤부터 앉을 수 있는 좌석 (D-46).
  // 두 목록을 합치지 않는다 — 합치면 1순위가 "지금 못 앉는 자리"가 될 수 있다.
  const laterList = verdict.move_to_later || [];
  const laterBest = laterList[0];
  // 지금 앉을 수 있는 좌석이 하나도 없을 때만 요약 문구를 지연 착석으로 대체한다.
  // 앉을 수 있으면 그냥 앉으면 되므로 그쪽이 항상 우선이다.
  const laterOnly = verdict.move_to.length === 0 && !!laterBest;

  const transfer = [seg("남은 구간 잔여 좌석 없음 · "), seg("지하철 환승", true), seg("이 나을 수 있음")];

  // 이용 구간의 마지막 구간을 달리는 중 — 팔 수 있는 구간이 없어 조회도 하지 않는다.
  // 여기서 빈 매트릭스를 그대로 그리면 "전부 매진"으로 읽힌다 (→ D-47)
  if (verdict.decision_needed === false) {
    return {
      chip: null,
      status: { text: `곧 ${alightAt} 도착`, tone: "ok" },
      detail: [seg("이동 판단 불필요 · 남은 구간에 살 수 있는 좌석이 없습니다")],
      later: null,
      showStandButton: false,
      showMatrix: false,
    };
  }

  const seated = data.sub_status === "SEATED";
  // 지연 착석 목록은 지금 앉을 수 있는 좌석과 **분리해서** 보여준다 (D-46).
  // 섞으면 "지금 앉을 수 있는 자리"인지 구분이 사라진다.
  const later =
    laterList.length > 0 && !verdict.all_sold_after_current
      ? {
          label: verdict.move_to.length > 0 ? "지금은 아니지만 뒤 구간에 빈 자리" : "빈 자리",
          // 그룹 1순위의 출발역 — 푸시 제목이 쓰는 값과 같다
          fromStation: stops[laterBest.clear_from_idx],
          seats: laterList.map((r) => `${r.car}-${r.seat_no}(${range(r)})`).join(", "),
        }
      : null;

  if (seated) {
    const myStatus = {
      CLEAR_ALL: { text: `${alightAt}까지 안전`, tone: "ok" },
      SOLD_FROM: { text: `${verdict.my_seat_sold_from}부터 판매됨`, tone: "danger" },
      UNKNOWN: { text: "상태 확인 불가", tone: "muted" },
    }[verdict.my_seat_status] ?? null;

    let detail;
    // 환승 권유는 매진일 때만 — clear_until로 판정하면 "시작 구간만 매진"이 뒤집힌다 (D-45)
    if (verdict.all_sold_after_current) detail = transfer;
    else if (verdict.my_seat_status === "CLEAR_ALL")
      detail = [seg("이동 불필요 · 자리가 팔리면 알림으로 알려드립니다")];
    else if (bestMove)
      detail = [
        seg(`${stops[startIdx]} 도착 전 이동 권장 → `),
        seg(`${bestMove.car}호차 ${bestMove.seat_no}`, true),
        ...(clearAllCount > 1 ? [seg(` 외 ${clearAllCount - 1}석이 ${alightAt}까지 빈 좌석`)] : []),
      ];
    else if (laterOnly)
      detail = [
        seg("지금 옮길 자리는 없음 · "),
        seg(stops[laterBest.clear_from_idx], true),
        seg("부터 "),
        seg(`${laterBest.car}호차 ${laterBest.seat_no}`, true),
        seg(` (${range(laterBest)})`),
      ];
    else detail = [seg("끝까지 비는 좌석 없음 · 아래에서 최장 구간 좌석 확인")];

    return {
      chip: { text: `내 자리 ${data.my_car}호차 ${data.my_seat_no}`, tone: "navy" },
      status: myStatus,
      detail,
      later,
      showStandButton: true,
      showMatrix: true,
    };
  }

  // ── 입석 ──
  let status;
  if (verdict.all_sold_after_current) status = { text: "앉을 좌석 없음", tone: "danger" };
  // 기준역은 stops[start]다 — 한 역 뒤를 가리키면 그 역에서 앉을 기회를 놓친다 (D-47)
  else if (bestMove) status = { text: `${stops[startIdx]}부터 착석 가능`, tone: "ok" };
  // 지금은 못 앉는다 — "일부 구간만 착석 가능"보다 **어느 역부터인지**가 정보다
  else if (laterOnly)
    status = { text: `${stops[laterBest.clear_from_idx]}부터 착석 가능`, tone: "warn" };
  else status = { text: "일부 구간만 착석 가능", tone: "warn" };

  let detail;
  if (verdict.all_sold_after_current) detail = transfer;
  else if (bestMove)
    detail = [
      seg("추천 "),
      seg(`${bestMove.car}호차 ${bestMove.seat_no}`, true),
      seg(` (${alightAt}까지 빈 좌석)`),
      ...(clearAllCount > 1 ? [seg(` 외 ${clearAllCount - 1}석`)] : []),
      seg(' · 좌석을 선택해 "이 자리에 앉음"을 누르면 이후 알림이 그 자리 기준으로 옵니다'),
    ];
  else if (laterOnly)
    detail = [
      seg("추천 "),
      seg(`${laterBest.car}호차 ${laterBest.seat_no}`, true),
      seg(` (${range(laterBest)}) · 미리 그 호차로 이동해 대기하세요`),
    ];
  else detail = [seg("끝까지 비는 좌석은 없음 · 아래에서 최장 구간 좌석을 골라 앉으세요")];

  return { chip: { text: "입석", tone: "warn" }, status, detail, later, showStandButton: false, showMatrix: true };
}

// 조회 실패 요약 (→ D-48). 매진이 아니라 **모른다**는 것을 문장으로도 말한다 —
// "수원까지 확인됨"이 정확한 답이고, 그 뒤는 확인하지 못했을 뿐이다.
export function failureSummary(failedSegIdxs, stops) {
  const idxs = [...failedSegIdxs].sort((a, b) => a - b);
  if (idxs.length === 0) return null;
  const list = idxs.map((i) => `${stops[i]}→${stops[i + 1]}`).join(", ");
  return [seg(`${list} 구간 조회 실패 · 그 구간은 `), seg("매진이 아니라 알 수 없음", true), seg("입니다")];
}
