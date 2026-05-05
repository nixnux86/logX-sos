import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "sosinsight.db"

schema = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT UNIQUE,
    filename TEXT,
    extracted_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_opened_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    section TEXT,
    key TEXT,
    value TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    module TEXT,
    severity TEXT,
    title TEXT,
    detail TEXT,
    recommendation TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    log_time TEXT,
    hostname TEXT,
    process TEXT,
    severity TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS dmesg_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    severity TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS sar_cpu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    sample_time TEXT,
    user_pct REAL,
    system_pct REAL,
    iowait_pct REAL,
    idle_pct REAL
);
CREATE TABLE IF NOT EXISTS sar_mem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    sample_time TEXT,
    mem_used_pct REAL,
    swap_used_pct REAL
);
CREATE TABLE IF NOT EXISTS sar_disk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    sample_time TEXT,
    device TEXT,
    read_kbps REAL,
    write_kbps REAL,
    util_pct REAL
);
CREATE TABLE IF NOT EXISTS sar_net (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    sample_time TEXT,
    interface TEXT,
    rx_kbps REAL,
    tx_kbps REAL,
    rxpck_s REAL,
    txpck_s REAL
);
CREATE TABLE IF NOT EXISTS sar_load (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    sample_time TEXT,
    runq_sz REAL,
    plist_sz REAL,
    ldavg1 REAL,
    ldavg5 REAL,
    ldavg15 REAL
);
"""

if __name__ == "__main__":
    with sqlite3.connect(DB) as conn:
        conn.executescript(schema)
    print(f"Database initialized: {DB}")
