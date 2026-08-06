#!/usr/bin/env python3
"""PWA 아이콘 생성 (PLAN.md 10절 Phase 3). 일회성 — app/ 코드와 무관하다.

    uv run python scripts/gen_icons.py

iOS 웹푸시는 **홈화면 추가가 전제**이고(D-1/D-9), 홈화면 추가에는 manifest 아이콘과
`apple-touch-icon`이 필요하다. 아이콘이 없으면 사파리가 스크린샷을 아이콘으로 쓰고
그 상태로는 알림 권한을 요청할 화면조차 제대로 안 뜬다.

의존성을 늘리지 않기 위해 PNG를 stdlib(zlib/struct)로 직접 쓴다 — 도형이 사각형뿐이라
이미지 라이브러리를 끌어올 이유가 없다. 그림은 이 앱의 본체인 **좌석 × 구간 매트릭스**다.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "public"

NAVY = (26, 58, 107)  # #1a3a6b — index.html의 theme-color와 같은 값
WHITE = (255, 255, 255)
SOLD = (58, 92, 148)  # 판매된 셀 — 배경보다 밝은 남색

# 좌석 × 구간 매트릭스 4×4. True = 빈자리(흰 칸)
GRID = (
    (True, True, False, False),
    (False, True, True, True),
    (True, False, False, True),
    (True, True, True, False),
)


def write_png(path: Path, size: int, rows: list[list[tuple[int, int, int]]]) -> None:
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8bit RGB
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def render(size: int) -> list[list[tuple[int, int, int]]]:
    """maskable 안전영역(가운데 80%) 안에 매트릭스를 그린다.

    안드로이드가 아이콘을 원형으로 잘라내므로 그림이 바깥 20%에 걸치면 잘린다.
    """
    cols = len(GRID[0])
    span = int(size * 0.56)  # 그림 전체 크기
    gap = max(1, span // 28)
    cell = (span - gap * (cols - 1)) // cols
    span = cell * cols + gap * (cols - 1)
    origin = (size - span) // 2

    rows = [[NAVY] * size for _ in range(size)]
    for r, line in enumerate(GRID):
        for c, free in enumerate(line):
            color = WHITE if free else SOLD
            y0 = origin + r * (cell + gap)
            x0 = origin + c * (cell + gap)
            for y in range(y0, y0 + cell):
                for x in range(x0, x0 + cell):
                    rows[y][x] = color
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # 192/512 = manifest 규격, 180 = apple-touch-icon (iOS 홈화면)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        write_png(OUT / name, size, render(size))
        print(f"{OUT / name} ({size}×{size})")


if __name__ == "__main__":
    main()
