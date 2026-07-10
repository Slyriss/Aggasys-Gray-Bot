-- Extensions (must come first)
CREATE EXTENSION IF NOT EXISTS vector;

-- Conversation memory: stores last N messages per user
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Long-term memory: personal facts about specific users
CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    fact TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Company wiki: LLM-maintained structured knowledge pages
CREATE TABLE IF NOT EXISTS wiki_pages (
    id SERIAL PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT[] DEFAULT '{}',
    embedding vector(768),
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', title || ' ' || content)
    ) STORED,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Company-wide atomic facts mined from conversations (shared across users)
CREATE TABLE IF NOT EXISTS company_memory (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'general',
    fact TEXT NOT NULL,
    source_user_id BIGINT,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Rolling conversation summaries (one per user, updated when history gets long)
CREATE TABLE IF NOT EXISTS conversation_summaries (
    telegram_user_id BIGINT PRIMARY KEY,
    summary TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Action items and reminders
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',   -- open | done
    due_text TEXT,                          -- natural language: "Monday", "end of week"
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Quick-capture notes per user
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Hermes operations audit log
CREATE TABLE IF NOT EXISTS hermes_audit_log (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT,
    chat_id BIGINT,
    action_name TEXT NOT NULL,
    risk TEXT NOT NULL,
    decision TEXT NOT NULL,
    status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Hermes approval requests for actions that need human confirmation
CREATE TABLE IF NOT EXISTS hermes_approval_requests (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT,
    chat_id BIGINT NOT NULL,
    action_name TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    prompt TEXT NOT NULL,
    reason TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    resolved_by BIGINT,
    resolved_at TIMESTAMP,
    resolution_note TEXT
);

-- Hermes scheduled jobs. Initial provider is in-process; schema keeps room for
-- future external scheduler handoff on Hostinger.
CREATE TABLE IF NOT EXISTS hermes_jobs (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    created_by BIGINT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    schedule_kind TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    next_run_at TIMESTAMP NOT NULL,
    last_run_at TIMESTAMP,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    locked_at TIMESTAMP,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Hermes standup workflow state
CREATE TABLE IF NOT EXISTS standup_sessions (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    created_by BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    participants TEXT[] NOT NULL DEFAULT '{}',
    updates JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_created_at ON conversations(telegram_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_wiki_search ON wiki_pages USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_wiki_path ON wiki_pages(path);
CREATE INDEX IF NOT EXISTS idx_wiki_embedding ON wiki_pages USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_company_memory_embedding ON company_memory USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_company_memory_search ON company_memory USING gin(to_tsvector('english', fact));
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(telegram_user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(telegram_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_embedding ON notes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_notes_search ON notes USING gin(to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS idx_hermes_audit_chat_created_at ON hermes_audit_log(chat_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_approvals_chat_status ON hermes_approval_requests(chat_id, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_approvals_expiry ON hermes_approval_requests(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_hermes_jobs_due ON hermes_jobs(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_hermes_jobs_chat ON hermes_jobs(chat_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_standup_sessions_chat_status ON standup_sessions(chat_id, status, created_at DESC);
