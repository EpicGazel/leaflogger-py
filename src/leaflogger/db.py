"""SQLite helpers."""
import os
import sqlite3

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "schema.sql")


def get_connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path, schema_path=SCHEMA_PATH):
    fresh = not os.path.exists(path)
    conn = get_connection(path)
    with open(schema_path) as fh:
        conn.executescript(fh.read())
    conn.commit()
    return conn, fresh
