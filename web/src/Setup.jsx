import { useState } from "react";
import { api } from "./api";
import { st } from "./styles";

// 탑승 등록 화면 (PLAN 10절). 등록 시 입석/착석을 고르고, 착석이면 좌석을 지정한다 (D-15).
// Phase 1은 목업 어댑터라 열차/역이 고정이지만, 값은 하드코딩하지 않고 입력으로 받는다 (원칙 1).
const today = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });

export default function Setup({ onCreated, onOpenSettings }) {
  const [form, setForm] = useState({
    train_no: "1004",
    date: today(),
    board_at: "",
    alight_at: "",
  });
  const [seated, setSeated] = useState(false);
  const [seat, setSeat] = useState({ my_car: "", my_seat_no: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = { ...form, status: seated ? "SEATED" : "STANDING" };
      if (seated) {
        payload.my_car = Number(seat.my_car);
        payload.my_seat_no = seat.my_seat_no;
      }
      onCreated(await api.createSubscription(payload));
    } catch (err) {
      setError(err.message);
    } finally {
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

        <form onSubmit={submit}>
          <div style={st.segRow}>
            <div style={{ flex: 1 }}>
              <label style={st.label} htmlFor="train_no">열차번호</label>
              <input id="train_no" style={st.input} value={form.train_no} onChange={set("train_no")} required />
            </div>
            <div style={{ flex: 1.4 }}>
              <label style={st.label} htmlFor="date">운행일</label>
              <input id="date" style={st.input} type="date" value={form.date} onChange={set("date")} required />
            </div>
          </div>

          <div style={st.segRow}>
            <div style={{ flex: 1 }}>
              <label style={st.label} htmlFor="board_at">탑승역</label>
              <input id="board_at" style={st.input} value={form.board_at} onChange={set("board_at")} required />
            </div>
            <div style={{ flex: 1 }}>
              <label style={st.label} htmlFor="alight_at">하차역</label>
              <input id="alight_at" style={st.input} value={form.alight_at} onChange={set("alight_at")} required />
            </div>
          </div>

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
              <div style={{ flex: 1 }}>
                <label style={st.label} htmlFor="my_car">호차</label>
                <input
                  id="my_car" style={st.input} type="number" min="1" value={seat.my_car}
                  onChange={(e) => setSeat({ ...seat, my_car: e.target.value })} required
                />
              </div>
              <div style={{ flex: 1 }}>
                <label style={st.label} htmlFor="my_seat_no">좌석번호</label>
                <input
                  id="my_seat_no" style={st.input} placeholder="7A" value={seat.my_seat_no}
                  onChange={(e) => setSeat({ ...seat, my_seat_no: e.target.value })} required
                />
              </div>
            </div>
          )}

          <button style={st.primaryBtn} type="submit" disabled={busy}>
            {busy ? "…" : "등록하고 매트릭스 보기"}
          </button>
        </form>

        {error && <div style={st.error}>{error}</div>}
      </div>
    </div>
  );
}
