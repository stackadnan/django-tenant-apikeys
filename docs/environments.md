# Environments

Every key has an `environment`: `"production"` (the default), `"staging"`,
`"development"`, or `"test"`.

```python
from django_tenant_apikeys.models import Environment

instance, raw_key = OrganizationAPIKey.generate_key(
    name="Staging smoke tests",
    tenant=org,
    environment=Environment.TEST,
)
raw_key               # tak_test_3f9a2c1d.Xk7p...
instance.environment   # "test"
```

`Environment` is a `TextChoices` class — `Environment.PRODUCTION`,
`Environment.STAGING`, `Environment.DEVELOPMENT`, `Environment.TEST` — or
just pass the plain string (`"test"`) directly; both work identically since
`TextChoices` members compare equal to their string values.

## What it's for

If your test suite, staging environment, and local development all talk to
the same Django project (a shared staging database, say), `environment`
lets you tell those keys apart without inventing your own field for it, and
lets you write code like:

```python
if api_key.environment != Environment.PRODUCTION:
    # e.g. skip a billing side-effect, log more verbosely, whatever your
    # application actually needs to do differently
    ...
```

The package itself doesn't branch on `environment` anywhere except when
building the key's prefix (below) — it's plain data for your application to
read, the same as [metadata](metadata.md), just with a fixed, validated set
of allowed values instead of arbitrary JSON.

## The prefix segment is a visual cue, not the source of truth

`generate_key()` encodes a coarser signal into the prefix itself:

| `environment`           | Prefix segment |
|--------------------------|:--------------:|
| `production` (default)  | `_live_`       |
| `staging`                | `_live_`       |
| `development`            | `_test_`       |
| `test`                   | `_test_`       |

```python
OrganizationAPIKey.generate_key(name="k", tenant=org)
# prefix: tak_live_...  (environment defaults to "production")

OrganizationAPIKey.generate_key(name="k", tenant=org, environment=Environment.DEVELOPMENT)
# prefix: tak_test_...
```

This only has two buckets, not four — `production`/`staging` both get
`_live_`, `development`/`test` both get `_test_` — the same coarse
live-vs-test split Stripe and GitHub use in their own key prefixes. It's
enough to eyeball a key's blast radius in a log line or an error report at
a glance.

**It is not authoritative.** Nothing in the package parses the prefix back
out to decide anything — `is_active`, `is_expired`, scope checks, IP
restrictions, and rate limiting are all identical regardless of which
segment a key's prefix has. If your application code needs to know a key's
environment, read `instance.environment`, never the prefix string.

## Backward compatibility

Every key created before this field existed has no `environment` column to
read. On upgrade, the field defaults to `"production"` — the same access
level those keys have always had, just now named explicitly. No migration
data backfill is required beyond Django's own `AddField` default handling.

## Next

- [Metadata](metadata.md) — arbitrary, unvalidated JSON, for anything
  `environment`'s fixed set of choices doesn't cover.
- [Authentication](authentication.md) — how the prefix is used during
  lookup (hint: only the part before the dot, and only for indexing).
