-- Educational assessment AI agent platform.
CREATE EXTENSION IF NOT EXISTS vector;

-- Learning standards (descriptions paraphrased) and reading passages: the RAG knowledge base.
CREATE TABLE IF NOT EXISTS standards (
    code        TEXT PRIMARY KEY,               -- e.g. CCSS.MATH.6.RP.A.3
    subject     TEXT NOT NULL,                  -- MATH | ELA | CS
    grade       INT  NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id            BIGSERIAL PRIMARY KEY,
    source_type   TEXT NOT NULL,                -- STANDARD | PASSAGE
    source_id     TEXT NOT NULL,
    content       TEXT NOT NULL,
    embedding     vector(1024),
    embed_model   TEXT,                         -- vectors from different models are never compared
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    UNIQUE (source_type, source_id)
);
CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON knowledge_chunks USING gin (tsv);

-- Assessment items. Drafts from the authoring agent need teacher approval before students see them.
CREATE TABLE IF NOT EXISTS items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    standard_code   TEXT NOT NULL REFERENCES standards (code),
    item_type       TEXT NOT NULL CHECK (item_type IN ('MULTIPLE_CHOICE', 'CONSTRUCTED_RESPONSE', 'CODE')),
    difficulty      TEXT NOT NULL CHECK (difficulty IN ('EASY', 'MEDIUM', 'HARD')),
    stem            TEXT NOT NULL,
    choices         JSONB,                       -- multiple choice: ["...", "..."]
    answer_key      TEXT NOT NULL,               -- correct choice letter, exemplar answer, or reference solution
    rubric          JSONB NOT NULL,              -- [{"criterion": "...", "max_points": 2, "descriptors": "..."}]
    tests           JSONB,                       -- code items: [{"args": [...], "expected": ...}]
    status          TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'APPROVED', 'REJECTED')),
    source          TEXT NOT NULL,               -- SEED | AUTHORING_AGENT
    review_notes    JSONB,                       -- the agent's self-review and the teacher's decision
    embedding       vector(1024),
    embed_model     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS students (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    grade INT  NOT NULL
);

-- Student responses and their scores (AI and, when needed, human).
CREATE TABLE IF NOT EXISTS responses (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id         TEXT NOT NULL REFERENCES students (id),
    item_id            UUID NOT NULL REFERENCES items (id),
    response_text      TEXT NOT NULL,           -- stored after PII redaction
    ai_score           NUMERIC(5, 2),
    max_score          NUMERIC(5, 2),
    ai_confidence      NUMERIC(4, 3),
    ai_result          JSONB,                    -- per-criterion points, evidence, rationale, provider
    safety             JSONB,                    -- flags from the safety layer
    needs_human_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reasons     JSONB NOT NULL DEFAULT '[]',
    human_score        NUMERIC(5, 2),
    human_note         TEXT,
    reviewed_by        TEXT,
    status             TEXT NOT NULL DEFAULT 'SCORING' CHECK (status IN ('SCORING', 'SCORED', 'NEEDS_REVIEW', 'REVIEWED', 'ERROR')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_responses_review ON responses (needs_human_review, status);

-- Persistent tutor memory per student (misconceptions, strengths, preferences), searchable by meaning.
CREATE TABLE IF NOT EXISTS student_memory (
    id          BIGSERIAL PRIMARY KEY,
    student_id  TEXT NOT NULL REFERENCES students (id),
    kind        TEXT NOT NULL CHECK (kind IN ('MISCONCEPTION', 'STRENGTH', 'PREFERENCE', 'NOTE')),
    content     TEXT NOT NULL,
    item_id     UUID,
    embedding   vector(1024),
    embed_model TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Shared state for one student working on one item: written by the tutor and the scoring agent.
CREATE TABLE IF NOT EXISTS learning_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id  TEXT NOT NULL REFERENCES students (id),
    item_id     UUID NOT NULL REFERENCES items (id),
    state       JSONB NOT NULL DEFAULT '{"hint_level": 0, "attempts": 0, "misconceptions": []}',
    transcript  JSONB NOT NULL DEFAULT '[]',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (student_id, item_id)
);

-- Agent runs (multi-step workflows), shown live in the UI.
CREATE TABLE IF NOT EXISTS agent_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    input       JSONB NOT NULL,
    steps       JSONB NOT NULL DEFAULT '[]',
    output      JSONB,
    error       TEXT,
    trace_id    TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

-- Observability: every model and embedding call.
CREATE TABLE IF NOT EXISTS llm_calls (
    id             BIGSERIAL PRIMARY KEY,
    trace_id       TEXT,
    role           TEXT NOT NULL,                -- safety | tutor | scoring | authoring | judge | embedding
    provider       TEXT NOT NULL,                -- bedrock | anthropic | voyage
    model          TEXT NOT NULL,
    ok             BOOLEAN NOT NULL,
    error          TEXT,
    latency_ms     INT NOT NULL,
    input_tokens   INT,
    output_tokens  INT,
    cost_usd       NUMERIC(10, 6),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_llm_calls_created ON llm_calls (created_at DESC);

CREATE TABLE IF NOT EXISTS safety_events (
    id          BIGSERIAL PRIMARY KEY,
    trace_id    TEXT,
    student_id  TEXT,
    surface     TEXT NOT NULL,                  -- SCORING | TUTOR_INPUT | TUTOR_OUTPUT
    category    TEXT NOT NULL,                  -- PROMPT_INJECTION | PII | SELF_HARM | HARASSMENT | ANSWER_LEAK | ...
    action      TEXT NOT NULL,                  -- REDACTED | BLOCKED | FLAGGED | ESCALATED
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    suite       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'RUNNING',
    metrics     JSONB,
    cases       JSONB,
    error       TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
