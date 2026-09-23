# Flightkit

FastAPI backend.

## Stack

See [TOOLS.txt](./TOOLS.txt) for the full list of tools/libraries used and why.

## Local development

```bash
uv sync
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Then check:
- http://127.0.0.1:8000/docs — interactive API docs
- http://127.0.0.1:8000/health — liveness check
- http://127.0.0.1:8000/ready — readiness check (verifies DB connectivity)

Copy `.env.example` to `.env` and fill in real values before running.

## Full stack via Docker

```bash
docker compose up -d --build
```

Also brings up Postgres, Prometheus (`:9090`), and Grafana (`:3001`).

## Tests

```bash
uv run pytest -v
```

## Migrations

Migrations are **not** run automatically on app startup — with multiple replicas,
concurrent containers racing to migrate the schema on boot is a real failure mode.

Run them as a separate, one-off step before deploying a new version:

```bash
uv run alembic upgrade head
```

In a deploy pipeline, this should run once (e.g. as a pre-deploy job/one-off task),
complete successfully, and only then should the new app version start receiving traffic.

## Code quality

```bash
uv run ruff check .
uv run ruff format .
uv run pip-audit
```

Pre-commit hooks run these automatically on `git commit` — see `.pre-commit-config.yaml`.
Install once per clone: `uv run pre-commit install`.
