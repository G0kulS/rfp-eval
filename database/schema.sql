CREATE TABLE IF NOT EXISTS criteria (
    criterion_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL CHECK (weight >= 0 AND weight <= 100),
    max_score REAL NOT NULL CHECK (max_score > 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    rfp_run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    model TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    notes_json TEXT NOT NULL DEFAULT '[]',
    locked INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1)),
    locked_at TEXT,
    lock_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS supplier_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfp_run_id TEXT NOT NULL REFERENCES evaluation_runs (rfp_run_id) ON DELETE CASCADE,
    supplier_name TEXT NOT NULL,
    submission_date TEXT NOT NULL,
    experience_rating REAL NOT NULL,
    file_name TEXT NOT NULL DEFAULT '',
    absolute_score REAL NOT NULL,
    ppi REAL NOT NULL,
    final_rank INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    UNIQUE (rfp_run_id, supplier_name)
);

CREATE INDEX IF NOT EXISTS supplier_scores_by_run ON supplier_scores (rfp_run_id, final_rank);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfp_run_id TEXT NOT NULL REFERENCES evaluation_runs (rfp_run_id) ON DELETE CASCADE,
    happened_at TEXT NOT NULL,
    action TEXT NOT NULL,
    supplier_name TEXT,
    criterion_id INTEGER,
    old_value REAL,
    new_value REAL,
    note TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS audit_log_by_run ON audit_log (rfp_run_id, id);
