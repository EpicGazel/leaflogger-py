"""Trip detection. Port of functions.php::findTripInfo (single-user).

A trip boundary is any gap between consecutive (non-ignored) records
longer than delimiter_minutes (default 10, the old users_trip_delimiter).
Units handling (mph/miles vs km/h/km) is left to the presentation layer;
this module returns raw start/end timestamps plus record counts.
"""
from datetime import datetime

_TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"


def _to_epoch(ts):
    return int(datetime.strptime(ts, _TIMESTAMP_FMT).timestamp())


def find_trips(conn, delimiter_minutes=10):
    cur = conn.execute(
        "SELECT leaflogs_timestamp FROM logs "
        "WHERE leaflogs_ignore = 0 OR leaflogs_ignore IS NULL "
        "ORDER BY leaflogs_timestamp ASC")
    starts, ends, counts = [], [], []
    prev_epoch, prev_ts, pending = 0, "", 0
    records = 0
    for (ts,) in cur:
        epoch = _to_epoch(ts)
        if epoch - prev_epoch > delimiter_minutes * 60:
            starts.append(ts)
            if records > 0:
                ends.append(prev_ts)
                counts.append(pending)
                pending = 0
        prev_epoch, prev_ts = epoch, ts
        records += 1
        pending += 1
    if prev_ts:
        ends.append(prev_ts)
        counts.append(pending)
    return [{"start": s, "end": e, "records": c}
            for s, e, c in zip(starts, ends, counts)]
