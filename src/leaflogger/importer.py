"""LeafSpy CSV importer. Port of BatLogToDb.php::importBatLog (single-user).

Quirks preserved from the PHP original:
  * Row 0 is a header and is skipped.
  * CSV column i maps to MAPPED_FIELDS[i] (fields.php minus id/user_id).
  * Latitude/longitude arrive as "DD:MM.mmmm" (older exports) or
    "DD MM.mmmm" (current exports) and are converted to decimal degrees;
    empty string becomes 0 (kept for parity with the original, which
    stored 0 rather than NULL for missing coordinates).
  * Battery voltage has a trailing "V" stripped ("12.6V" -> 12.6).
  * The literals "none"/"na"/"n/a" (missing sensors, e.g. some model
    years or absent 12 V reading) -> NULL.
  * Any other empty field -> NULL (column left out of the INSERT).
  * Timestamps are normalised to "YYYY-MM-DD HH:MM:SS".
  * A row whose timestamp already exists is counted as a dup and skipped.

Deliberate differences from the original:
  * No users_id anywhere (single user).
  * The PHP loop bound was ($max - 2), silently dropping the last two
    columns of short rows (rows narrower than fields.php). This importer
    maps every column present in MAPPED_FIELDS.
  * hvolt1/hvolt2 exist as real columns in schema.sql for newer LeafSpy
    exports; they are not yet in MAPPED_FIELDS because no sample file
    with those columns exists. When one appears, append them to
    csv_fields.MAPPED_FIELDS in schema order and they will import.
  * Dedup is also enforced by UNIQUE(logs.leaflogs_timestamp).
"""
import csv
from datetime import datetime

from .csv_fields import MAPPED_FIELDS

LAT_FIELDS = {"leaflogs_lat", "leaflogs_lon"}

_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",   # canonical LeafSpy / normalised form
    "%Y-%m-%d %H:%M",      # minute resolution
    "%m/%d/%y %H:%M:%S",   # US short form some exports use
    "%m/%d/%Y %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
)


def funky_to_decimal(raw):
    """Convert LeafSpy "DD:MM.mmmm" (older exports) or "DD MM.mmmm"
    (current exports, space-separated) to decimal degrees, preserving sign.

    Note: the PHP original only split on ":". Space-form coordinates fell
    through to `$pos[0] + ($pos[1] / 60)` with $pos[1] unset, i.e. they
    were stored truncated to whole degrees (28.0 instead of 28.5958).
    This port parses both forms correctly.
    """
    text = raw.strip()
    if ":" in text:
        deg, _, minutes = text.partition(":")
    else:
        deg, _, minutes = text.partition(" ")
        if not minutes:
            deg, _, minutes = text.partition("\t")
    deg = float(deg)
    minutes = float(minutes) if minutes.strip() else 0.0
    if deg > 0:
        return deg + minutes / 60.0
    return -(abs(deg) + minutes / 60.0)


#: Cell literals meaning "no reading" -> NULL. PHP only knew "" and the
#: exact string "none"; real exports also use "na" (e.g. missing 12 V
#: battery voltage, which PHP stored as MySQL-coerced 0).
NULL_LITERALS = {"", "none", "na", "n/a"}


def parse_timestamp(raw):
    """Normalise a timestamp string to "YYYY-MM-DD HH:MM:SS"."""
    text = raw.strip()
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError(f"Unparseable timestamp: {raw!r}")


def convert_value(field, raw):
    """Convert one raw CSV cell. Returns (present, value); present=False
    means the column is left out of the INSERT (stored as NULL)."""
    if raw is None:
        return False, None
    text = raw.strip()
    if text.lower() in NULL_LITERALS:
        if field in LAT_FIELDS and text == "":
            return True, 0  # parity: PHP stored 0 for missing coords
        return False, None
    if field in LAT_FIELDS:
        return True, funky_to_decimal(text)
    if field == "leaflogs_timestamp":
        return True, parse_timestamp(text)
    if field == "leaflogs_batvolt":
        text = text.replace("V", "")
    return True, text


def import_csv(conn, path):
    """Import a LeafSpy CSV file into the logs table.

    Returns {"processed", "dups", "errors", "inserted", "errorStrings"}
    mirroring the PHP return shape.
    """
    stats = {"processed": 0, "dups": 0, "errors": 0,
             "inserted": 0, "errorStrings": []}
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        for row_num, data in enumerate(reader):
            if row_num == 0:
                continue  # header row
            stats["processed"] += 1
            record = {}
            width = min(len(data), len(MAPPED_FIELDS))
            try:
                for col in range(width):
                    field = MAPPED_FIELDS[col]
                    present, value = convert_value(field, data[col])
                    if present:
                        record[field] = value
            except ValueError as exc:
                stats["errors"] += 1
                stats["errorStrings"].append(f"Row {row_num + 1}: {exc}")
                continue
            if "leaflogs_timestamp" not in record:
                stats["errors"] += 1
                stats["errorStrings"].append(
                    f"Row {row_num + 1}: missing timestamp, skipped")
                continue
            cur = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE leaflogs_timestamp = ?",
                (record["leaflogs_timestamp"],))
            if cur.fetchone()[0] > 0:
                stats["dups"] += 1
                continue
            columns = ", ".join(record)
            placeholders = ", ".join("?" for _ in record)
            try:
                conn.execute(
                    f"INSERT INTO logs ({columns}) VALUES ({placeholders})",
                    tuple(record.values()))
                stats["inserted"] += 1
            except Exception as exc:  # e.g. UNIQUE race on timestamp
                stats["errors"] += 1
                stats["errorStrings"].append(
                    f"Row {row_num + 1} ({record['leaflogs_timestamp']}): {exc}")
    conn.commit()
    return stats
