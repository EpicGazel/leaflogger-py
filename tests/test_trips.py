"""Trip-detection tests. Mirrors functions.php gap logic (default 10 min)."""
import os
import tempfile
import unittest

from leaflogger.db import init_db
from leaflogger.trips import find_trips


class FindTripsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn, _ = init_db(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def insert(self, *timestamps, ignore=0):
        self.conn.executemany(
            "INSERT INTO logs (leaflogs_timestamp, leaflogs_ignore)"
            " VALUES (?, ?)",
            [(t, ignore) for t in timestamps])
        self.conn.commit()

    def test_empty_db(self):
        self.assertEqual(find_trips(self.conn), [])

    def test_single_trip(self):
        self.insert("2026-09-01 08:00:00",
                    "2026-09-01 08:05:00",
                    "2026-09-01 08:09:00")
        self.assertEqual(find_trips(self.conn), [{
            "start": "2026-09-01 08:00:00",
            "end": "2026-09-01 08:09:00",
            "records": 3,
        }])

    def test_gap_splits_trips(self):
        # 40-min gap, then 5-min gap (under the 10-min delimiter).
        self.insert("2026-09-01 08:00:00",
                    "2026-09-01 08:05:00",
                    "2026-09-01 08:45:00",
                    "2026-09-01 08:50:00")
        self.assertEqual(find_trips(self.conn), [
            {"start": "2026-09-01 08:00:00",
             "end": "2026-09-01 08:05:00", "records": 2},
            {"start": "2026-09-01 08:45:00",
             "end": "2026-09-01 08:50:00", "records": 2},
        ])

    def test_ignored_rows_excluded(self):
        self.insert("2026-09-01 08:00:00", "2026-09-01 08:05:00")
        self.insert("2026-09-01 08:06:00", ignore=1)
        trips = find_trips(self.conn)
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0]["records"], 2)


if __name__ == "__main__":
    unittest.main()
