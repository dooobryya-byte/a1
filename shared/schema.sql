-- Чаты
CREATE TABLE IF NOT EXISTS chats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL UNIQUE,
    chat_id         TEXT,
    name            TEXT NOT NULL,
    city            TEXT,
    gender          TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);

-- Сообщения
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mid             TEXT UNIQUE,
    chat_pk         INTEGER NOT NULL,
    user_id         TEXT NOT NULL,
    direction       TEXT NOT NULL,        -- 'in' | 'out'
    sender_id       TEXT,
    sender_name     TEXT,
    is_bot          INTEGER DEFAULT 0,
    author          TEXT,                 -- 'user' | 'bot' | 'admin'
    text            TEXT,
    type_id         INTEGER,
    status          TEXT DEFAULT 'sent',
    reply_to_mid    TEXT,
    created_at      TEXT NOT NULL,
    timestamp_ms    INTEGER,
    edited_at       TEXT,
    deleted_at      TEXT,
    raw_json        TEXT,
    FOREIGN KEY (chat_pk) REFERENCES chats(id)
);

CREATE INDEX IF NOT EXISTS idx_msg_chat_pk ON messages(chat_pk, id);
CREATE INDEX IF NOT EXISTS idx_msg_mid ON messages(mid);
CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_msg_type ON messages(type_id);

-- Связки
CREATE TABLE IF NOT EXISTS relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_pk         INTEGER NOT NULL,
    id_message_for  TEXT NOT NULL,
    id_message_back TEXT NOT NULL,
    rel_type        TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (chat_pk) REFERENCES chats(id)
);

-- Аудит
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    action          TEXT NOT NULL,
    chat_pk         INTEGER,
    mid             TEXT,
    details         TEXT
);