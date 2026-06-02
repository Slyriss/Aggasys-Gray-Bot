-- Conversation memory: stores last N messages per user
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Long term memory: important facts the bot remembers about users
CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    fact TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory(telegram_user_id);

-- Company wiki: LLM-maintained knowledge pages (Karpathy wiki pattern)
CREATE TABLE IF NOT EXISTS wiki_pages (
    id SERIAL PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,       -- e.g. 'clients/temasek', 'procedures/escalation'
    title TEXT NOT NULL,
    content TEXT NOT NULL,           -- full markdown
    sources TEXT[] DEFAULT '{}',     -- source filenames or record IDs this was built from
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', title || ' ' || content)
    ) STORED,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wiki_search ON wiki_pages USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_wiki_path ON wiki_pages(path);
