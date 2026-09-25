# leaflogger-py

Single-user Python app for viewing Nissan LEAF logs collected with
Leaf Spy Pro. Upload a CSV, pick a trip, and explore it: map, SOC and
thermal charts, and a point-by-point data table. No login, no
registration.

Stack: Python + FastAPI + SQLite on the backend; Leaflet/OpenStreetMap
plus Plotly and vanilla JS (no jQuery) on the frontend.

## Features

- Trip list with summary bar (distance, average speed, SOC/GIDs change)
- Map with Start/End markers and per-segment green→red efficiency
  colouring, relative to the points shown (grey when parked)
- SOC + thermal charts; hovering a chart highlights the table row
- Data table with trip-absolute node numbers, cumulative miles and
  mi/kWh, per-row ignore, and map-to-table rollover highlight
- Delete one trip (with confirm) or all records (double confirm)
- Dark mode
- US/SI units toggle

## Run

    docker compose up --build
    # open http://<host>:8084/

Data lives in `./data/leaflogger.db` (SQLite, created on first start).

## Tests

Stdlib `unittest` only, no test dependencies:

    PYTHONPATH=src python3 -m unittest discover -s tests -v

The main fixture (`tests/fixtures/real_format.csv`) is a genuine
LeafSpy export with GPS/dates shifted and the VIN replaced — see
`tools/anonymize_csv.py`.

## Privacy

Real LeafSpy exports contain your VIN and location history. Never commit
them: real-log filenames are gitignored (see `.gitignore`).

## Credits

Ported from [LeafLogger](https://github.com/kevinlieb/LeafLogger) by
[Kevin Lieb](https://github.com/kevinlieb). Many thanks for publishing
the original.

## AI disclosure

Most of the code here was written by an AI coding assistant working
from the original LeafLogger, with supervision, testing feedback, and
debugging help from the maintainer.

## License

MIT — see [LICENSE](LICENSE).
