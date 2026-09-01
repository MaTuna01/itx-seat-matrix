"""정차역 캐시 에러 문구 (이슈 #75).

`stops_error_detail`은 순수 함수 — sleep 없이 now 주입으로 검증한다 (D-21).
"""

from __future__ import annotations

from datetime import date, datetime

from app.api.stops import stops_error_detail
from app.domain.models import KST


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=KST)


class TestStopsErrorDetail:
    def test_캐시_미스_문구는_다음_갱신을_안내한다(self):
        msg = stops_error_detail(
            train_no="4202",
            missing_station=None,
            source_run_ymd=date(2026, 8, 4),
            now=NOW,
        )
        assert "4202" in msg
        assert "정차역 정보" in msg
        assert "다음 날 새벽 자동 갱신" in msg
        # 개발자용 스크립트 경로가 사용자에게 노출되지 않아야 한다 (이슈 #75 원인 중 하나)
        assert "scripts/" not in msg
        assert "load_train_stops" not in msg

    def test_캐시_미스에_기준일이_없으면_문구가_짧아진다(self):
        msg = stops_error_detail(
            train_no="4202", missing_station=None, source_run_ymd=None, now=NOW,
        )
        assert "4202" in msg
        assert "다음 날 새벽" in msg
        assert "기준일" not in msg  # None이면 그 절이 빠져야 한다

    def test_노선_불일치_문구는_역과_기준일을_노출한다(self):
        msg = stops_error_detail(
            train_no="4202",
            missing_station="대전",
            source_run_ymd=date(2026, 8, 4),
            now=NOW,
        )
        assert "'대전'" in msg
        assert "4202" in msg
        assert "2026-08-04" in msg  # 사용자가 왜 안 나오는지 판단할 수 있게 기준일 노출
        assert "시각표 개편" in msg  # 개편 가능성 명시
        assert "scripts/" not in msg

    def test_노선_불일치에_기준일이_없어도_핵심_문구는_남는다(self):
        msg = stops_error_detail(
            train_no="4202", missing_station="대전", source_run_ymd=None, now=NOW,
        )
        assert "'대전'" in msg
        assert "정차역 목록에 없습니다" in msg
        assert "기준" not in msg  # 기준일 절 자체가 빠져야 한다
