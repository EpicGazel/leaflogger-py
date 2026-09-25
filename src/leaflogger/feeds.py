"""Chart/read feeds. Single-user; no auth layer (bind to LAN only).

Conventions:
  * start/end filter inclusive (>= / <=), "YYYY-MM-DD HH:MM:SS".
  * units come from a `units=US|SI` parameter (default US).
  * CSV-ish feeds return plain text with stable headers/column order.
  * start/end are bound parameters, never interpolated.

Deliberate deviations from the PHP originals (all covered by tests):
  * /thermal emits exactly one row per record. The PHP loop ran
    0..numRecords inclusive, appending one extra all-empty row.
  * Decimal rendering differs: MySQL DECIMAL came back with trailing
    zeros ("40.500000", "69.0000"); SQLite REAL renders as "40.5", "69.0".
    Numeric values are identical; chart code parses floats.
  * Trip length is computed in UTC rather than inheriting container TZ.
  * POST /ignore with a missing date is a 400, not a 200 {"error": ...}.
"""
import calendar
import math
from datetime import datetime

from .csv_fields import MAPPED_FIELDS

ALLOWED_FEED_FIELDS = [f for f in MAPPED_FIELDS
                       if f not in ("leaflogs_id", "leaflogs_user_id")]
ALLOWED_FEED_FIELDS.append("leaflogs_elevation_lookedup")

DEFAULT_FEED_FIELDS = ["leaflogs_timestamp", "leaflogs_elevation",
                       "leaflogs_elevation_lookedup"]

MILES_MULTIPLIER = 0.621371
FEET_PER_METER = 3.28084

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _epoch_utc(ts):
    return calendar.timegm(datetime.strptime(ts, _TS_FMT).timetuple())


def _haversine_miles(lat1, lon1, lat2, lon2):
    """Statute miles, same formula as the frontend distance()."""
    rad = math.radians
    dist = (math.sin(rad(lat1)) * math.sin(rad(lat2)) +
            math.cos(rad(lat1)) * math.cos(rad(lat2)) *
            math.cos(rad(lon1 - lon2)))
    dist = min(1.0, max(-1.0, dist))
    return math.degrees(math.acos(dist)) * 60 * 1.1515


def _hours_between(earlier, later):
    try:
        delta = (_epoch_utc(later) - _epoch_utc(earlier)) / 3600.0
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, delta)


def _range_clause(start, end):
    clauses, params = [], []
    if start:
        clauses.append("leaflogs_timestamp >= ?")
        params.append(start)
    if end:
        clauses.append("leaflogs_timestamp <= ?")
        params.append(end)
    return clauses, params


def _check_units(units):
    units = (units or "US").upper()
    if units not in ("US", "SI"):
        raise ValueError("units must be US or SI")
    return units


