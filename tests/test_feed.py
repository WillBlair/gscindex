import unittest
from datetime import datetime, timezone

from components.feed import _format_time_ago


class FormatTimeAgoTests(unittest.TestCase):
    def test_aware_utc_timestamp_uses_utc_now(self) -> None:
        now = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)

        result = _format_time_ago("2026-03-20T11:00:00Z", now=now)

        self.assertEqual(result, "1h ago")

    def test_naive_timestamp_defaults_to_utc(self) -> None:
        now = datetime(2026, 3, 20, 12, 30, tzinfo=timezone.utc)

        result = _format_time_ago("2026-03-20T12:00:00", now=now)

        self.assertEqual(result, "30m ago")


if __name__ == "__main__":
    unittest.main()
