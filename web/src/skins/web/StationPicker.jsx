import { useEffect, useMemo, useRef, useState } from "react";
import { filterStations } from "../../core/hangul";
import { st } from "./styles";

// 역 선택 콤보박스 (D-32). 타이핑은 **목록을 좁히기만** 하고,
// 확정되는 값은 언제나 목록에서 고른 역이다 — 자유 입력이 그대로 API로 가지 않는다.
// D-25("역은 고르는 것이지 입력하는 것이 아니다")의 확장이지 반전이 아니다.
export default function StationPicker({ id, stations, value, onChange, disabled, required }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [active, setActive] = useState(0); // 키보드로 이동 중인 항목
  const boxRef = useRef(null);
  const listRef = useRef(null);

  const matches = useMemo(
    () => (open ? filterStations(stations, text) : []),
    [open, stations, text]
  );

  // 목록이 바뀌면 선택 위치를 처음으로 되돌린다 — 안 하면 범위 밖을 가리킨다
  useEffect(() => setActive(0), [text]);

  // 키보드로 이동한 항목이 화면 밖이면 따라 스크롤
  useEffect(() => {
    listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const commit = (station) => {
    if (station) onChange(station.name);
    setOpen(false);
    setText("");
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); // 커서가 글자 끝으로 튀는 것 방지
      if (!open) return setOpen(true);
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => Math.min(Math.max(i + step, 0), matches.length - 1));
    } else if (e.key === "Enter") {
      if (open) {
        e.preventDefault(); // 폼이 제출되기 전에 선택을 먼저 확정한다
        commit(matches[active]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setText("");
    }
  };

  return (
    <div ref={boxRef} style={st.pickerWrap}>
      <input
        id={id}
        style={st.input}
        // 열려 있는 동안만 입력값을 보여준다. 닫히면 확정된 역 이름으로 돌아간다 —
        // 고르다 만 글자가 화면에 남아 선택된 것처럼 보이면 안 된다
        value={open ? text : value}
        placeholder={open ? value || "역 이름 / 초성" : ""}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
          setText("");
        }}
        onBlur={() => {
          setOpen(false);
          setText("");
        }}
        onKeyDown={onKeyDown}
        disabled={disabled}
        // 목록을 닫는 시점에 항상 확정값으로 되돌아가므로, 비어 있으면 곧 미선택이다.
        // 제출 버튼을 누르면 blur가 먼저 나 닫히고, 그 뒤 이 검사가 걸린다
        required={required}
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
      />

      {open && (
        <ul id={`${id}-list`} ref={listRef} role="listbox" style={st.pickerList}>
          {matches.length === 0 && (
            <li style={{ ...st.pickerItem, color: "#9aa4b2" }}>일치하는 역이 없습니다</li>
          )}
          {matches.map((s, i) => (
            <li
              key={s.name}
              role="option"
              aria-selected={i === active}
              // blur가 click보다 먼저 나서 목록이 닫혀 버린다 — mousedown에서 잡는다
              onMouseDown={(e) => {
                e.preventDefault();
                commit(s);
              }}
              onMouseEnter={() => setActive(i)}
              style={{
                ...st.pickerItem,
                background: i === active ? "#eef3fb" : "transparent",
                fontWeight: s.name === value ? 700 : 400,
              }}
            >
              {s.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
