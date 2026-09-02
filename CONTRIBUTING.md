# Contributing

Issues and pull requests are welcome. This is a small, single-maintainer
package, so keep changes focused — a PR that does one thing is much easier
to review than one that also reformats unrelated code.

## Setup

```bash
git clone https://github.com/stackadnan/django-tenant-apikeys
cd django-tenant-apikeys
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"
```

The `dev` extra pulls in everything needed to run and check the project:
`pytest`, `pytest-django`, `pytest-cov`, `djangorestframework`,
`django-ninja`, `mypy`, `django-stubs`, `djangorestframework-stubs`, and
`ruff`. It does *not* include `psycopg` -- install `psycopg[binary]`
yourself if you want to run the suite against PostgreSQL locally (see
[Running the tests](README.md#running-the-tests) in the main README).

## Running the checks

These are the exact three commands CI runs on every push and PR — run them
locally before opening one, so you see the same result CI will:

```bash
pytest --cov=django_tenant_apikeys --cov-report=term-missing
ruff check .
mypy django_tenant_apikeys
```

A few things worth knowing:

- **Coverage is enforced at 100%** (`fail_under = 100` in `pyproject.toml`).
  If you add a branch, add a test that exercises it — there's no partial
  credit here, and no line is excluded without a `# pragma: no cover` and a
  reason.
- **`mypy` runs in strict mode.** Public functions and methods need real
  type hints, not `Any`. If you hit a genuine third-party stub limitation
  (see the `# type: ignore[no-any-return]` in `models.py` for an example),
  explain why in a comment rather than silently suppressing it.
- Tests live in `tests/`, run against an in-memory SQLite database
  (`tests/settings.py`), using the concrete `TenantAPIKey` / `Tenant` /
  `UnlinkedAPIKey` models defined in `tests/models.py` — `AbstractTenantAPIKey`
  itself can't be instantiated or queried directly.

## Making a change

1. Fork the repo and create a branch off `main`.
2. Write the change. If it alters behaviour (not just docs/comments), add or
   update a test for it — untested behaviour changes won't be merged.
3. Run the three commands above.
4. Open a PR describing *why*, not just *what*. Link an issue if there is
   one.

## Code style

- Type hints on public functions and methods (`from __future__ import
  annotations`, `X | None` unions, lowercase `tuple`/`type` generics — see
  any existing module for the pattern).
- Docstrings explain *why* something is the way it is when it's non-obvious
  (see `hash_key()`'s note on why the hash is unsalted); they don't restate
  what the code already says.
- `ruff` (line length 100, rule set in `pyproject.toml`) handles formatting
  and import order — let it, rather than hand-formatting.

## Reporting bugs

Open a GitHub issue with a minimal reproduction. For anything
security-related, see [SECURITY.md](SECURITY.md) instead — please don't file
those as public issues.

## What's out of scope

Before proposing a new feature, check the
[FAQ](README.md#faq) and the
[SECURITY.md scope section](SECURITY.md#scope) — a few things (rate
limiting, multi-tenant keys, async views) are deliberately left to the
consuming project rather than built in. If you think one of those should
change, open an issue to discuss it before sending a PR.
