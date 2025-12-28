-- =========================================================
-- Anchor v1 Schema (Supabase Postgres)
-- =========================================================

-- ---------- Extensions ----------
create extension if not exists pgcrypto;      -- gen_random_uuid()
create extension if not exists citext;        -- case-insensitive text for emails (optional)

-- Optional (enable later if you implement embeddings)
-- create extension if not exists vector;     -- pgvector

-- ---------- Enums ----------
do $$ begin
  create type user_tier as enum ('free', 'paid');
exception when duplicate_object then null; end $$;

do $$ begin
  create type session_status as enum ('active', 'ended');
exception when duplicate_object then null; end $$;

do $$ begin
  create type utterance_role as enum ('user', 'assistant');
exception when duplicate_object then null; end $$;

do $$ begin
  create type safety_stage as enum ('input', 'draft_output', 'final_output');
exception when duplicate_object then null; end $$;

do $$ begin
  create type safety_action as enum ('allow', 'block', 'fallback');
exception when duplicate_object then null; end $$;

do $$ begin
  create type audit_event_type as enum (
    'session_start',
    'session_end',
    'turn_received',
    'stt_complete',
    'scores_computed',
    'safety_input',
    'llm_draft',
    'safety_output',
    'tts_complete',
    'turn_complete',
    'error'
  );
exception when duplicate_object then null; end $$;

-- =========================================================
-- USERS / SETTINGS
-- =========================================================

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  -- If you later integrate Supabase Auth, you can map this to auth.users.id
  email citext unique,
  tier user_tier not null default 'free',
  created_at timestamptz not null default now()
);

create table if not exists user_settings (
  user_id uuid primary key references users(id) on delete cascade,

  -- Opt-in personalization toggles
  personalization_opt_in boolean not null default false,
  baseline_opt_in boolean not null default false,

  -- Optional: store UI preferences later
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_users_created_at on users(created_at);

-- =========================================================
-- SESSIONS / TURNS / UTTERANCES
-- =========================================================

create table if not exists sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,

  status session_status not null default 'active',

  -- Server-side gating (free 300 sec, paid 600+)
  max_duration_sec int not null check (max_duration_sec > 0),
  started_at timestamptz not null default now(),
  ended_at timestamptz,

  -- Aggregates computed at end (optional but handy)
  utterance_count int not null default 0,
  turn_count int not null default 0,

  -- You can snapshot model/policy at session start if you want
  policy_version text,
  model_version text,

  created_at timestamptz not null default now()
);

create index if not exists idx_sessions_user_id_started_at on sessions(user_id, started_at desc);
create index if not exists idx_sessions_status on sessions(status);

-- Each "turn" corresponds to one user recording submission (may include multiple 5s chunks)
create table if not exists turns (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,

  turn_index int not null,
  received_at timestamptz not null default now(),

  -- STT output (text only; do NOT store audio)
  transcript text,
  transcript_confidence float check (transcript_confidence is null or (transcript_confidence >= 0 and transcript_confidence <= 1)),

  -- Timing + enforcement
  elapsed_session_sec int check (elapsed_session_sec is null or elapsed_session_sec >= 0),
  remaining_session_sec int check (remaining_session_sec is null or remaining_session_sec >= 0),
  gated boolean not null default false,  -- true if blocked by time limit

  -- Debug + tracing
  request_id text,                       -- your server-generated id per request
  error_code text,
  error_message text,

  created_at timestamptz not null default now(),

  unique(session_id, turn_index)
);

create index if not exists idx_turns_session_id_turn_index on turns(session_id, turn_index);
create index if not exists idx_turns_request_id on turns(request_id);

-- Utterances are the canonical conversational timeline (user + assistant)
-- For user: chunked ~5 seconds
-- For assistant: one message per turn (or chunk if you choose)
create table if not exists utterances (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  turn_id uuid references turns(id) on delete set null,

  role utterance_role not null,
  seq int not null, -- global sequence within session timeline
  chunk_index int,  -- for user chunks inside a turn (0..N-1)

  text text not null,

  -- Scoring fields (as per your plan)
  valence float check (valence is null or (valence >= -1 and valence <= 1)),
  arousal float check (arousal is null or (arousal >= 0 and arousal <= 1)),
  confidence float check (confidence is null or (confidence >= 0 and confidence <= 1)),
  extremeness float check (extremeness is null or extremeness >= 0),

  -- Optional speech features (store when available)
  speech_rate_wpm float check (speech_rate_wpm is null or speech_rate_wpm >= 0),
  pause_ratio float check (pause_ratio is null or (pause_ratio >= 0 and pause_ratio <= 1)),

  created_at timestamptz not null default now(),

  unique(session_id, seq)
);

