// 즐겨찾기 노선 (D-56) — 스킨 공통 로직. 문구/판정이 스킨마다 갈리면 안 되므로
// 라벨과 저장 가능 판정은 여기서 한 번만 만든다 (D-50과 같은 원칙).

// 백엔드 MAX_PRESETS_PER_USER와 같은 값. 여기 것은 버튼을 미리 감추는 용도일 뿐이고
// 최종 방어선은 서버다 — 초과 요청은 409로 거절된다 (api/presets.py).
export const MAX_FAVORITES = 5;

export const routeLabel = (p) => `${p.from_station} → ${p.to_station}`;

export const isSaved = (favs, from, to) =>
  favs.some((p) => p.from_station === from && p.to_station === to);

// 저장 칩을 보여줄 조건: 양쪽 역이 골라졌고, 같은 역 왕복이 아니고,
// 이미 저장돼 있지 않고, 상한 미만일 때.
export const canSave = (favs, from, to) =>
  Boolean(from && to) && from !== to && !isSaved(favs, from, to) && favs.length < MAX_FAVORITES;
