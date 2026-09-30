import json
import sqlite3
from contextlib import closing
from datetime import datetime

from core.config import ROOT, database_path
from core.reply import criteria_errors

SCHEMA_FILE = ROOT / "database" / "schema.sql"

DEFAULT_CRITERIA = [
    (1, "Technical Capability", "Architecture, integrations, scalability, technical fit", 35),
    (2, "Implementation Plan", "Timeline, milestones, staffing, risk plan", 15),
    (3, "Commercial Value", "Pricing clarity, total cost, assumptions", 20),
    (4, "Security & Compliance", "Controls, certifications, privacy, auditability", 20),
    (5, "Support & Experience", "Support model, similar projects, references", 10),
]


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def prepare_database(reset_criteria=False):
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    with closing(connect()) as connection:
        with connection:
            connection.executescript(schema)
            if reset_criteria:
                connection.execute("DELETE FROM criteria")
            count = connection.execute("SELECT COUNT(*) FROM criteria").fetchone()[0]
            if count == 0:
                seed_defaults(connection)


def seed_defaults(connection):
    stamp = now_text()
    for criterion_id, name, description, weight in DEFAULT_CRITERIA:
        connection.execute(
            "INSERT INTO criteria (criterion_id, name, description, weight, max_score, is_active, "
            "updated_at) VALUES (?, ?, ?, ?, 10, 1, ?)",
            (criterion_id, name, description, weight, stamp),
        )


def criterion_row(row):
    return {
        "id": row["criterion_id"],
        "title": row["name"],
        "guidance": row["description"],
        "weight": row["weight"],
        "max_points": row["max_score"],
        "active": bool(row["is_active"]),
    }


def list_criteria(active_only=False):
    query = "SELECT * FROM criteria"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY criterion_id"
    with closing(connect()) as connection:
        rows = connection.execute(query).fetchall()
    return [criterion_row(row) for row in rows]


def clean_id(value):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if number < 1:
        return None
    return number


def assign_ids(rows):
    used = set()
    for row in rows:
        number = clean_id(row.get("id"))
        if number is not None and number not in used:
            used.add(number)
    next_id = max(used, default=0) + 1
    ready = []
    taken = set()
    for row in rows:
        number = clean_id(row.get("id"))
        if number is None or number in taken:
            number = next_id
            next_id += 1
        taken.add(number)
        ready.append((number, row))
    return ready


def replace_criteria(rows):
    rows = list(rows)
    errors = criteria_errors(rows)
    if errors:
        raise ValueError("\n".join(errors))
    stamp = now_text()
    with closing(connect()) as connection:
        with connection:
            connection.execute("DELETE FROM criteria")
            for number, row in assign_ids(rows):
                connection.execute(
                    "INSERT INTO criteria (criterion_id, name, description, weight, max_score, is_active, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        number,
                        str(row["title"]).strip(),
                        str(row.get("guidance") or "").strip(),
                        float(row["weight"]),
                        float(row["max_points"]),
                        1 if bool(row.get("active")) else 0,
                        stamp,
                    ),
                )
    return list_criteria()


def create_run(run_id, name, model, criteria):
    with closing(connect()) as connection:
        with connection:
            connection.execute(
                "INSERT INTO evaluation_runs (rfp_run_id, name, created_at, status, model, criteria_json) "
                "VALUES (?, ?, ?, 'RUNNING', ?, ?)",
                (run_id, name, now_text(), model, json.dumps(criteria)),
            )


def finish_run(run_id, state, notes):
    with closing(connect()) as connection:
        with connection:
            connection.execute(
                "UPDATE evaluation_runs SET status = ?, finished_at = ?, notes_json = ? WHERE rfp_run_id = ?",
                (state, now_text(), json.dumps(list(notes)), run_id),
            )


