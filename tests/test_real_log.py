"""Regression test over a real LeafSpy export (100 rows, 2 trips).

The fixture is anonymized from a genuine export with
tools/anonymize_csv.py (shifted GPS/dates, placeholder VIN). It covers
the real-world format the synthetic fixtures don't: US-style
timestamps, space-separated "DD MM.mmmm" coordinates, 161 columns, and
"na" missing-value literals. The original file stays local-only
(gitignored) — never commit real logs with your VIN and location
history.
"""
import os
import tempfile
import unittest

from leaflogger.db import init_db
from leaflogger.importer import import_csv
from leaflogger.trips import find_trips

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "real_format.csv")


class RealLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn, _ = init_db(os.path.join(self.tmp.name, "test.db"))
        self.stats = import_csv(self.conn, FIXTURE)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_clean_import(self):
        self.assertEqual(
            (self.stats["processed"], self.stats["inserted"],
             self.stats["dups"], self.stats["errors"]),
            (100, 100, 0, 0))

    def test_space_form_coordinates(self):
        row = self.conn.execute(
            "SELECT leaflogs_lat, leaflogs_lon FROM logs "
            "ORDER BY leaflogs_timestamp LIMIT 1").fetchone()
        self.assertAlmostEqual(row[0], 5 + 28 + 35.74814 / 60.0, places=5)
        self.assertAlmostEqual(row[1], -(86 + 40.03851 / 60.0), places=5)

    def test_timestamp_and_na_batvolt(self):
        row = self.conn.execute(
            "SELECT leaflogs_timestamp, leaflogs_batvolt FROM logs "
            "ORDER BY leaflogs_timestamp LIMIT 1").fetchone()
        self.assertEqual(row[0], "2025-08-21 08:43:11")
        self.assertIsNone(row[1])

    def test_two_trips(self):
        self.assertEqual(find_trips(self.conn), [
            {"start": "2025-08-21 08:43:11",
             "end": "2025-08-21 09:00:58", "records": 53},
            {"start": "2025-08-21 09:19:30",
             "end": "2025-08-21 09:35:11", "records": 47},
        ])

    def test_reimport_counts_dups(self):
        stats = import_csv(self.conn, FIXTURE)
        self.assertEqual((stats["inserted"], stats["dups"]), (0, 100))


if __name__ == "__main__":
    unittest.main()
