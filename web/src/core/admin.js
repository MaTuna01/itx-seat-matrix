// 관리자 화면의 공유 판정 (D-53).
//
// 스킨이 각자 이 조건을 쓰면 한쪽만 고쳐졌을 때 **한 스킨에서만 지워지는 버튼**이 생긴다.
// D-50 결정 ②와 같은 이유로 core에 한 벌만 둔다.

// 삭제 버튼을 그릴지 여부. 서버도 같은 조건을 400으로 거절하므로 여기는 "보여주지 않기"만
// 담당한다 — 화면이 방어선이 아니다.
export function isDeletable(row, me) {
  return !row.is_admin && row.id !== me.id;
}

// 목록 한 줄의 부가 설명. 스킨은 이 문자열을 그리기만 한다
export function describeUser(row) {
  const parts = [];
  if (row.korail_linked) parts.push("코레일 연결됨");
  if (row.discord_linked) parts.push("디스코드");
  parts.push(`구독 ${row.subscription_count}건`);
  return parts.join(" · ");
}
