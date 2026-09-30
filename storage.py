"""
Append-only record store for assessment runs.

Appendix D of the manuscript requires assessment records to be versioned so that
changes are compared rather than overwritten. This module provides that: every
run is written once, keyed by a sequential identifier, and nothing is ever
updated or deleted in place.

It performs no engineering calculation. It stores the inputs it was given and the
record assessment_framework.py produced, and it can hand either one back.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional


def _default_db_path() -> Path:
    """
    Beside the code when that folder is writable, as it is locally. Serverless hosts
    such as Vercel only allow writes to the temporary directory, so the store moves
    there; its history then lasts only as long as the running instance.
    EAF_DB_PATH overrides both.
    """
    if os.environ.get("EAF_DB_PATH"):
        return Path(os.environ["EAF_DB_PATH"])
    here = Path(__file__).parent
    if not os.environ.get("VERCEL") and os.access(here, os.W_OK):
        return here / "assessment_records.db"
    return Path(tempfile.gettempdir()) / "assessment_records.db"


DB_PATH = _default_db_path()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    seq               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT    NOT NULL UNIQUE,
    created_utc       TEXT    NOT NULL,
    facility          TEXT    NOT NULL DEFAULT '',
    assessor          TEXT    NOT NULL DEFAULT '',
    eem_label         TEXT    NOT NULL DEFAULT '',
    case_id           TEXT,
    case_run_key      TEXT,
    selected_mode     TEXT    NOT NULL,
    override          INTEGER NOT NULL,
    gate_passed       INTEGER NOT NULL,
    input_sha256      TEXT    NOT NULL,
    framework_sha256  TEXT    NOT NULL,
    framework_version TEXT    NOT NULL,
    input_json        TEXT    NOT NULL,
    record_json       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_created ON runs (created_utc DESC);
CREATE INDEX IF NOT EXISTS runs_case    ON runs (case_id, case_run_key);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """
    One transaction, then close.

    sqlite3's own context manager commits but leaves the connection open, which on
    Windows keeps a lock on the file. Closing here lets a scratch database be
    deleted afterwards, which verify.py relies on.
    """
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialise() -> None:
    with _connect() as connection:
        connection.executescript(SCHEMA)


def digest(payload: Any) -> str:
    """
    Content identity for a set of inputs.

    Two runs with the same digest were given byte-identical inputs, which is what
    lets a reviewer confirm that a figure can be regenerated. Keys are sorted so
    the digest depends on the values, not on dictionary ordering.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(
    *,
    created_utc: str,
    facility: str,
    assessor: str,
    eem_label: str,
    case_id: Optional[str],
    case_run_key: Optional[str],
    selected_mode: str,
    override: bool,
    gate_passed: bool,
    input_payload: dict,
    record: dict,
    framework_sha256: str,
    framework_version: str,
) -> str:
    """
    Writes one run and returns its identifier.

    The identifier comes from the table's own sequence rather than from a hash of
    the facility name, so it is stable across restarts and orders the way an audit
    log is expected to.
    """
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO runs (
                run_id, created_utc, facility, assessor, eem_label,
                case_id, case_run_key, selected_mode, override, gate_passed,
                input_sha256, framework_sha256, framework_version,
                input_json, record_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "pending",
                created_utc,
                facility,
                assessor,
                eem_label,
                case_id,
                case_run_key,
                selected_mode,
                int(override),
                int(gate_passed),
                digest(input_payload),
                framework_sha256,
                framework_version,
                json.dumps(input_payload, sort_keys=True),
                json.dumps(record),
            ),
        )
        run_id = f"EAF-{cursor.lastrowid:04d}"
        connection.execute(
            "UPDATE runs SET run_id = ? WHERE seq = ?", (run_id, cursor.lastrowid)
        )
    return run_id


def _row_to_summary(row: sqlite3.Row) -> dict:
    return {
        "run_id": row["run_id"],
        "created_utc": row["created_utc"],
        "facility": row["facility"],
        "assessor": row["assessor"],
        "eem_label": row["eem_label"],
        "case_id": row["case_id"],
        "case_run_key": row["case_run_key"],
        "selected_mode": row["selected_mode"],
        "override": bool(row["override"]),
        "gate_passed": bool(row["gate_passed"]),
        "input_sha256": row["input_sha256"],
    }


def recent(limit: int = 40) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM runs ORDER BY seq DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_summary(row) for row in rows]


def load(run_id: str) -> Optional[dict]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        **_row_to_summary(row),
        "framework_sha256": row["framework_sha256"],
        "framework_version": row["framework_version"],
        "inputs": json.loads(row["input_json"]),
        "record": json.loads(row["record_json"]),
    }


def latest_for_case(case_id: str, case_run_key: str) -> Optional[dict]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT run_id FROM runs
            WHERE case_id = ? AND case_run_key = ?
            ORDER BY seq DESC LIMIT 1
            """,
            (case_id, case_run_key),
        ).fetchone()
    return load(row["run_id"]) if row else None
