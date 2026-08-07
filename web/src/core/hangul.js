// 역 이름 검색 매칭 (D-32). 순수 함수만 — 컴포넌트 상태를 모른다.
//
// 282개 역을 드롭다운으로 훑는 건 실사용에서 성립하지 않는다. 타이핑으로 좁히되
// **선택은 여전히 목록에서** 한다 (D-25 유지).
//
// 초성 검색이 핵심이다. 모바일에서 "ㅊㅇ" 두 타로 천안에 닿는 것과 "천안"을
// 완성해야 하는 것의 차이가 크다.
//
// 다만 초성만 비교하면 **조합 중간 상태에서 목록이 빈다.** 한글 IME로 "천안"을
// 치면 ㅊ → 처 → 천 → 천ㅇ → 천아 → 천안을 실제로 거치는데, "천아"는 초성
// 비교로도 완성형 비교로도 걸리지 않는다(아 ≠ 안).
//
// 그래서 글자를 **자모로 분해해 접두 비교**한다. 질의 글자의 자모열이 이름 글자의
// 자모열의 접두면 일치:
//   아[ㅇㅏ] ⊂ 안[ㅇㅏㄴ] ✓   ㅊ[ㅊ] ⊂ 천[ㅊㅓㄴ] ✓   사[ㅅㅏ] ⊄ 산[ㅅㅏㄴ]의 역방향 ✗
// 초성 검색·조합 중간 상태·완성형이 규칙 하나로 통일된다.
//
// 겹모음(ㅘ=ㅗ+ㅏ)·겹받침(ㄳ=ㄱ+ㅅ)도 풀어 둔다. 안 풀면 "고"로 과천에,
// "안"으로 앉- 계열에 닿지 못한다 — 역시 조합 중간 상태다.

const CHOSEONG = [
  "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
  "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
];
const JUNGSEONG = [
  "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ", "ㅙ",
  "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
];
const JONGSEONG = [
  "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ",
  "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
];
// 두 자모가 합쳐진 것들 — 조합 순서대로 되돌린다
const COMPOUND = {
  "ㅘ": "ㅗㅏ", "ㅙ": "ㅗㅐ", "ㅚ": "ㅗㅣ", "ㅝ": "ㅜㅓ", "ㅞ": "ㅜㅔ", "ㅟ": "ㅜㅣ", "ㅢ": "ㅡㅣ",
  "ㄳ": "ㄱㅅ", "ㄵ": "ㄴㅈ", "ㄶ": "ㄴㅎ", "ㄺ": "ㄹㄱ", "ㄻ": "ㄹㅁ", "ㄼ": "ㄹㅂ",
  "ㄽ": "ㄹㅅ", "ㄾ": "ㄹㅌ", "ㄿ": "ㄹㅍ", "ㅀ": "ㄹㅎ", "ㅄ": "ㅂㅅ",
};

const HANGUL_BASE = 0xac00; // '가'
const HANGUL_LAST = 0xd7a3; // '힣'
const JUNG_JONG = 21 * 28; // 중성 21 × 종성 28 — 초성 1칸의 크기

const split = (jamo) => COMPOUND[jamo] || jamo;

// 글자 하나를 자모열로. 완성형 음절이 아니면(자모·영문·숫자) 그대로 돌려준다
function toJamo(ch) {
  const code = ch.charCodeAt(0);
  const offset = code - HANGUL_BASE;
  if (offset < 0 || code > HANGUL_LAST) return ch;
  return (
    CHOSEONG[Math.floor(offset / JUNG_JONG)] +
    split(JUNGSEONG[Math.floor((offset % JUNG_JONG) / 28)]) +
    split(JONGSEONG[offset % 28])
  );
}

function charMatches(nameCh, queryCh) {
  if (nameCh === queryCh) return true;
  return toJamo(nameCh).startsWith(toJamo(queryCh));
}

// 이름에서 질의가 처음 걸리는 위치. 없으면 -1, 빈 질의는 0
export function matchIndex(name, query) {
  if (!query) return 0;
  if (query.length > name.length) return -1;
  for (let start = 0; start + query.length <= name.length; start++) {
    let ok = true;
    for (let i = 0; i < query.length; i++) {
      if (!charMatches(name[start + i], query[i])) {
        ok = false;
        break;
      }
    }
    if (ok) return start;
  }
  return -1;
}

// 질의에 맞는 역만 남기고 정렬한다.
// 앞에서 걸린 것 우선 → 짧은 이름 우선 → 가나다순.
// 두 번째 기준이 없으면 "천안"을 쳤을 때 천안아산이 천안보다 먼저 올 수 있다.
export function filterStations(stations, query) {
  const q = query.trim();
  const scored = [];
  for (const s of stations) {
    const at = matchIndex(s.name, q);
    if (at >= 0) scored.push({ station: s, at });
  }
  scored.sort(
    (a, b) =>
      a.at - b.at ||
      a.station.name.length - b.station.name.length ||
      a.station.name.localeCompare(b.station.name, "ko")
  );
  return scored.map((x) => x.station);
}
