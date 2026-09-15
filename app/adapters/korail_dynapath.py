"""DynaPath 안티봇 우회 — 벤더링 (D-22).

## 출처와 범위

원본: https://github.com/dhfhfk/korail2 브랜치 `bypassDynapath`
고정 커밋: `4b134266fff097ea0fd54e9f760cb128b6c8f878` (korail2 PR #54 "Implement anti-bot
bypass"의 head 커밋. 공급망 리뷰 완료된 커밋이다)

여기에는 우회에 필요한 것만 옮긴다. 원본 PR은 `korail2/korail2.py` 한 파일을
+145/-7로 고치는데, **우리가 쓰는 것은 그중 하나뿐이다** (→ D-60):

- `x-dynapath-m-token` 헤더 부착 — 우리가 부르는 조회 3종 전부에 붙인다

원본의 나머지 셋(`Sid` 본문 필드, 로그인 `Version` 덮어쓰기, `ScheduleView`의
GET→POST 전환)은 **로그인 경로 전용**이라 익명 전환(D-60) 이후 필요 없어졌다.
`Sid`는 아예 보내지 않는다 — 익명 경로는 요구하지 않는다.

전부 **HTTP 계층에서 표현 가능**하므로 `requests.Session` 서브클래스 하나로 끝낸다.
업스트림 korail2가 갱신돼도 어긋날 일이 없다 — 우회 코드가 본체와 물리적으로 분리된다.

## 유지보수 부채 (PLAN 0절에 기록된 리스크)

코레일이 앱을 업데이트하면 토큰 스킴이 바뀌어 우회가 깨질 수 있다. 그때 고칠 곳은
이 파일 하나다.

**증상이 두 가지라는 점에 주의해라.** 앱 로직까지 닿으면 `MACRO ERROR`(`h_msg_cd`)로
오지만, 게이트웨이에서 먼저 잘리면 **HTTP 403**이다 (2026-09-15 실측 — 그때는 토큰이
아니라 인증 경로가 막힌 것이었다). 둘 다 `KorailBlocked`로 모인다.

## 알고리즘 이식 주의

`_DynaPathTokenEngine`의 메서드들은 원본과 **1:1로 대조 가능하도록** 이름과 구조를
그대로 뒀다 (`string2xA1s`, `make_key`, `encode_normal_be` 등 — 파이썬 명명 관례와
어긋나지만 의도적이다). 알고리즘을 '정리'하지 마라. 앱의 난독화 로직을 재현한
것이라 사소한 차이가 곧 토큰 불일치다.
"""

from __future__ import annotations

import random
import string
import time
from typing import Any

import requests

# ── 원본 상수 (dhfhfk/korail2 @ 4b13426) ────────────────────────────────
# 토큰을 붙일 경로. **원본과 달리 research.* 도 포함한다** — 원본은 로그인 세션으로
# 그 둘을 부르지만, 익명 경로에서는 토큰이 곧 통행증이다 (D-60 실측).
DYNAPATH_PATHS = (
    "/classes/com.korail.mobile.certification.TicketReservation",
    "/classes/com.korail.mobile.nonMember.NonMemTicket",
    "/classes/com.korail.mobile.seatMovie.ScheduleView",
    "/classes/com.korail.mobile.seatMovie.ScheduleViewSpecial",
    "/classes/com.korail.mobile.trn.prcFare.do",
    "/classes/com.korail.mobile.login.Login",
    "/classes/com.korail.mobile.research.TrainResearch",
    "/classes/com.korail.mobile.research.ResidualSeatsResearch.do",
)

APP_VERSION = "250601002"
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; SM-S928N Build/UP1A.231005.007)"

_DEVICE_ID = "558a4f02041657ea"
_DEVICE = "AD"


