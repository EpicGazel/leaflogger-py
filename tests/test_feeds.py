"""Feed tests. Expected values mirror the PHP originals' output format."""
import os
import tempfile
import unittest

from leaflogger import feeds
from leaflogger.db import init_db
from leaflogger.trips import find_trips

COLS = ("leaflogs_timestamp, leaflogs_lat, leaflogs_lon, leaflogs_soc, "
        "leaflogs_gids, leaflogs_speed, leaflogs_odometer, leaflogs_soh, "
        "leaflogs_pack_t1_f, leaflogs_pack_t2_f, leaflogs_pack_t3_f, "
        "leaflogs_pack_t4_f, leaflogs_pack_t1_c, leaflogs_ambient, "
        "leaflogs_elevation_lookedup, leaflogs_ignore")


def row(ts, lat=40.5, lon=-74.0, soc=78000, gids=120, speed=30, odo=100000,
        soh=95, t1f=69, t2f=70, t3f=71, t4f=72, t1c=21, amb=72,
        elev_fixed=50.0, ignore=0):
    return (ts, lat, lon, soc, gids, speed, odo, soh,
            t1f, t2f, t3f, t4f, t1c, amb, elev_fixed, ignore)


class FeedsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn, _ = init_db(os.path.join(self.tmp.name, "test.db"))
        self.conn.executemany(
            f"INSERT INTO logs ({COLS}) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [row("2026-09-01 08:00:00"),
             row("2026-09-01 08:05:00", soc=77000, gids=115, odo=100005),
             row("2026-09-01 09:00:00", soc=76000, gids=110, odo=100010,
                 t1f=-100, ignore=1)])
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_soc_scales(self):
        self.assertEqual(
            feeds.soc_text(self.conn),
            "date,SOC,gids\n"
            "2026-09-01 08:00:00,7.8,120\n"
            "2026-09-01 08:05:00,7.7,115\n"
            "2026-09-01 09:00:00,7.6,110\n")

    def test_soc_none_blank(self):
        self.conn.execute(
            "INSERT INTO logs (leaflogs_timestamp) VALUES "
            "('2026-09-01 10:00:00')")
        out = feeds.soc_text(self.conn, start="2026-09-01 10:00:00")
        self.assertEqual(out, "date,SOC,gids\n2026-09-01 10:00:00,,\n")

    def test_thermal_us(self):
        out = feeds.thermal_text(
            self.conn, end="2026-09-01 08:05:00").split("\n")
        self.assertEqual(out[0], "date,t1,t2,t3,t4,ambient,")
        # REAL columns render as floats ("69.0"); MySQL DECIMAL gave
        # "69.0000". Same values, documented in feeds.py.
        self.assertEqual(out[1], "2026-09-01 08:00:00,69.0,70.0,71.0,72.0,72,")
        # one row per record: header + exactly the 2 records in range,
        # i.e. no trailing PHP-style empty row
        self.assertEqual([ln for ln in out if ln], out[:3])

    def test_thermal_invalid_blanked(self):
        out = feeds.thermal_text(self.conn, start="2026-09-01 09:00:00")
        # t1f=-100 -> blank, which empties the whole (single-row) column,
        # so the header renames it too (matches the PHP rule); the ignored
        # row is still included (no ignore filter, matching the PHP feed)
        self.assertTrue(out.startswith("date,empty,t2,t3,t4,ambient,\n"))
        self.assertIn("2026-09-01 09:00:00,,70.0,71.0,72.0,72,", out)

    def test_thermal_all_zero_column_renamed(self):
        self.conn.execute("UPDATE logs SET leaflogs_pack_t4_f = 0")
        out = feeds.thermal_text(
            self.conn, end="2026-09-01 08:05:00").split("\n")[0]
        self.assertEqual(out, "date,t1,t2,t3,empty,ambient,")

    def test_thermal_si_picks_celsius(self):
        out = feeds.thermal_text(
            self.conn, end="2026-09-01 08:00:00").split("\n")
        self.assertEqual(out[1], "2026-09-01 08:00:00,69.0,70.0,71.0,72.0,72,")
        out_si = feeds.thermal_text(
            self.conn, end="2026-09-01 08:00:00", units="SI").split("\n")
        # only t1 has a _c value in the test data; NULL _c cols blank out,
        # exactly as the PHP feed renders NULLs. Ambient (72 °F stored)
        # converts to °C.
        self.assertEqual(out_si[1], "2026-09-01 08:00:00,21.0,,,,22.2,")

    def test_thermal_bad_units(self):
        with self.assertRaises(ValueError):
            feeds.thermal_text(self.conn, units="K")

    def test_summary_us(self):
        self.assertEqual(
            feeds.summary_dict(self.conn, end="2026-09-01 08:05:00"),
            {"trip_length": 5, "start": 62137.1, "end": 62140.2,
             "trip": 3.1, "socDifference": 0.1, "gidsDifference": 5,
             "averageSpeed": 30.0, "speed_units": "mph",
             "distance_units": "miles"})

    def test_summary_si(self):
        summary = feeds.summary_dict(
            self.conn, end="2026-09-01 08:05:00", units="SI")
        self.assertEqual(summary["trip"], 5.0)
        self.assertEqual(summary["speed_units"], "km/h")
        self.assertEqual(summary["distance_units"], "km")

    def test_summary_empty(self):
        summary = feeds.summary_dict(self.conn, start="2030-01-01")
        self.assertEqual(summary["trip_length"], 0)
        self.assertEqual(summary["trip"], 0)
        self.assertEqual(summary["gidsDifference"], 0)

    def test_table_shape_and_feet(self):
        table = feeds.table_dict(self.conn, end="2026-09-01 08:00:00")
        self.assertEqual(table, {"aaData": [
            [1, "2026-09-01 08:00:00", "40.5", "-74.0", "", "164.0",
             "30", "7.8", "120", "95", "2026-09-01 08:00:00"]]})
        si = feeds.table_dict(
            self.conn, end="2026-09-01 08:00:00", units="SI")
        self.assertEqual(si["aaData"][0][5], "50.0")

    def test_table_excludes_ignored(self):
        table = feeds.table_dict(self.conn)
        self.assertEqual(len(table["aaData"]), 2)

    def test_generic_explicit_fields(self):
        out = feeds.generic_text(
            self.conn, ["leaflogs_timestamp", "leaflogs_soc"],
            end="2026-09-01 08:00:00")
        self.assertEqual(
            out, "leaflogs_timestamp,leaflogs_soc\n"
                 "2026-09-01 08:00:00,78000\n")

    def test_generic_rejects_unknown_and_defaults(self):
        out = feeds.generic_text(self.conn, ["bogus", "leaflogs_id"])
        self.assertTrue(out.startswith(
            "leaflogs_timestamp,leaflogs_elevation,"
            "leaflogs_elevation_lookedup\n"))

    def test_ignore_flow(self):
        result = feeds.ignore_point(self.conn, "2026-09-01 08:05:00")
        self.assertEqual(result, {"success": True, "rows": 1})
        self.assertEqual(len(feeds.table_dict(self.conn)["aaData"]), 1)
        self.assertEqual(len(feeds.track_data(self.conn)), 1)

    def test_track_shape_order_and_ignore(self):
        track = feeds.track_data(self.conn)
        self.assertEqual(len(track), 2)  # ignored row excluded
        self.assertEqual(track[0]["t"], "2026-09-01 08:00:00")
        self.assertEqual(
            set(track[0]),
            {"t", "lat", "lon", "speed", "motor_w", "aux_w", "ac_w",
             "cum_mi", "cum_eff"})
        self.assertEqual(
            [p["t"] for p in track],
            sorted(p["t"] for p in track))

    def test_track_cumulatives(self):
        track = feeds.track_data(self.conn)
        self.assertEqual(track[0]["cum_mi"], 0.0)
        self.assertIsNone(track[0]["cum_eff"])
        # same coords twice: no distance, no time passes
        self.assertEqual(track[1]["cum_mi"], 0.0)

    def test_ignore_missing_date(self):
        with self.assertRaises(ValueError):
            feeds.ignore_point(self.conn, "  ")

    def test_delete_trip_removes_range_only(self):
        result = feeds.delete_trip(
            self.conn, "2026-09-01 08:00:00", "2026-09-01 08:05:00")
        self.assertEqual(result, {"success": True, "rows": 2})
        remaining = [r[0] for r in self.conn.execute(
            "SELECT leaflogs_timestamp FROM logs ORDER BY 1")]
        self.assertEqual(remaining, ["2026-09-01 09:00:00"])
        # the survivor is ignored, so no trips remain
        self.assertEqual(find_trips(self.conn), [])

    def test_delete_trip_needs_both_bounds(self):
        with self.assertRaises(ValueError):
            feeds.delete_trip(self.conn, "2026-09-01 08:00:00", "")

    def test_delete_all(self):
        result = feeds.delete_all(self.conn)
        self.assertEqual(result, {"success": True, "rows": 3})
        n = self.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
