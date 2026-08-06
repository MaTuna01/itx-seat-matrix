#!/usr/bin/env bash
# `.env` 의 시크릿을 값 노출 없이 대조한다 (DEPLOY.md 4절).
#
# 왜 필요한가: 배포 `.env` 를 별도 보관본(노션 등)에서 손으로 만들면 SECRET_KEY 가
# 한 글자만 달라도 — 공백, 스마트 쿼트, 잘린 끝 문자 — 앱은 정상 기동하고 로그인도 되는데
# 옮겨온 DB 의 korail_pw_enc 복호화만 실패한다. 증상은 FETCH_FAILED 1회 +
# 화면의 "연결됨" 꺼짐뿐이라 원인이 SECRET_KEY 라는 걸 알기 어렵다 (D-35).
#
# 사용법:
#   scripts/env_fingerprint.sh [.env 경로]      # 기본값: ./.env
#
# 원본(아이맥)과 사본(M4)에서 각각 돌려 12자 지문이 전부 일치하는지 본다.
# 아이맥에 ssh 로 붙어서 돌려도 된다 — 출력에 값은 없다:
#   ssh imac 'cd ~/itx-seat-matrix && scripts/env_fingerprint.sh'
set -euo pipefail

ENV_FILE="${1:-.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "없다: $ENV_FILE" >&2
  exit 1
fi

# 그대로 옮겨야 하는 키만 본다. KORAIL_* 는 애초에 옮기지 않으므로 대조 대상이 아니다
# (phase0 잔재 — 실 자격증명은 DB 에 Fernet 으로 있다).
KEYS='SECRET_KEY|VAPID_PUBLIC_KEY|VAPID_PRIVATE_KEY|VAPID_SUBJECT|DATA_GO_KR_SERVICE_KEY'

if command -v shasum >/dev/null 2>&1; then
  hash_cmd() { shasum -a 256; }
elif command -v sha256sum >/dev/null 2>&1; then
  hash_cmd() { sha256sum; }
else
  echo "shasum/sha256sum 이 없다" >&2
  exit 1
fi

found=0
while IFS= read -r line; do
  key="${line%%=*}"
  val="${line#*=}"
  # 따옴표로 감싼 값은 벗겨서 비교한다 — 한쪽만 감싸져 있어도 같은 값으로 봐야 한다
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  if [[ -z "$val" ]]; then
    printf '%-26s %s\n' "$key" "(빈 값)"
  else
    printf '%-26s %s\n' "$key" "$(printf %s "$val" | hash_cmd | cut -c1-12)"
  fi
  found=$((found + 1))
done < <(grep -E "^(${KEYS})=" "$ENV_FILE" || true)

if [[ "$found" -eq 0 ]]; then
  echo "대조할 키가 하나도 없다 — 파일을 잘못 지정했나: $ENV_FILE" >&2
  exit 1
fi

# 옮기면 안 되는 키가 섞여 들어왔는지도 같이 본다 (4절 표)
if grep -qE '^KORAIL_(ID|PW|SUB_ID|SUB_PW)=' "$ENV_FILE"; then
  echo >&2
  echo "경고: KORAIL_* 가 들어 있다 — 배포 .env 에서는 빼라 (4절, D-35)" >&2
fi
