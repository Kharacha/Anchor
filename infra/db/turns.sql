-- turns.sql

-- Turn: one user->assistant exchange
create table if not exists turns (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  created_at timestamptz not null default now()
);

-- Utterance: the user input (text for now; later audio chunks)
create table if not exists utterances (
  id uuid primary key default gen_random_uuid(),
  turn_id uuid not null references turns(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  chunk_index int not null default 0,
  created_at timestamptz not null default now()
);

-- Safety event: store input/output classification per turn
create table if not exists safety_events (
  id uuid primary key default gen_random_uuid(),
  turn_id uuid not null references turns(id) on delete cascade,
  stage text not null check (stage in ('input','output')),
  classification jsonb not null,
  fallback_used boolean not null default false,
  policy_version text not null,
  model_version text not null,
  created_at timestamptz not null default now()
);

-- Assistant message: assistant output (separate from utterances for auditability)
create table if not exists assistant_messages (
  id uuid primary key default gen_random_uuid(),
  turn_id uuid not null references turns(id) on delete cascade,
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_turns_session_id on turns(session_id);
create index if not exists idx_utterances_turn_id on utterances(turn_id);
create index if not exists idx_safety_events_turn_id on safety_events(turn_id);
create index if not exists idx_assistant_messages_turn_id on assistant_messages(turn_id);
