-- Forward-only authoritative memory schema. 001 telemetry is deliberately separate.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS flick;
CREATE TABLE flick.profiles (
    id text PRIMARY KEY CHECK (length(btrim(id)) > 0),
    display_name text NOT NULL CHECK (length(btrim(display_name)) > 0),
    biography text NOT NULL,
    embedding_backend text NOT NULL,
    embedding_model text NOT NULL,
    embedding_dim integer NOT NULL CHECK (embedding_dim = 384),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE flick.nodes (
    profile_id text NOT NULL REFERENCES flick.profiles(id),
    id text NOT NULL CHECK (length(btrim(id)) > 0),
    kind text NOT NULL CHECK (kind IN ('Person','Place','Thing','Activity','Need','Memory')),
    content text NOT NULL CHECK (length(btrim(content)) > 0),
    attributes jsonb NOT NULL CHECK (jsonb_typeof(attributes) = 'object'),
    embedding vector(384) NOT NULL CHECK (vector_norm(embedding) > 0),
    weight double precision NOT NULL DEFAULT 1 CHECK (weight > '-Infinity'::float8 AND weight < 'Infinity'::float8),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_accessed timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, id)
);
CREATE TABLE flick.edges (
    profile_id text NOT NULL REFERENCES flick.profiles(id),
    id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('KNOWS','LIKES','DISLIKES','NEEDS','LOCATED_AT','DOES','INVOLVES','RELATES_TO')),
    source text NOT NULL,
    target text NOT NULL,
    weight double precision NOT NULL DEFAULT 1 CHECK (weight > '-Infinity'::float8 AND weight < 'Infinity'::float8),
    count bigint NOT NULL DEFAULT 1 CHECK (count >= 0),
    strength double precision CHECK (strength >= 0 AND strength <= 1),
    last_reinforced timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, id),
    UNIQUE (profile_id, kind, source, target),
    FOREIGN KEY (profile_id, source) REFERENCES flick.nodes(profile_id, id),
    FOREIGN KEY (profile_id, target) REFERENCES flick.nodes(profile_id, id),
    CHECK ((kind IN ('LIKES','DISLIKES')) = (strength IS NOT NULL))
);
CREATE INDEX edges_source ON flick.edges(profile_id, source);
CREATE INDEX edges_target ON flick.edges(profile_id, target);
CREATE INDEX nodes_kind ON flick.nodes(profile_id, kind);
-- Exact profile-filtered cosine search is intentional at hackathon graph sizes.
-- Approximate global indexes can underfill results after profile filtering.
CREATE TABLE flick.conversation_turns (
    profile_id text NOT NULL REFERENCES flick.profiles(id),
    id text NOT NULL,
    partner_id text,
    partner_name text NOT NULL,
    user_name text NOT NULL,
    incoming_utterance text NOT NULL,
    chosen_intent text NOT NULL,
    selected_reply text NOT NULL,
    playback_outcome text NOT NULL CHECK (playback_outcome IN ('completed','failed','unconfirmed')),
    learning_outcome text NOT NULL CHECK (learning_outcome IN ('committed','extraction_failed','not_spoken')),
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, id),
    FOREIGN KEY (profile_id, partner_id) REFERENCES flick.nodes(profile_id, id)
);
CREATE INDEX turns_recent ON flick.conversation_turns(profile_id, partner_id, completed_at DESC, id DESC);
