-- Run this on an EXISTING installation to upgrade to the 2nd Brain schema.
-- Safe to run multiple times (all statements are idempotent).

CREATE EXTENSION IF NOT EXISTS vector;

-- Add vector embedding column to wiki_pages
ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS embedding vector(768);

-- Drop old IVFFlat index if it exists, create HNSW instead
DROP INDEX IF EXISTS idx_wiki_embedding;
CREATE INDEX IF NOT EXISTS idx_wiki_embedding ON wiki_pages USING hnsw (embedding vector_cosine_ops);

-- Company-wide atomic facts
CREATE TABLE IF NOT EXISTS company_memory (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'general',
    fact TEXT NOT NULL,
    source_user_id BIGINT,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_company_memory_embedding ON company_memory USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_company_memory_search ON company_memory USING gin(to_tsvector('english', fact));

-- Rolling conversation summaries
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
    status TEXT NOT NULL DEFAULT 'open',
    due_text TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(telegram_user_id, status, created_at DESC);

-- Quick-capture notes
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(telegram_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_embedding ON notes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_notes_search ON notes USING gin(to_tsvector('english', content));

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
CREATE INDEX IF NOT EXISTS idx_hermes_audit_chat_created_at ON hermes_audit_log(chat_id, created_at DESC);

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
ALTER TABLE hermes_approval_requests ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '24 hours');
CREATE INDEX IF NOT EXISTS idx_hermes_approvals_chat_status ON hermes_approval_requests(chat_id, status, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_approvals_expiry ON hermes_approval_requests(status, expires_at);

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
CREATE INDEX IF NOT EXISTS idx_hermes_jobs_due ON hermes_jobs(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_hermes_jobs_chat ON hermes_jobs(chat_id, status, created_at DESC);

ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP;
ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE hermes_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

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
CREATE INDEX IF NOT EXISTS idx_standup_sessions_chat_status ON standup_sessions(chat_id, status, created_at DESC);
