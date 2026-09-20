import unittest
from datetime import date

from booking.utils import (
    DAY_MINUTES,
    build_datetime_range,
    duration_minutes,
    format_minutes,
    minute_offset,
    validate_booking_range,
)


class BookingTimeTests(unittest.TestCase):
    def test_parse_twenty_four_hour(self):
        self.assertEqual(minute_offset("24:00"), DAY_MINUTES)
        self.assertEqual(format_minutes(DAY_MINUTES), "24:00")

    def test_build_normal_range(self):
        start, end = build_datetime_range(date(2026, 9, 20), 9 * 60, 11 * 60 + 30)
        self.assertEqual(start.hour, 9)
        self.assertEqual(end.hour, 11)
        self.assertEqual(duration_minutes(start, end), 150)

    def test_end_at_midnight_for_24_hour_day(self):
        start, end = build_datetime_range(date(2026, 9, 20), 23 * 60 + 30, DAY_MINUTES)
        self.assertEqual(start.day, 20)
        self.assertEqual(end.day, 21)
        self.assertEqual(end.hour, 0)
        self.assertEqual(duration_minutes(start, end), 30)

    def test_rejects_reversed_range(self):
        with self.assertRaises(ValueError):
            validate_booking_range(date(2026, 9, 20), 12 * 60, 11 * 60)


if __name__ == "__main__":
    unittest.main()
