"""SQLite snapshots; optimistic concurrency and approval are atomic."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("REPORT_DATA_DIR", ROOT / "data"))


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / "reports.sqlite3", timeout=20)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
          id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL,
          stage TEXT NOT NULL, approval TEXT, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions (
          report_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
          note TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(report_id, revision));
        CREATE TABLE IF NOT EXISTS templates (
          id TEXT PRIMARY KEY, profile TEXT NOT NULL, approved INTEGER NOT NULL,
          metadata TEXT NOT NULL, created TEXT NOT NULL);
        """)


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def decode(row):
    return {"id": row["id"], "revision": row["revision"], "report": json.loads(row["body"]),
            "stage": row["stage"], "approval": json.loads(row["approval"]) if row["approval"] else None,
            "updated": row["updated"]}


def get(report_id):
    with connect() as con:
        row = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if row is None:
        raise KeyError("보고서를 찾을 수 없습니다.")
    return decode(row)


def create(report_id, report):
    body, stamp = dump(report), now()
    with connect() as con:
        con.execute("INSERT INTO reports VALUES (?,1,?,'draft',NULL,?)", (report_id, body, stamp))
        con.execute("INSERT INTO revisions VALUES (?,1,?,?,?)", (report_id, body, "보고서 생성", stamp))
    return get(report_id)


def save(report_id, revision, report, note, stage="draft", approval=None):
    body, stamp = dump(report), now()
    with connect() as con:
        result = con.execute("UPDATE reports SET revision=revision+1, body=?, stage=?, approval=?, updated=? WHERE id=? AND revision=?",
                             (body, stage, dump(approval) if approval else None, stamp, report_id, revision))
        if result.rowcount != 1:
            raise ValueError("다른 창에서 문서가 변경되었습니다. 다시 불러온 뒤 수정해 주세요.")
        con.execute("INSERT INTO revisions VALUES (?,?,?,?,?)", (report_id, revision + 1, body, note, stamp))
    return get(report_id)

