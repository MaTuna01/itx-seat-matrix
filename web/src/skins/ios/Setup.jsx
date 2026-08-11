import { useEffect, useState } from "react";
import { api } from "../../core/api";
import { MAX_FAVORITES, canSave, routeLabel } from "../../core/favorites";
import StationPicker from "./StationPicker";
import { st, tk } from "./styles";

// 피그마 ios `21:35`(02 탑승 등록) · `23:45`(03 역 검색) · `25:60`(04 열차 선택) ·
// `25:105`(05 지금 상태).
//
// **네 화면이지만 라우팅은 하나다** — 공유 `phase`는 `setup` 그대로고 하위 단계는 여기의
// 상태다 (→ D-50 결정 ③). web 스킨은 같은 내용을 카드 하나에 세로로 쌓는다.
//
// 코레일 앱과 같은 순서로 좁혀 들어간다:
//   출발/도착역 → 운행일 + 검색 기준 시각(하한) → 열차 선택 → 입석/착석 → 등록
// 오타가 곧 404고 사용자는 정식 역명을 모르므로, **확정되는 값은 언제나 목록에서 고른 역**이다.

const nowParts = () => {
  const fmt = (opts) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", ...opts });
  return {
    date: fmt({ dateStyle: "short" }).format(new Date()),
    time: fmt({ hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date()),
  };
};

// 직전에 탄 구간. "탑승 종료"는 하드 삭제가 아니라 active=0이므로(api/subscriptions.py)
// 지난 구독이 그대로 남아 있고, 목록은 created_at DESC다 — 앞쪽이 최근이다.
// 역 목록에 없는 이름은 건너뛴다: 채워 놓아도 검색이 실패해 빈 칸보다 나쁘다.
// 운행일·시각은 프리필하지 않는다 — 어제 날짜가 들어가 있는 편이 훨씬 나쁜 버그다.
export function lastRoute(subs, stations) {
  const names = new Set(stations.map((s) => s.name));
  const last = subs.find((s) => names.has(s.board_at) && names.has(s.alight_at));
  return last ? { from: last.board_at, to: last.alight_at } : null;
}

const hhmm = (iso) =>
  new Date(iso).toLocaleTimeString("ko-KR", {
    timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false,
  });

const dateLabel = (ymd) =>
  new Date(`${ymd}T00:00:00+09:00`).toLocaleDateString("ko-KR", {
    timeZone: "Asia/Seoul", month: "long", day: "numeric", weekday: "short",
  });

export default function Setup({ onCreated, onOpenSettings }) {
  const [stations, setStations] = useState([]);
  const [query, setQuery] = useState({ from: "", to: "", ...nowParts() });
  const [favs, setFavs] = useState([]);
  const [trains, setTrains] = useState(null); // null = 아직 검색 안 함
  const [picked, setPicked] = useState(null);
  const [seated, setSeated] = useState(false);
  const [seat, setSeat] = useState({ my_car: "", my_seat_no: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  // 하위 단계 — 03 역 검색 시트를 어느 칸에 대해 열었는가 ("from" | "to" | null)
  const [picking, setPicking] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      // 직전 구간·즐겨찾기 조회는 **실패해도 되는 부가 기능**이다 — 여기서 막히면
      // 탑승 등록 자체를 못 한다. 역 목록만 필수로 두고 나머지의 실패는 삼킨다.
      const [list, past, saved] = await Promise.all([
        api.stations(),
        api.subscriptions({ activeOnly: false }).catch(() => []),
        api.presets().catch(() => []),
      ]);
      if (!alive) return;
      setStations(list);
      setFavs(saved);
      const route = lastRoute(past, list);
      // 조회가 늦게 도착했는데 사용자가 이미 역을 골랐다면 덮어쓰지 않는다.
      if (route) setQuery((q) => (q.from || q.to ? q : { ...q, ...route }));
    })().catch((err) => {
      if (alive) setError(err.message);
    });
    return () => {
      alive = false;
    };
  }, []);

  const set = (key) => (e) => setQuery({ ...query, [key]: e.target.value });

  // ── 즐겨찾기 노선 (D-56) ──
  const applyFav = (p) =>
    setQuery((q) => ({ ...q, from: p.from_station, to: p.to_station }));

  const saveFav = async () => {
    setError(null);
    try {
      const route = { from_station: query.from, to_station: query.to };
      const created = await api.createPreset({ name: routeLabel(route), ...route });
      setFavs((prev) => [...prev, created]);
    } catch (err) {
      setError(err.message);
    }
  };

  const removeFav = async (id) => {
    setError(null);
    try {
      await api.deletePreset(id);
      setFavs((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      setError(err.message);
    }
  };

  const search = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setPicked(null);
    try {
      setTrains(await api.searchTrains(query));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const register = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        train_no: picked.train_no,
        date: query.date,
        board_at: query.from,
        alight_at: query.to,
        status: seated ? "SEATED" : "STANDING",
      };
      if (seated) {
        payload.my_car = Number(seat.my_car);
        payload.my_seat_no = seat.my_seat_no;
      }
      onCreated(await api.createSubscription(payload));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  // ── 03 역 검색 (모달 시트) ──
  if (picking) {
    return (
      <StationPicker
        title={picking === "from" ? "출발역" : "도착역"}
        stations={stations}
        value={query[picking]}
        onPick={(name) => {
          setQuery((q) => ({ ...q, [picking]: name }));
          setPicking(null);
        }}
        onClose={() => setPicking(null)}
      />
    );
  }

  // ── 04 열차 선택 (+ 05 지금 상태 바텀시트) ──
  if (trains !== null) {
    return (
      <div style={st.screen}>
        <div style={st.navBar}>
          <button style={st.navAction} onClick={() => { setTrains(null); setPicked(null); }}>
            ‹ 구간
          </button>
          <span style={st.navTitle}>열차 선택</span>
          <span style={{ minWidth: 64 }} />
        </div>

        <div style={st.body}>
          <p style={{ ...st.subtitle, margin: 0 }}>
            {dateLabel(query.date)} · {query.from} → {query.to}
            {trains.length > 0 && ` · ${trains.length}편`}
          </p>

          {trains.length === 0 ? (
            <p style={{ ...st.footnote, padding: 0 }}>
              조건에 맞는 열차가 없습니다 · 시각을 앞당기거나 구간을 확인하세요.
            </p>
          ) : (
            <div style={st.group}>
              {trains.flatMap((t, i) => [
                ...(i === 0 ? [] : [<div key={`s${t.train_no}`} style={st.sep} />]),
                <button
                  key={t.train_no}
                  className="iosRow"
                  style={st.trainRow}
                  onClick={() => setPicked(t)}
                >
                  <span
                    style={{
                      ...st.trainBadge,
                      background: picked?.train_no === t.train_no ? tk.brandNavy : tk.textMuted,
                    }}
                  >
                    {t.train_name}
                  </span>
                  <span style={st.trainNo}>{t.train_no}</span>
                  <span style={st.trainTime}>{hhmm(t.dep_time)} → {hhmm(t.arr_time)}</span>
                </button>,
              ])}
            </div>
          )}

          <p style={{ ...st.footnote, padding: 0 }}>
            자유석은 좌석이 지정되지 않습니다. 열차를 고르면 지금 상태(입석/착석)를 물어봅니다.
          </p>
          {error && <p style={{ ...st.footnoteError, padding: 0 }}>{error}</p>}
        </div>

        {/* ── 05 지금 상태 (바텀시트) ── */}
        {picked && (
          <NowStateSheet
            train={picked}
            route={`${query.from} → ${query.to}`}
            seated={seated} setSeated={setSeated}
            seat={seat} setSeat={setSeat}
            busy={busy}
            onClose={() => setPicked(null)}
            onSubmit={register}
          />
        )}
      </div>
    );
  }

  // ── 02 탑승 등록 ──
  return (
    <form style={st.screen} onSubmit={search}>
      <div style={st.navBar}>
        <span style={{ minWidth: 64 }} />
        <span style={st.navTitle}>탑승 등록</span>
        <button type="button" style={{ ...st.navAction, textAlign: "right" }} onClick={onOpenSettings}>
          설정
        </button>
      </div>

      <div style={st.body}>
        {/* ── 즐겨찾기 노선 (D-56) — 칩 탭 = 구간 채움, × = 삭제 ── */}
        {(favs.length > 0 || canSave(favs, query.from, query.to)) && (
          <>
            <div style={st.favLabelRow}>
              <span style={{ fontSize: 13, color: tk.textMuted }}>즐겨찾기 노선</span>
              <span style={st.favCount}>{favs.length}/{MAX_FAVORITES}</span>
            </div>
            <div style={st.favChips}>
              {favs.map((p) => (
                <span key={p.id} style={st.favChip}>
                  <button type="button" style={st.favRoute} onClick={() => applyFav(p)}>
                    {routeLabel(p)}
                  </button>
                  <button
                    type="button" style={st.favDel}
                    aria-label={`${routeLabel(p)} 삭제`}
                    onClick={() => removeFav(p.id)}
                  >
                    ×
                  </button>
                </span>
              ))}
              {canSave(favs, query.from, query.to) && (
                <button type="button" style={st.favAddChip} onClick={saveFav}>
                  + 현재 구간 저장
                </button>
              )}
            </div>
          </>
        )}

        <p style={st.sectionLabel}>구간</p>
        <div style={st.group}>
          <button type="button" className="iosRow" style={st.actionRow}
            disabled={!stations.length} onClick={() => setPicking("from")}>
            <span style={{ ...st.rowLabel, color: tk.textPrimary }}>출발역</span>
            <span style={query.from ? st.rowValue : { ...st.rowValue, color: tk.textFaint }}>
              {query.from || "선택"}
            </span>
          </button>
          <div style={st.sep} />
          <button type="button" className="iosRow" style={st.actionRow}
            disabled={!stations.length} onClick={() => setPicking("to")}>
            <span style={{ ...st.rowLabel, color: tk.textPrimary }}>도착역</span>
            <span style={query.to ? st.rowValue : { ...st.rowValue, color: tk.textFaint }}>
              {query.to || "선택"}
            </span>
          </button>
        </div>

        <p style={st.sectionLabel}>운행일 · 검색 기준 시각</p>
        <div style={st.group}>
          <div style={st.fieldRow}>
            <label style={st.fieldLabel} htmlFor="date">운행일</label>
            <input id="date" style={st.fieldInput} type="date" value={query.date}
              onChange={set("date")} required />
          </div>
          <div style={st.sep} />
          <div style={st.fieldRow}>
            <label style={st.fieldLabel} htmlFor="time">이 시각 이후</label>
            <input id="time" style={st.fieldInput} type="time" value={query.time}
              onChange={set("time")} />
          </div>
        </div>

        <p style={st.footnote}>
          등록하면 정차역 도착 전에 자동으로 좌석을 다시 조회하고, 앉을 자리가 생기면 알림을 보냅니다.
        </p>
        {error && <p style={st.footnoteError}>{error}</p>}
      </div>

      <div style={st.bottomBar}>
        <button type="submit" style={st.primaryBtn}
          disabled={busy || !stations.length || !query.from || !query.to}>
          {busy ? "…" : "열차 조회"}
        </button>
      </div>
    </form>
  );
}

// 05 지금 상태 — 열차를 고르면 올라오는 바텀시트.
// 착석을 고르면 좌석을 받아야 등록할 수 있다.
function NowStateSheet({ train, route, seated, setSeated, seat, setSeat, busy, onClose, onSubmit }) {
  return (
    <>
      <div style={st.sheetBackdrop} onClick={onClose} />
      <div style={{ ...st.sheet, top: "auto", height: "auto", borderRadius: "12px 12px 0 0" }}
        role="dialog" aria-label="지금 상태">
        <div style={st.grabber} />
        <div style={{ padding: "12px 16px 0" }}>
          <p style={{ ...st.title, fontSize: 22 }}>지금 상태</p>
          <p style={{ ...st.subtitle, marginTop: 4 }}>{train.train_name} {train.train_no} · {route}</p>

          <div style={{ ...st.segment, marginTop: 16 }}>
            {[false, true].map((value) => (
              <button
                key={String(value)} type="button" onClick={() => setSeated(value)}
                style={{ ...st.segmentItem, ...(seated === value ? st.segmentItemOn : null) }}
                aria-pressed={seated === value}
              >
                {value ? "착석 (자리 지정)" : "입석 (자리 찾는 중)"}
              </button>
            ))}
          </div>

          {seated && (
            <div style={st.group}>
              <div style={st.fieldRow}>
                <label style={st.fieldLabel} htmlFor="my_car">호차</label>
                <input id="my_car" style={st.fieldInput} type="number" min="1" inputMode="numeric"
                  value={seat.my_car} onChange={(e) => setSeat({ ...seat, my_car: e.target.value })} required />
              </div>
              <div style={st.sep} />
              <div style={st.fieldRow}>
                <label style={st.fieldLabel} htmlFor="my_seat_no">좌석번호</label>
                <input id="my_seat_no" style={st.fieldInput} placeholder="7A" value={seat.my_seat_no}
                  onChange={(e) => setSeat({ ...seat, my_seat_no: e.target.value })} required />
              </div>
            </div>
          )}

          <p style={{ ...st.footnote, padding: 0 }}>
            착석을 고르면 그 자리가 팔리는 순간 알림을 보냅니다. 자리를 옮기면 매트릭스에서 좌석을
            눌러 갱신하세요.
          </p>
        </div>

        <div style={st.bottomBar}>
          <button type="button" style={st.primaryBtn} onClick={onSubmit}
            disabled={busy || (seated && (!seat.my_car || !seat.my_seat_no))}>
            {busy ? "…" : `${train.train_no} 등록하고 매트릭스 보기`}
          </button>
        </div>
      </div>
    </>
  );
}
