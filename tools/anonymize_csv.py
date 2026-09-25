#!/usr/bin/env python3
"""Anonymize a real LeafSpy export for use as a public test fixture.

Strips the three things that identify the driver while preserving the
file's value as a format test (real headers, US timestamps,
space-separated coordinates, 161 columns, "na" literals, trip gaps):
  * GPS coordinates shifted by a fixed offset (route shape preserved).
  * Timestamps shifted back by a fixed number of days (gaps preserved,
    so trip splitting is unaffected).
  * VIN replaced with a placeholder.

Usage:
    python3 tools/anonymize_csv.py tests/fixtures/Log_xxx.csv \\
        -o tests/fixtures/real_format.csv
"""
import argparse
import csv
from datetime import datetime, timedelta

LAT_OFFSET = 5.0
LON_OFFSET = -5.0
DAY_SHIFT = -400
VIN_PLACEHOLDER = "TESTVINREAL000001"
TS_FMT = "%Y-%m-%d %H:%M:%S"


def shift_coord(text, offset):
    text = text.strip()
    sep = ":" if ":" in text else " "
    deg, _, minutes = text.partition(sep)
    deg = float(deg)
    minutes = float(minutes) if minutes.strip() else 0.0
    base = deg + minutes / 60.0 if deg > 0 else deg - minutes / 60.0
    shifted = base + offset
    sign = -1 if shifted < 0 else 1
    whole = int(abs(shifted))
    mins = (abs(shifted) - whole) * 60.0
    return f"{sign * whole}:{mins:07.4f}"


def shift_ts(text):
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%m/%d/%y %H:%M:%S"):
        try:
            dt = datetime.strptime(text.strip(), fmt)
            return (dt + timedelta(days=DAY_SHIFT)).strftime(TS_FMT)
        except ValueError:
            continue
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("-o", "--out", required=True)
    args = parser.parse_args()
    with open(args.src, newline="") as fh:
        rows = list(csv.reader(fh))
    header, data = rows[0], rows[1:]
    lat_i = next(i for i, h in enumerate(header) if h.lower() == "lat")
    lon_i = next(i for i, h in enumerate(header) if h.lower() == "long")
    vin_i = next((i for i, h in enumerate(header)
                  if "vin" in h.lower()), None)
    for row in data:
        row[0] = shift_ts(row[0])
        row[lat_i] = shift_coord(row[lat_i], LAT_OFFSET)
        row[lon_i] = shift_coord(row[lon_i], LON_OFFSET)
        if vin_i is not None and len(row) > vin_i:
            row[vin_i] = VIN_PLACEHOLDER
    with open(args.out, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(data)
    print(f"wrote {len(data)} anonymized rows to {args.out}")


if __name__ == "__main__":
    main()