def _php_zero_string(value):
    """String form PHP array_unique() would see (SORT_STRING): NULL -> "",
    numeric zero -> "0". A column is "empty" iff exactly one such string
    exists and it is "" or "0" (PHP loose == 0)."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) and value == 0:
        return "0"
    return str(value)


def _text(value):
    return "" if value is None else str(value)


def soc_text(conn, start=None, end=None):
    """SOC/GIDs CSV for the SOC chart. soc is stored x10000 (matches)."""
    clauses, params = _range_clause(start, end)
    sql = "SELECT leaflogs_timestamp, leaflogs_soc, leaflogs_gids FROM logs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY leaflogs_timestamp"
    out = ["date,SOC,gids\n"]
    for ts, soc, gids in conn.execute(sql, params):
        scaled = "" if soc is None else str(soc / 10000)
        out.append(f"{ts},{scaled},{_text(gids)}\n")
    return "".join(out)


def thermal_text(conn, start=None, end=None, units="US"):
    """Temperature CSV. Picks _f/_c columns by units; invalid (<-90)
    readings blanked; all-zero/blank columns renamed to "empty" (the
    frontend hides series by that name)."""
    units = _check_units(units)
    suffix = "_f" if units == "US" else "_c"
    temp_cols = [f"leaflogs_pack_t{i}{suffix}" for i in (1, 2, 3, 4)]
    clauses, params = _range_clause(start, end)
    sql = ("SELECT leaflogs_timestamp, " + ", ".join(temp_cols) +
           ", leaflogs_ambient FROM logs")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY leaflogs_timestamp"
    rows = list(conn.execute(sql, params))

    names = ["date", "t1", "t2", "t3", "t4", "ambient"]
    table = [[] for _ in names]
    for row in rows:
        table[0].append(row[0])
        for n in range(1, 6):
            value = row[n]
            if value is None or (isinstance(value, (int, float))
                                 and value < -90):
                value = ""
            table[n].append(value)
    if units == "SI":
        # Ambient has no _c column (LeafSpy logs it once, in °F here);
        # convert for SI display. Blanked readings stay blank.
        table[5] = ["" if v == "" else round((v - 32) * 5 / 9, 1)
                    for v in table[5]]
    for n in range(1, 6):
        uniq = {_php_zero_string(v) for v in table[n]}
        if len(uniq) == 1 and next(iter(uniq)) in ("", "0"):
            names[n] = "empty"
    out = [",".join(names) + ",\n"]
    for i in range(len(rows)):
        out.append(",".join(_text(table[n][i]) for n in range(6)) + ",\n")
    return "".join(out)


def summary_dict(conn, start=None, end=None, units="US"):
    """Trip summary JSON: length, odometer range, distance, SOC/GIDs
    change, average speed, unit labels."""
    units = _check_units(units)
    if units == "US":
        speed_units, distance_units, mult = "mph", "miles", MILES_MULTIPLIER
    else:
        speed_units, distance_units, mult = "km/h", "km", 1
    clauses, params = _range_clause(start, end)
    sql = ("SELECT MIN(leaflogs_timestamp), MAX(leaflogs_timestamp), "
           "MIN(leaflogs_odometer), MAX(leaflogs_odometer), "
           "AVG(leaflogs_speed), MIN(leaflogs_gids), MAX(leaflogs_gids), "
           "MIN(leaflogs_soc), MAX(leaflogs_soc) FROM logs")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    row = conn.execute(sql, params).fetchone()
    (start_ts, end_ts, start_odo, end_odo, avg_speed,
     min_gids, max_gids, min_soc, max_soc) = row

    def num(v):
        return 0 if v is None else v
    length = (round((_epoch_utc(end_ts) - _epoch_utc(start_ts)) / 60, 0)
              if start_ts and end_ts else 0)
    return {
        "trip_length": length,
        "start": round(num(start_odo) * mult, 1),
        "end": round(num(end_odo) * mult, 1),
        "trip": round((num(end_odo) - num(start_odo)) * mult, 1),
        "socDifference": round(abs((num(max_soc) - num(min_soc)) / 10000), 1),
        "gidsDifference": abs(num(max_gids) - num(min_gids)),
        "averageSpeed": round(num(avg_speed), 1),
        "speed_units": speed_units,
        "distance_units": distance_units,
    }


def table_dict(conn, start=None, end=None, units="US"):
    """Data-table feed in {"aaData": [[n, ...], ...]} shape."""
    units = _check_units(units)
    clauses = ["(leaflogs_ignore = 0 OR leaflogs_ignore IS NULL)"]
    r_clauses, params = _range_clause(start, end)
    clauses += r_clauses
    sql = ("SELECT leaflogs_timestamp, leaflogs_lat, leaflogs_lon, "
           "leaflogs_elevation, leaflogs_elevation_lookedup, leaflogs_speed, "
           "leaflogs_soc, leaflogs_gids, leaflogs_soh, leaflogs_timestamp "
           "FROM logs WHERE " + " AND ".join(clauses) +
           " ORDER BY leaflogs_timestamp")
    aa_data = []
    for n, row in enumerate(conn.execute(sql, params), start=1):
        (ts, lat, lon, elev, elev_fixed, speed,
         soc, gids, soh, ts2) = row
        soc = "" if soc is None else str(round(soc / 10000, 1))
        if elev_fixed is None:
            elev_fixed = ""
        elif units == "US":
            elev_fixed = str(round(elev_fixed * FEET_PER_METER, 1))
        else:
            elev_fixed = str(elev_fixed)
        aa_data.append([n, _text(ts), _text(lat), _text(lon), _text(elev),
                        elev_fixed, _text(speed), soc, _text(gids),
                        _text(soh), _text(ts2)])
    return {"aaData": aa_data}


def generic_text(conn, fields, start=None, end=None):
    """Arbitrary-column CSV. Unknown columns rejected."""
    selected = [f.strip() for f in (fields or []) if f.strip()
                in ALLOWED_FEED_FIELDS]
    if not selected:
        selected = list(DEFAULT_FEED_FIELDS)
    clauses = ["(leaflogs_ignore = 0 OR leaflogs_ignore IS NULL)"]
    r_clauses, params = _range_clause(start, end)
    clauses += r_clauses
    quoted = ", ".join(f'"{c}"' for c in selected)
    sql = (f"SELECT {quoted} FROM logs WHERE " + " AND ".join(clauses) +
           " ORDER BY leaflogs_timestamp")
    out = [",".join(selected) + "\n"]
    for row in conn.execute(sql, params):
        out.append(",".join(_text(v) for v in row) + "\n")
    return "".join(out)


def ignore_point(conn, date):
    """Flag one record ignored by timestamp. Returns rows affected."""
    if not (date or "").strip():
        raise ValueError("No date supplied")
    cur = conn.execute(
        "UPDATE logs SET leaflogs_ignore = 1 WHERE leaflogs_timestamp = ?",
        (date.strip(),))
    conn.commit()
    return {"success": True, "rows": cur.rowcount}


def delete_trip(conn, start, end):
    """Delete every record in [start, end]. A "trip" is a time range here
    (trips are derived from gaps, not stored), so deleting one is a range
    delete. Returns rows deleted."""
    if not (start or "").strip() or not (end or "").strip():
        raise ValueError("Both start and end are required")
    cur = conn.execute(
        "DELETE FROM logs WHERE leaflogs_timestamp >= ? "
        "AND leaflogs_timestamp <= ?",
        (start.strip(), end.strip()))
    conn.commit()
    return {"success": True, "rows": cur.rowcount}


def delete_all(conn):
    """Delete every log record. The frontend guards this behind confirm
    dialogs; there is no undo short of re-uploading."""
    cur = conn.execute("DELETE FROM logs")
    conn.commit()
    return {"success": True, "rows": cur.rowcount}


def track_data(conn, start=None, end=None):
    """Per-point track for the map: timestamp, lat/lon, speed, power,
    plus cumulative distance (statute miles) and cumulative efficiency
    (miles per kWh) "thus far", integrated over the returned points.

    The frontend colours each segment by relative efficiency
    (speed per kW, min-max normalised over the returned range).
    Power columns may be NULL (stored as None -> treated as 0 client-side);
    if a log has no power data at all the map falls back to one colour.
    cum_eff is None until any energy has been used.
    """
    clauses = ["(leaflogs_ignore = 0 OR leaflogs_ignore IS NULL)",
               "leaflogs_lat != 0"]
    r_clauses, params = _range_clause(start, end)
    clauses += r_clauses
    sql = ("SELECT leaflogs_timestamp, leaflogs_lat, leaflogs_lon, "
           "leaflogs_speed, leaflogs_power_motor, leaflogs_power_aux, "
           "leaflogs_power_ac FROM logs WHERE " + " AND ".join(clauses) +
           " ORDER BY leaflogs_timestamp")
    track = [{"t": ts, "lat": lat, "lon": lon, "speed": speed,
              "motor_w": motor, "aux_w": aux, "ac_w": ac}
             for ts, lat, lon, speed, motor, aux, ac
             in conn.execute(sql, params)]
    cum_mi, cum_kwh = 0.0, 0.0
    for i, p in enumerate(track):
        if i > 0:
            prev = track[i - 1]
            cum_mi += _haversine_miles(prev["lat"], prev["lon"],
                                       p["lat"], p["lon"])
            kw = ((p["motor_w"] or 0) + (p["aux_w"] or 0) +
                  (p["ac_w"] or 0)) / 1000.0
            cum_kwh += kw * _hours_between(prev["t"], p["t"])
        p["cum_mi"] = cum_mi
        p["cum_eff"] = cum_mi / cum_kwh if cum_kwh > 0 else None
    return track
