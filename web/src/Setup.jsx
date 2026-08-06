import { useEffect, useState } from "react";
import { api } from "./api";
import StationPicker from "./StationPicker";
import { st } from "./styles";

// 탑승 등록 (PLAN 10절 '열차 선택 화면', D-25).
// 코레일 앱과 같은 순서로 좁혀 들어간다:
//   출발/도착역 선택 → 운행일 + 검색 기준 시각(하한) → 열차 선택 → 입석/착석 → 등록
// 오타가 곧 404고 사용자는 정식 역명을 모르므로, **확정되는 값은 언제나 목록에서 고른 역**이다.
// 실연동으로 역이 282개가 되면서 통짜 드롭다운은 성립하지 않게 됐다 —
// StationPicker가 타이핑으로 목록을 좁혀준다 (D-32).

const nowParts = () => {
  const fmt = (opts) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", ...opts });
  return {
    date: fmt({ dateStyle: "short" }).format(new Date()),
    time: fmt({ hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date()),
  };
};

const hhmm = (iso) =>
  new Date(iso).toLocaleTimeString("ko-KR", {
    timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false,
  });

export default function Setup({ onCreated, onOpenSettings }) {
  const [stations, setStations] = useState([]);
  const [query, setQuery] = useState({ from: "", to: "", ...nowParts() });
  const [trains, setTrains] = useState(null); // null = 아직 검색 안 함
  const [picked, setPicked] = useState(null);
  const [seated, setSeated] = useState(false);
  const [seat, setSeat] = useState({ my_car: "", my_seat_no: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // 역은 비워 둔 채 시작한다. 목업(6개) 시절엔 노선 양 끝을 기본값으로 넣었지만,
    // 실테이블 282개에서 가나다순 처음/끝은 아무 의미가 없다 — 어차피 둘 다 바꿔야 한다.
    // 자주 쓰는 구간을 채우는 것은 프리셋의 일이다 (Phase 4).
    api.stations().then(setStations).catch((err) => setError(err.message));
  }, []);

  const set = (key) => (e) => setQuery({ ...query, [key]: e.target.value });

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

  return (
    <div style={{ ...st.page, paddingTop: 32 }}>
      <div style={st.card}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <h1 style={{ ...st.h1, flex: 1 }}>탑승 등록</h1>
          <button type="button" style={st.ghostBtn} onClick={onOpenSettings}>설정</button>
        </div>
        <p style={st.dim}>등록하면 정차역 도착 전에 자동으로 좌석을 다시 조회합니다.</p>

        {/* ── 1단계: 구간 + 운행일 + 검색 기준 시각 ── */}
        <form onSubmit={search}>
          <div style={st.segRow}>
            <div style={st.segCol}>
              <label style={st.label} htmlFor="from">출발역</label>
              <StationPicker
                id="from" stations={stations} value={query.from}
                onChange={(name) => setQuery((q) => ({ ...q, from: name }))}
                disabled={!stations.length} required
              />
            </div>
            <div style={st.segCol}>
              <label style={st.label} htmlFor="to">도착역</label>
              <StationPicker
                id="to" stations={stations} value={query.to}
                onChange={(name) => setQuery((q) => ({ ...q, to: name }))}
                disabled={!stations.length} required
              />
            </div>
          </div>

          <div style={st.segRow}>
            <div style={{ ...st.segCol, flex: 1.4 }}>
              <label style={st.label} htmlFor="date">운행일</label>
              <input id="date" style={st.input} type="date" value={query.date} onChange={set("date")} required />
            </div>
            <div style={st.segCol}>
              <label style={st.label} htmlFor="time">이 시각 이후</label>
              <input id="time" style={st.input} type="time" value={query.time} onChange={set("time")} />
            </div>
          </div>

          <button style={st.primaryBtn} type="submit" disabled={busy || !stations.length}>
            {busy && trains === null ? "…" : "열차 조회"}
          </button>
        </form>

        {/* ── 2단계: 열차 선택 ── */}
        {trains !== null && (
          <>
            <label style={st.label}>
              열차 선택 {trains.length > 0 && `(${trains.length}편)`}
            </label>
            {trains.length === 0 ? (
              <p style={st.dim}>조건에 맞는 열차가 없습니다 · 시각을 앞당기거나 구간을 확인하세요.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {trains.map((t) => {
                  const on = picked?.train_no === t.train_no;
                  return (
                    <button
                      key={t.train_no}
                      type="button"
                      onClick={() => setPicked(t)}
                      style={{
                        ...st.card,
                        padding: "10px 12px",
                        textAlign: "left",
                        cursor: "pointer",
                        borderColor: on ? "#1a3a6b" : "#e2e6eb",
                        background: on ? "#eef3fb" : "#fff",
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                      }}
                    >
                      <span style={{ ...st.badge, background: on ? "#1a3a6b" : "#6b7686" }}>
                        {t.train_name}
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 700 }}>{t.train_no}</span>
                      <span style={{ ...st.dim, marginLeft: "auto", fontVariantNumeric: "tabular-nums" }}>
                        {hhmm(t.dep_time)} → {hhmm(t.arr_time)}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </>
        )}

        {/* ── 3단계: 지금 상태 ── */}
        {picked && (
          <>
            <label style={st.label}>지금 상태</label>
            <div style={st.toggleRow}>
              {[false, true].map((value) => (
                <button
                  key={String(value)}
                  type="button"
                  onClick={() => setSeated(value)}
                  style={{
                    ...st.filterBtn,
                    flex: 1,
                    background: seated === value ? "#1a3a6b" : "#fff",
                    color: seated === value ? "#fff" : "#1a3a6b",
                  }}
                >
                  {value ? "착석 (자리 지정)" : "입석 (자리 찾는 중)"}
                </button>
              ))}
            </div>

            {seated && (
              <div style={st.segRow}>
                <div style={st.segCol}>
                  <label style={st.label} htmlFor="my_car">호차</label>
                  <input
                    id="my_car" style={st.input} type="number" min="1" value={seat.my_car}
                    onChange={(e) => setSeat({ ...seat, my_car: e.target.value })} required
                  />
                </div>
                <div style={st.segCol}>
                  <label style={st.label} htmlFor="my_seat_no">좌석번호</label>
                  <input
                    id="my_seat_no" style={st.input} placeholder="7A" value={seat.my_seat_no}
                    onChange={(e) => setSeat({ ...seat, my_seat_no: e.target.value })} required
                  />
                </div>
              </div>
            )}

            <button
              style={st.primaryBtn}
              onClick={register}
              disabled={busy || (seated && (!seat.my_car || !seat.my_seat_no))}
            >
              {busy ? "…" : `${picked.train_no} 등록하고 매트릭스 보기`}
            </button>
          </>
        )}

        {error && <div style={st.error}>{error}</div>}
      </div>
    </div>
  );
}
