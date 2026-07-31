-- JATAYU OS — Layer 1 Memory Schema
-- Replaces the split memory.json + entities.json with one SQLite store.
-- Design goals:
--   - unified (facts + entities in one DB, no split lookup paths)
--   - lightning-fast retrieval (FTS5 keyword index + covering indices)
--   - scalable to thousands of facts without a rewrite
--   - protected facts (identity/preference) always injectable in O(1)

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- FACTS: flat semantic facts (identity, preferences, knowledge)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS facts (
    id            TEXT PRIMARY KEY,
    fact          TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'general',
        -- 'identity' | 'preference' | 'project' | 'person' | 'knowledge' | 'contract'
    protected     INTEGER NOT NULL DEFAULT 0,
        -- 1 = always injected into every prompt, regardless of query relevance
    importance    REAL NOT NULL DEFAULT 0.5,   -- 0.0–1.0
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    access_count  INTEGER NOT NULL DEFAULT 0,
    last_accessed TEXT
);

CREATE INDEX IF NOT EXISTS idx_facts_category  ON facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_protected ON facts(protected);

-- FTS5 index kept in sync with facts via triggers (external-content table:
-- zero data duplication, index lives alongside the row).
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    fact,
    content = 'facts',
    content_rowid = 'rowid'
);

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, fact) VALUES (new.rowid, new.fact);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, fact) VALUES ('delete', old.rowid, old.fact);
END;

CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, fact) VALUES ('delete', old.rowid, old.fact);
    INSERT INTO facts_fts(rowid, fact) VALUES (new.rowid, new.fact);
END;

-- ─────────────────────────────────────────────────────────────
-- ENTITIES: people + projects, structured, with real dedup key
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,          -- 'person' | 'project'
    name       TEXT NOT NULL,
    name_lower TEXT NOT NULL,          -- dedup key (lowercased name)
    json_blob  TEXT NOT NULL,          -- structured fields (role, email, contract, etc.)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_dedup ON entities(type, name_lower);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

-- ─────────────────────────────────────────────────────────────
-- NOTES: verbatim save/recall — separate from `facts` on purpose.
-- `facts` get surfaced to the LLM as context for it to reason/write about;
-- `notes` are for when the exact original text must come back unchanged
-- (e.g. "repeat exactly what I told you"). One row per label — saving to
-- the same label again replaces the previous content (last one wins).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notes (
    label      TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias      TEXT NOT NULL,
    alias_lower TEXT NOT NULL,
    PRIMARY KEY (entity_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_alias_lower ON entity_aliases(alias_lower);

-- Relevance search over entities (name + aliases + description/role text),
-- so prompt injection can include FULL details only for entities relevant
-- to the current message, instead of dumping every person/project into
-- every request. Maintained manually by MemoryStore.remember_entity()
-- (composite blob, not a single source column, so no content= trigger).
CREATE VIRTUAL TABLE IF NOT EXISTS entities_search_fts USING fts5(
    entity_id UNINDEXED,
    type UNINDEXED,
    blob
);
