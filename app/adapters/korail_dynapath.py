"""DynaPath 안티봇 우회 — 벤더링 (D-22).

## 출처와 범위

원본: https://github.com/dhfhfk/korail2 브랜치 `bypassDynapath`
고정 커밋: `4b134266fff097ea0fd54e9f760cb128b6c8f878` (korail2 PR #54 "Implement anti-bot
bypass"의 head 커밋. 공급망 리뷰 완료된 커밋이다)

korail2 **본체는 PyPI 정식 릴리스**(`korail2>=0.4.0`)를 그대로 쓰고, 여기에는 우회에
필요한 것만 옮긴다. 원본 PR은 `korail2/korail2.py` 한 파일을 +145/-7로 고치는데,
그 변경은 전부 아래 4가지로 환원된다:

1. `DYNAPATH_PATHS`에 속한 경로에 `x-dynapath-m-token` 헤더 부착
2. 같은 경로의 요청 본문에 `Sid`(AES-CBC 산출값) 추가
3. `Version`을 `250601002`로 최신화 (`login()`은 `231231001`을 **하드코딩**하고 있다)
4. `ScheduleView` 호출을 GET → POST로 변경

넷 다 **HTTP 계층에서 표현 가능**하므로 `Korail.login()` / `Korail.search_train()`의
본문을 복사하지 않고 `requests.Session` 서브클래스 하나로 끝낸다. 업스트림 korail2가
갱신돼도 메서드 본문이 어긋날 일이 없다 — 우회 코드가 본체와 물리적으로 분리된다.

## 유지보수 부채 (PLAN 0절에 기록된 리스크)

코레일이 앱을 업데이트하면 토큰 스킴이 바뀌어 우회가 깨질 수 있다. 그때 고칠 곳은
이 파일 하나다. 깨진 것은 `MACRO ERROR`(`h_msg_cd`)로 드러난다.

## 알고리즘 이식 주의

`_DynaPathTokenEngine`의 메서드들은 원본과 **1:1로 대조 가능하도록** 이름과 구조를
그대로 뒀다 (`string2xA1s`, `make_key`, `encode_normal_be` 등 — 파이썬 명명 관례와
어긋나지만 의도적이다). 알고리즘을 '정리'하지 마라. 앱의 난독화 로직을 재현한
것이라 사소한 차이가 곧 토큰 불일치다.
"""

from __future__ import annotations

import base64
import random
import string
import time
from typing import Any

import requests
from cryptography.hazmat.primitives import padding as _padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# ── 원본 상수 (dhfhfk/korail2 @ 4b13426) ────────────────────────────────
# 이 경로들만 토큰을 요구한다. 좌석맵 엔드포인트(research.*)는 여기 없다 —
# Phase 0 실측대로 인증 세션만으로 호출된다.
DYNAPATH_PATHS = (
    "/classes/com.korail.mobile.certification.TicketReservation",
    "/classes/com.korail.mobile.nonMember.NonMemTicket",
    "/classes/com.korail.mobile.seatMovie.ScheduleView",
    "/classes/com.korail.mobile.seatMovie.ScheduleViewSpecial",
    "/classes/com.korail.mobile.trn.prcFare.do",
    "/classes/com.korail.mobile.login.Login",
)

APP_VERSION = "250601002"
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; SM-S928N Build/UP1A.231005.007)"

_SID_KEY = b"2485dd54d9deaa36"  # AES-128 키 겸 IV (원본 그대로)
_DEVICE_ID = "558a4f02041657ea"
_DEVICE = "AD"

# GET → POST로 바꿔야 하는 경로 (원본 patch의 search_train 변경분)
_FORCE_POST_PATHS = (
    "/classes/com.korail.mobile.seatMovie.ScheduleView",
    "/classes/com.korail.mobile.seatMovie.ScheduleViewSpecial",
)


def _generate_sid(ts_ms: int, *, device: str = _DEVICE) -> str:
    """`Sid` 본문 필드. AES-128-CBC(key=iv=_SID_KEY) + PKCS7 + base64 + 개행.

    원본은 pycryptodome(`Crypto.Cipher.AES`)을 쓰지만 여기서는 이미 명시적 의존인
    `cryptography`를 쓴다 — 산출 바이트는 동일하다 (같은 키/IV/패딩).
    pycryptodome은 korail2의 전이 의존일 뿐이라 직접 기대지 않는다.
    """
    plaintext = f"{device}{ts_ms}".encode()
    padder = _padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_SID_KEY), modes.CBC(_SID_KEY)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode() + "\n"


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
    """우회를 적용하는 `requests.Session`.

    `Korail` 인스턴스의 `_session`을 이것으로 갈아끼우면 로그인·열차조회가 통과한다.
    좌석맵(`research.*`) 호출도 같은 세션을 재사용하면 인증 쿠키가 그대로 실린다.

    주의: korail2의 `_session`은 **클래스 속성**이라 인스턴스에 대입해 가려야 한다
    (`korail._session = DynaPathSession()`). 클래스 속성을 갈면 프로세스 전역이 오염된다.
    """

    def __init__(self, *, app_version: str = APP_VERSION) -> None:
        super().__init__()
        self._engine = _DynaPathTokenEngine()
        self._app_version = app_version
        self.headers.update({"User-Agent": USER_AGENT})

    def _dynapath_headers(self, ts_ms: int) -> dict[str, str]:
        rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return {"x-dynapath-m-token": self._engine.generate_token(_DEVICE_ID, ts_ms, rand)}

    def request(  # type: ignore[override]
        self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any
    ) -> requests.Response:
        url_s = url.decode() if isinstance(url, bytes) else url
        method_s = (method.decode() if isinstance(method, bytes) else method).upper()

        # (3) Version 최신화. login()이 '231231001'을 하드코딩하고 있어 여기서 덮는다.
        for field in ("data", "params"):
            payload = kwargs.get(field)
            if isinstance(payload, dict) and "Version" in payload:
                payload["Version"] = self._app_version

        if _matches(url_s, DYNAPATH_PATHS):
            ts_ms = int(time.time() * 1000)

            # (1) 토큰 헤더
            headers = dict(kwargs.get("headers") or {})
            headers.update(self._dynapath_headers(ts_ms))
            kwargs["headers"] = headers

            # (2) Sid 본문 필드
            data = kwargs.get("data")
            if isinstance(data, dict):
                data["Sid"] = _generate_sid(ts_ms)
            elif data is None and method_s == "POST":
                kwargs["data"] = {"Sid": _generate_sid(ts_ms)}

            # (4) ScheduleView는 POST여야 한다. 원본도 params는 쿼리스트링에 그대로 둔다.
            if method_s == "GET" and _matches(url_s, _FORCE_POST_PATHS):
                method_s = "POST"

        return super().request(method_s, url_s, *args, **kwargs)


def apply_bypass(korail: Any) -> DynaPathSession:
    """`korail2.Korail` 인스턴스에 우회를 적용하고 세션을 돌려준다.

    korail2 본체는 건드리지 않는다 — 인스턴스 속성만 덮는다.
    """
    session = DynaPathSession()
    korail._session = session  # 클래스 속성을 인스턴스 속성으로 가림 (위 주의 참고)
    korail._version = APP_VERSION
    return session
