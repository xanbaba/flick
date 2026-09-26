# Flick

A semantic brain-computer interface for assistive communication. See
`ARCHITECTURE.md` for the full specification.

## Install

```bash
uv sync
cp .env.example .env
cd frontend && npm install && cd ..
```

## Run

```bash
./run.sh
```

Or run each process individually:

```bash
uv run python -m sensor.main
uv run python -m stimulus.main
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```

To develop with no hardware at all, set `input.adapter: keyboard` and
`mode.source: synthetic` in `config.yaml`.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```