class _DynaPathTokenEngine:
    """`x-dynapath-m-token` 생성기. 원본 `DynaPathMasterEngine`의 이식.

    앱이 심어둔 난독화 인코딩을 재현한다. 아래 메서드는 원본과 대조하기 쉽도록
    이름·구조를 보존했다 (naming 규칙 위반은 의도적).
    """

    APP_ID = "com.korail.talk"
    AS_VALUE = "%5B38ff229cb34c7dda8e28220a2d750cce%5D"
    DEVICE_MODEL = "SM-S928N"
    OS_TYPE = "Android"
    SDK_VERSION = "v1"

    TABLE = "3FE9jgRD4KdCyuawklqGJYmvfMn15P7US8XbxeLQtWT6OicBAopINs2Vh0HZrz"
    I8, I9, I10 = 161, 30, 2

    def __init__(self, app_start_ts: str | None = None) -> None:
        # 앱 기동 시각. 프로세스 수명 동안 고정이다 (원본과 동일한 의미).
        self.app_start_ts = app_start_ts or str(int(time.time() * 1000))

    # -- 원본 이식부: 아래 4개는 손대지 말 것 ---------------------------------
    def string2xA1s(self, data_str: str) -> list[int]:  # noqa: N802
        result: list[int] = []
        i = 0
        while i < len(data_str):
            cp = ord(data_str[i])
            i += 1
            if cp < 128:
                result.append(cp)
            elif cp < 2048:
                result.append(128 | ((cp >> 7) & 15))
                result.append(cp & 127)
            elif cp >= 262144:
                result.append(160)
                result.append((cp >> 14) & 127)
                result.append((cp >> 7) & 127)
                result.append(cp & 127)
            elif (63488 & cp) != 55296:
                result.append(((cp >> 14) & 15) | 144)
                result.append((cp >> 7) & 127)
                result.append(cp & 127)
        return result

    def make_key(self, key_str: str) -> int:
        big_int_add = 0
        for char in key_str:
            cp = ord(char)
            i9_bit = 32768
            for _ in range(16):
                if (i9_bit & cp) != 0:
                    break
                i9_bit >>= 1
            big_int_add = (big_int_add * (i9_bit << 1)) + cp
        return big_int_add

    def _internal_i(self, base_table: str, remainder: int, encode_size: int, current_sb: str) -> str:
        # encode_size는 원본에서도 쓰이지 않는다 (시그니처 보존용).
        j8_count = 0
        for k in range(len(base_table)):
            char = base_table[k]
            if char not in current_sb:
                if j8_count == remainder:
                    return char
                j8_count += 1
        return " "

    def make_encode_table(self, num: int, encode_size: int, base_table: str) -> str:
        sb = ""
        temp_num = num
        for i in range(encode_size):
            j8_divisor = encode_size - i
            remainder = temp_num % j8_divisor
            char = self._internal_i(base_table, remainder, len(base_table), sb)
            sb += char
            temp_num //= j8_divisor
        return sb

    def encode_normal_be(
        self, data_str: str, table: str, i8: int = 161, i9: int = 30, i10: int = 2
    ) -> str:
        list_data = self.string2xA1s(data_str)
        sb: list[str] = []
        i_arr = [0] * (i10 + 1)
        idx, size = 0, len(list_data) % i10
        size2 = len(list_data) - size
        while idx < size2:
            val = 0
            for _ in range(i10):
                val = (val * i8) + list_data[idx]
                idx += 1
            for i in range(i10 + 1):
                i_arr[i] = val % i9
                val //= i9
            for i in range(i10, -1, -1):
                sb.append(table[i_arr[i]])
        if size > 0:
            val = 0
            for _ in range(size):
                val = (val * i8) + list_data[idx]
                idx += 1
            for i in range(size + 1):
                i_arr[i] = val % i9
                val //= i9
            while size >= 0:
                sb.append(table[i_arr[size]])
                size -= 1
        return "".join(sb)

    def generate_token(self, device_id: str, ts: int, rand: str) -> str:
        plaintext = (
            f"ai={self.APP_ID}&di={device_id}&as={self.AS_VALUE}&"
            f"su=false&dbg=false&emu=false&hk=false&it={self.app_start_ts}&"
            f"ts={ts}&rt=0&os=13&dm={self.DEVICE_MODEL}&st={self.OS_TYPE}&sv={self.SDK_VERSION}"
        )
        dyn_key = f"v1+{rand}+{ts}"
        key_enc = self.encode_normal_be(dyn_key, self.TABLE, self.I8, self.I9, self.I10)
        big_key = self.make_key(dyn_key)
        custom_table = self.make_encode_table(big_key, self.I9, self.TABLE)
        body_enc = self.encode_normal_be(plaintext, custom_table, self.I8, self.I9, self.I10)
        return f"bEeEP{self.TABLE[len(key_enc)]}{key_enc}{body_enc}"

    # -- 이식부 끝 -----------------------------------------------------------


def _matches(url: str, paths: tuple[str, ...]) -> bool:
    return any(p in url for p in paths)


class DynaPathSession(requests.Session):
    """우회를 적용하는 `requests.Session` — 하는 일은 **토큰 헤더 부착 하나**다.

    익명 조회 경로(D-60)에서는 이 세션이 인증의 전부다. `ScheduleView` 응답이
    내려주는 익명 쿠키를 세션이 들고 있다가 `research.*` 두 호출에 실어 보낸다.

    **세션 하나가 곧 조회 한 건의 문맥이다.** 쿠키가 순서(ScheduleView → research)에
    의존하므로 **구간마다 새 세션을 써라** — 하나를 여러 구간이 공유하면 병렬 조회에서
    쿠키가 뒤섞인다. 로그인이 없어져 세션 생성이 공짜이므로 아낄 이유도 없다.
    """

    def __init__(self) -> None:
        super().__init__()
        self._engine = _DynaPathTokenEngine()
        self.headers.update({"User-Agent": USER_AGENT})

    def _dynapath_headers(self, ts_ms: int) -> dict[str, str]:
        rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return {"x-dynapath-m-token": self._engine.generate_token(_DEVICE_ID, ts_ms, rand)}

    def request(  # type: ignore[override]
        self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any
    ) -> requests.Response:
        url_s = url.decode() if isinstance(url, bytes) else url

        if _matches(url_s, DYNAPATH_PATHS):
            ts_ms = int(time.time() * 1000)
            headers = dict(kwargs.get("headers") or {})
            headers.update(self._dynapath_headers(ts_ms))
            kwargs["headers"] = headers

        return super().request(method, url_s, *args, **kwargs)
