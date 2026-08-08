CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    run_id TEXT,
    action TEXT,
    message_ids TEXT,
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id TEXT PRIMARY KEY,
    account_id TEXT,
    thread_id TEXT,
    summary TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS sender_rules (
    account_id TEXT,
    sender TEXT,
    category TEXT,
    auto_delete INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (account_id, sender)
);

CREATE TABLE IF NOT EXISTS vip_senders (
    account_id TEXT,
    sender TEXT,
    PRIMARY KEY (account_id, sender)
);

CREATE TABLE IF NOT EXISTS sync_state (
    account_id TEXT PRIMARY KEY,
    last_sort_at TEXT
);
