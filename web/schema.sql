CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    freq TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDENTE',
    total INTEGER DEFAULT 0,
    completed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    started_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    client_name TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL,
    error_detail TEXT,
    presentation_url TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