def save_scores(run_id, suppliers):
    with closing(connect()) as connection:
        with connection:
            connection.execute("DELETE FROM supplier_scores WHERE rfp_run_id = ?", (run_id,))
            for supplier in suppliers:
                connection.execute(
                    "INSERT INTO supplier_scores (rfp_run_id, supplier_name, submission_date, "
                    "experience_rating, file_name, absolute_score, ppi, final_rank, result_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        supplier["supplier"],
                        str(supplier["submitted_on"]),
                        float(supplier["experience"]),
                        supplier.get("filename", ""),
                        supplier["absolute"],
                        supplier["ppi"],
                        supplier["rank"],
                        json.dumps(supplier, ensure_ascii=False),
                    ),
                )


def add_audit(run_id, action, supplier=None, criterion_id=None, old_value=None, new_value=None, note=""):
    with closing(connect()) as connection:
        with connection:
            connection.execute(
                "INSERT INTO audit_log (rfp_run_id, happened_at, action, supplier_name, criterion_id, "
                "old_value, new_value, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, now_text(), action, supplier, criterion_id, old_value, new_value, note),
            )


def runs_overview():
    query = (
        "SELECT r.rfp_run_id, r.created_at, r.status, r.name, r.model, r.locked, "
        "(SELECT COUNT(*) FROM supplier_scores s WHERE s.rfp_run_id = r.rfp_run_id) AS supplier_count, "
        "(SELECT s.supplier_name FROM supplier_scores s WHERE s.rfp_run_id = r.rfp_run_id "
        "AND s.final_rank = 1) AS top_supplier "
        "FROM evaluation_runs r ORDER BY r.created_at DESC, r.rfp_run_id DESC"
    )
    with closing(connect()) as connection:
        rows = connection.execute(query).fetchall()
    overview = []
    for row in rows:
        overview.append(
            {
                "run_id": row["rfp_run_id"],
                "started_at": row["created_at"],
                "state": row["status"],
                "name": row["name"],
                "model": row["model"],
                "locked": bool(row["locked"]),
                "supplier_count": row["supplier_count"],
                "top_supplier": row["top_supplier"] or "",
            }
        )
    return overview


def audit_row(row):
    return {
        "at": row["happened_at"],
        "action": row["action"],
        "supplier": row["supplier_name"],
        "criterion_id": row["criterion_id"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "note": row["note"],
    }


def load_run(run_id):
    with closing(connect()) as connection:
        run = connection.execute("SELECT * FROM evaluation_runs WHERE rfp_run_id = ?", (run_id,)).fetchone()
        if run is None:
            return None
        scores = connection.execute(
            "SELECT result_json FROM supplier_scores WHERE rfp_run_id = ? ORDER BY final_rank", (run_id,)
        ).fetchall()
        audit = connection.execute(
            "SELECT * FROM audit_log WHERE rfp_run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return {
        "run_id": run["rfp_run_id"],
        "name": run["name"],
        "state": run["status"],
        "model": run["model"],
        "started_at": run["created_at"],
        "finished_at": run["finished_at"],
        "locked": bool(run["locked"]),
        "locked_at": run["locked_at"],
        "lock_note": run["lock_note"],
        "criteria": json.loads(run["criteria_json"]),
        "notes": json.loads(run["notes_json"]),
        "suppliers": [json.loads(row["result_json"]) for row in scores],
        "audit": [audit_row(row) for row in audit],
    }


def remove_run(run_id):
    with closing(connect()) as connection:
        with connection:
            connection.execute("DELETE FROM evaluation_runs WHERE rfp_run_id = ?", (run_id,))


def lock_decision(run_id, note):
    run = load_run(run_id)
    if run is None:
        raise ValueError(f"Run {run_id} was not found.")
    if run["locked"]:
        raise ValueError(f"Run {run_id} is already locked.")
    if run["state"] != "COMPLETED":
        raise ValueError("Only a completed run can be locked.")
    note = " ".join(str(note or "").split())
    with closing(connect()) as connection:
        with connection:
            connection.execute(
                "UPDATE evaluation_runs SET locked = 1, locked_at = ?, lock_note = ? WHERE rfp_run_id = ?",
                (now_text(), note, run_id),
            )
    add_audit(run_id, "LOCK_DECISION", note=note)
    return load_run(run_id)
