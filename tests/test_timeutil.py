"""跨时区换日：先后判断只认 UTC 时刻，本地日期仅用于展示。"""

import unittest
from datetime import datetime, timedelta, timezone

from src.governance.errors import ValidationError
from src.governance.timeutil import covers, local_date, to_utc

BEIJING = timezone(timedelta(hours=8))


class TimeutilTest(unittest.TestCase):
    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValidationError):
            to_utc(datetime(2026, 3, 10, 9, 0))

    def test_term_boundary_is_instant_not_local_day(self):
        # 任期结束于北京时间 2026-07-01 00:00，即 UTC 2026-06-30 16:00。
        start = datetime(2026, 1, 1, 0, 0, tzinfo=BEIJING)
        end = datetime(2026, 7, 1, 0, 0, tzinfo=BEIJING)
        # UTC 15:30（北京 23:30，仍在 6 月 30 日）→ 有效
        self.assertTrue(covers(start, end, datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc)))
        # UTC 16:30（北京已是 7 月 1 日 00:30；洛杉矶仍是 6 月 30 日上午）→ 无效
        self.assertFalse(covers(start, end, datetime(2026, 6, 30, 16, 30, tzinfo=timezone.utc)))

    def test_local_date_depends_on_zone(self):
        instant = datetime(2026, 3, 10, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(local_date(instant, "Asia/Shanghai").isoformat(), "2026-03-10")
        self.assertEqual(local_date(instant, "America/Los_Angeles").isoformat(), "2026-03-09")


if __name__ == "__main__":
    unittest.main()