create index if not exists idx_utterances_session_seq on utterances(session_id, seq);
create index if not exists idx_utterances_session_turn on utterances(session_id, turn_id);

-- Assistant messages: store draft vs final + evidence
create table if not exists assistant_messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  turn_id uuid references turns(id) on delete set null,

  draft_text text,
  final_text text not null,

  fallback_used boolean not null default false,
  fallback_type text,

  -- Evidence must be present for any factual claims (curated sources)
  -- Store: { "sources": [...], "snippets": [...], "retrieved_at": "...", ... }
  evidence jsonb not null default '{}'::jsonb,

  policy_version text not null,
  model_version text not null,

  created_at timestamptz not null default now()
);

create index if not exists idx_assistant_messages_session_turn on assistant_messages(session_id, turn_id);

-- =========================================================
-- SAFETY + AUDITABILITY
-- =========================================================

-- Safety events for input / draft / final
create table if not exists safety_events (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  turn_id uuid references turns(id) on delete set null,

  stage safety_stage not null,
  action safety_action not null,

  category text,       -- your classifier label
  severity float check (severity is null or (severity >= 0 and severity <= 1)),

  -- Store full classifier payloads + rule hits:
  -- { "blocked": true/false, "labels": [...], "rule_hits": [...], ... }
  classification jsonb not null default '{}'::jsonb,

  fallback_used boolean not null default false,

  policy_version text not null,
  model_version text not null,

  created_at timestamptz not null default now()
);

create index if not exists idx_safety_events_session_turn_stage on safety_events(session_id, turn_id, stage);

-- General audit log for the full pipeline (timings, failures, etc.)
create table if not exists audit_logs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references sessions(id) on delete set null,
  turn_id uuid references turns(id) on delete set null,

  request_id text,
  event_type audit_event_type not null,

  -- Store durations, counters, internal flags, etc.
  -- Example: { "stt_ms": 430, "llm_ms": 900, "tts_ms": 500, "fallback_used": false, ... }
  data jsonb not null default '{}'::jsonb,

  policy_version text,
  model_version text,

  created_at timestamptz not null default now()
);

create index if not exists idx_audit_logs_session_created_at on audit_logs(session_id, created_at desc);
create index if not exists idx_audit_logs_request_id on audit_logs(request_id);

-- =========================================================
-- PERSONALIZATION BASELINES (opt-in)
-- =========================================================

create table if not exists user_baselines (
  user_id uuid primary key references users(id) on delete cascade,

  -- Rolling mean/variance for your fields
  valence_mean float,
  valence_var float,

  arousal_mean float,
  arousal_var float,

  speech_rate_mean float,
  speech_rate_var float,

  pause_ratio_mean float,
  pause_ratio_var float,

  updated_at timestamptz not null default now()
);

-- Optional: store per-session baseline deltas/spikes for analysis
create table if not exists baseline_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  session_id uuid references sessions(id) on delete set null,

  -- e.g. z-scores / spike flags
  data jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now()
);

create index if not exists idx_baseline_events_user_created_at on baseline_events(user_id, created_at desc);

-- =========================================================
-- CURATED SOURCES (facts only, RAG later)
-- =========================================================

-- List of approved sources (curated)
create table if not exists curated_sources (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  base_url text,
  description text,

  approved boolean not null default true,

  created_at timestamptz not null default now()
);

-- Documents fetched from curated sources
create table if not exists curated_documents (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references curated_sources(id) on delete cascade,

  url text not null,
  title text,
  retrieved_at timestamptz not null default now(),

  -- Raw cleaned text (no copyrighted large dumps; keep reasonable)
  text_content text not null,

  -- Metadata about cleaning/chunking
  meta jsonb not null default '{}'::jsonb,

  unique(source_id, url)
);

create index if not exists idx_curated_documents_source_retrieved on curated_documents(source_id, retrieved_at desc);

-- Chunked passages for retrieval
create table if not exists curated_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references curated_documents(id) on delete cascade,

  chunk_index int not null,
  content text not null,

  meta jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),

  unique(document_id, chunk_index)
);

create index if not exists idx_curated_chunks_document on curated_chunks(document_id, chunk_index);

-- Optional embeddings (enable pgvector extension first)
-- create table if not exists curated_chunk_embeddings (
--   chunk_id uuid primary key references curated_chunks(id) on delete cascade,
--   embedding vector(1536),  -- dimension depends on the model you use
--   created_at timestamptz not null default now()
-- );

-- =========================================================
-- SIMPLE TRIGGERS (updated_at convenience)
-- =========================================================

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_user_settings_updated_at on user_settings;
create trigger trg_user_settings_updated_at
before update on user_settings
for each row execute function set_updated_at();

-- =========================================================
-- DONE
-- =========================================================
