"""Importer unit tests (coordinate/timestamp/value conversions).

End-to-end import is covered by test_real_log.py against the anonymized
real LeafSpy fixture.
"""
import unittest

from leaflogger.importer import (
    convert_value,
    funky_to_decimal,
    parse_timestamp,
)


class FunkyCoordinatesTest(unittest.TestCase):
    def test_positive(self):
        self.assertAlmostEqual(funky_to_decimal("40:30.0000"), 40.5)

    def test_negative(self):
        # PHP compares the string numerically: "-74" > 0 is false,
        # so the sign branch is -(abs(d) + m/60).
        self.assertAlmostEqual(funky_to_decimal("-74:00.0000"), -74.0)
        self.assertAlmostEqual(funky_to_decimal("-122:28.8540"),
                               -(122 + 28.854 / 60.0))

    def test_zero_minutes(self):
        self.assertAlmostEqual(funky_to_decimal("37:00.0000"), 37.0)

    def test_space_separated_current_format(self):
        # Current LeafSpy exports use "DD MM.mmmm".
        self.assertAlmostEqual(
            funky_to_decimal("28 35.74814"), 28 + 35.74814 / 60.0)
        self.assertAlmostEqual(
            funky_to_decimal("-81 40.03851"), -(81 + 40.03851 / 60.0))


class ConvertValueTest(unittest.TestCase):
    def test_empty_coord_becomes_zero(self):
        self.assertEqual(convert_value("leaflogs_lat", ""), (True, 0))
        self.assertEqual(convert_value("leaflogs_lon", "  "), (True, 0))

    def test_empty_other_becomes_null(self):
        self.assertEqual(convert_value("leaflogs_gids", ""), (False, None))

    def test_none_literal_becomes_null(self):
        self.assertEqual(convert_value("leaflogs_pack_t1_f", "none"),
                         (False, None))

    def test_na_literal_becomes_null(self):
        # Real exports use "na" for missing readings (e.g. 12 V battery).
        self.assertEqual(convert_value("leaflogs_batvolt", "na"),
                         (False, None))
        self.assertEqual(convert_value("leaflogs_batvolt", "N/A"),
                         (False, None))

    def test_batvolt_strips_v(self):
        self.assertEqual(convert_value("leaflogs_batvolt", "12.6V"),
                         (True, "12.6"))

    def test_timestamp_normalised(self):
        self.assertEqual(
            parse_timestamp("2026-09-01 08:00:00"), "2026-09-01 08:00:00")

    def test_bad_timestamp_raises(self):
        with self.assertRaises(ValueError):
            parse_timestamp("not a date")


if __name__ == "__main__":
    unittest.main()
