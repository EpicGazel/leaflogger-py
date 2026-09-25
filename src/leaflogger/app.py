"""leaflogger-py API. Single user, no auth (bind to LAN only)."""
import os
import tempfile

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import feeds
from .db import init_db
from .importer import import_csv
from .trips import find_trips

DB_PATH = os.environ.get("LEAFLOGGER_DB", "/data/leaflogger.db")
TRIP_DELIMITER_MINUTES = int(os.environ.get("LEAFLOGGER_TRIP_GAP_MIN", "10"))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="leaflogger-py")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


def _conn():
    conn, _ = init_db(DB_PATH)
    return conn


@app.get("/health")
def health():
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    conn.close()
    return {"ok": True, "records": n}


@app.post("/upload")
def upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(400, "expected a LeafSpy .csv file")
    with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name
    try:
        conn = _conn()
        try:
            stats = import_csv(conn, tmp_path)
        finally:
            conn.close()
    finally:
        os.unlink(tmp_path)
    return stats


@app.get("/trips")
def trips():
    conn = _conn()
    result = find_trips(conn, TRIP_DELIMITER_MINUTES)
    conn.close()
    return result


@app.get("/soc", response_class=PlainTextResponse)
def soc(start: str = Query(default=None), end: str = Query(default=None)):
    conn = _conn()
    try:
        return feeds.soc_text(conn, start, end)
    finally:
        conn.close()


@app.get("/thermal", response_class=PlainTextResponse)
def thermal(start: str = Query(default=None), end: str = Query(default=None),
            units: str = Query(default="US")):
    conn = _conn()
    try:
        return feeds.thermal_text(conn, start, end, units)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.get("/summary")
def summary(start: str = Query(default=None), end: str = Query(default=None),
            units: str = Query(default="US")):
    conn = _conn()
    try:
        return feeds.summary_dict(conn, start, end, units)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.get("/table")
def table(start: str = Query(default=None), end: str = Query(default=None),
          units: str = Query(default="US")):
    conn = _conn()
    try:
        return feeds.table_dict(conn, start, end, units)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.get("/feed", response_class=PlainTextResponse)
def feed(fields: str = Query(default=""),
         start: str = Query(default=None), end: str = Query(default=None)):
    conn = _conn()
    try:
        return feeds.generic_text(conn, fields.split(","), start, end)
    finally:
        conn.close()


@app.get("/track")
def track(start: str = Query(default=None), end: str = Query(default=None)):
    conn = _conn()
    try:
        return feeds.track_data(conn, start, end)
    finally:
        conn.close()


@app.post("/ignore")
def ignore(date: str = Query(default="")):
    conn = _conn()
    try:
        return feeds.ignore_point(conn, date)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.delete("/trip")
def delete_trip(start: str = Query(default=""),
                end: str = Query(default="")):
    conn = _conn()
    try:
        return feeds.delete_trip(conn, start, end)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.delete("/records")
def delete_records():
    conn = _conn()
    try:
        return feeds.delete_all(conn)
    finally:
        conn.close()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
