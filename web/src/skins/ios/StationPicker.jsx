import { useEffect, useMemo, useRef, useState } from "react";
import { filterStations } from "../../core/hangul";
import { st, tk } from "./styles";

// 피그마 ios `23:45` (03 역 검색 · 모달 시트 + 키보드).
//
// web 스킨은 인라인 콤보박스지만 iOS는 **전체 화면 검색 모달**이다 — 키보드가 291pt를
// 먹으므로 인라인 드롭다운은 결과가 두세 줄밖에 안 보인다 (설계 규칙 보드).
//
// D-32는 그대로 지킨다: 타이핑은 **목록을 좁히기만** 하고, 확정되는 값은 언제나 목록에서
// 고른 역이다 — 자유 입력이 그대로 API로 가지 않는다.
export default function StationPicker({ title, stations, value, onPick, onClose }) {
  const [text, setText] = useState("");
  const inputRef = useRef(null);

  // 시트가 열리면 바로 키보드를 띄운다 — 한 번 더 탭하게 만들 이유가 없다
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const matches = useMemo(() => filterStations(stations, text), [stations, text]);

  return (
    <div style={st.screen}>
      <div style={st.sheetBackdrop} onClick={onClose} />
      <div style={st.sheet} role="dialog" aria-label={title}>
        <div style={st.grabber} />
        <div style={st.sheetBar}>
          <span style={{ minWidth: 56 }} />
          <span style={st.sheetTitle}>{title}</span>
          <button style={{ ...st.sheetAction, textAlign: "right" }} onClick={onClose}>취소</button>
        </div>

        <div style={st.searchField}>
          <input
            ref={inputRef}
            style={st.searchInput}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="역 이름 / 초성"
            autoComplete="off"
            aria-label="역 검색"
          />
        </div>

        <div style={{ ...st.sheetBody, paddingTop: 16 }}>
          <div style={st.group}>
            {matches.length === 0 ? (
              <div style={{ ...st.row, color: tk.textMuted }}>일치하는 역이 없습니다</div>
            ) : (
              matches.flatMap((s, i) => [
                ...(i === 0 ? [] : [<div key={`s${s.name}`} style={st.sep} />]),
                <button
                  key={s.name}
                  className="iosRow"
                  style={{ ...st.pickItem, fontWeight: s.name === value ? 700 : 400 }}
                  onClick={() => onPick(s.name)}
                >
                  {s.name}
                </button>,
              ])
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
