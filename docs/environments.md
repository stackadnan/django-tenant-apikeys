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

By default the package doesn't branch on `environment` except when building
the key's prefix (below) — it's plain data for your application to read. To
have the library *enforce* it, say which environments this deployment
serves:

```python
# settings.py (production)
TENANT_API_KEY_ALLOWED_ENVIRONMENTS = ["production"]
```

A key from any other environment is then refused during authentication
(403), so a test or staging key can't be used against production even by
accident. Unset (the default) means no enforcement; an empty list refuses
everything.

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
out to decide anything — enforcement and every other check use the
`environment` column, never the prefix string. If your application code
needs to know a key's environment, read `instance.environment`.

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
