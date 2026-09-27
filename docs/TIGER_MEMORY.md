# Tiger memory

The application uses `TIGER_DSN` from the ignored `.env` for profiles, graph nodes,
relationships, 384-dimensional pgvector embeddings and conversation turns.
`LOCAL_PG_DSN` selects explicit local development **only when TIGER_DSN is absent**.
There is no Kuzu or local-Postgres failover after a Tiger connection failure.
`TIMESCALE_DSN` remains legacy telemetry configuration; it does not select memory.

Start the backend normally after setting the DSN. Startup applies forward migration
`002_memory.sql` under a transaction/advisory lock, recording its checksum. The
database role needs permission to create the `vector` extension, `flick` schema
and its tables. TimescaleDB must be available on the Tiger destination. Existing
`001_timescale.sql` telemetry tables are neither changed nor required.

Storage availability and destination are shown in the status bar. A missing or
unreachable DSN produces `MEMORY_UNAVAILABLE` and 503 graph/onboarding responses.
Configure/fix the DSN and restart; unavailable memory never becomes a fake empty
persona. Ordinary transient read failures end the current turn cleanly.

## Existing Kuzu profile

Stop the old backend before importing. Choose a fresh backup filename. The
importer reads Kuzu without modifying it, keeps a rollback copy, re-embeds facts
in one recorded space, and compares IDs, facts, attributes, weights, counts and
strengths inside the PostgreSQL transaction. Invalid imports roll back. An
existing target profile is rejected, never overwritten.

```powershell
uv run python -m scripts.import_kuzu_memory --source ./data/kuzu --backup ./data/memory-migration/kuzu-before-tiger --profile-id user
```

If the actual legacy database is elsewhere, supply its path. Optional
`--biography ./path/to/biography.txt` preserves the original biography text;
without it, the imported facts are retained and biography is blank, not invented.
The tool defaults to bounds of 5,000 nodes and 20,000 edges. Use explicit
`--max-nodes` / `--max-edges` for a larger reviewed import. `--local` explicitly
selects `LOCAL_PG_DSN` for development. Keep all backups private and uncommitted.

## Conversation and learning

Both generation rounds receive graph facts, current input and a separate
speaker-labelled recent conversation. Retrieval puts the current question and
newest antecedents first so a short embedding model does not truncate them away.
History is partitioned by profile and partner, limited to the newest six exchanges
and 12,000 rendered characters. Oversized exchanges are omitted whole, preserving
speaker identity. Counts/bounds are configurable in `config.yaml`.

Learning requires a supporting quote from the current speaker. Partner quotes
remain attributed to the partner; questions and unselected candidates do not
become user facts. Deduplication searches the proposed node kind and preserves
speaker attribution. Provider/embedding work finishes before SQL writes.

Confirmed graph changes, reinforcement and the turn record commit atomically.
Stable turn IDs prevent repeated increments. Extraction-provider failure records
an honest exchange with `learning_outcome=extraction_failed` and discloses that
failure. Failed/unconfirmed playback is recorded without a spoken user statement
or graph learning. If database commit is uncertain, writes remain blocked until
canonical state is reconciled under the profile's write lock. There is no outbox
or offline acceptance.

Profiles record the actual embedding backend/model/dimension. Cached CPU MiniLM
is preferred; otherwise deterministic SHA-256 token embeddings are recorded.
A different embedding space at restart is rejected, never silently mixed. Reuse
the original space or explicitly import into a new profile with consistent
re-embedding. Hash embeddings exercise retrieval but do not have MiniLM's semantic
quality.

## Verification

Offline unit/regression tests:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Real database acceptance (separate from network-free pytest):

```powershell
uv run python -m scripts.check_memory --env-file .env --tiger
```

For an explicit local PostgreSQL/pgvector DSN file, omit `--tiger`. The check uses
uniquely named test profiles and removes those profiles afterward. It exercises
onboarding, both retrieval/generation rounds, learning attribution, rollback,
write deadlines/reconciliation, duplicate-turn protection, profile separation,
read-only Kuzu import, playback outcomes and restart recovery. It also drives the
real app lifespan, HTTP routes and WebSocket choices/playback across an application
restart. LLM and audio providers are **labelled scripted acceptance fixtures**;
these checks do not claim live model quality or headset success. Rehearse the
vacation follow-up with the configured live generation provider before the demo.

Verification on 2026-09-27: the real local PostgreSQL/pgvector check passed,
including the full application restart flow and Kuzu import comparison. The
configured Tiger endpoint resolved and accepted TCP connections, but did not
answer PostgreSQL's initial SSL negotiation. Both asyncpg and containerized psql
timed out. Cloud migration and acceptance therefore remain unverified until the
service/network issue is resolved; local success is not a Tiger Cloud result.
