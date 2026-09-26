# Django API key authentication

This page covers how a key is generated, stored, and verified — the
mechanics behind every `generate_key()` call and every authenticated
request. If you just want the integration code, see
[Django REST Framework](django-rest-framework.md) or
[Django Ninja](django-ninja.md).

## How a key is shaped

```
tak_live_3f9a2c1d.Xk7pQ2m1vYzN0hT8sR4uWjLdEaFbGcHiJk
└──┬──┘ └───┬────┘ └────────────────┬────────────────┘
 prefix  secret_prefix              secret
└──────────┬──────────┘
   stored in `prefix` column (indexed, unique, cleartext)
```

`generate_api_key(prefix="tak")` builds this and returns `(full_key,
key_prefix, hashed_key)`. This is the same prefix + hashed-secret shape
Stripe and GitHub use for their own API keys, for the same reason:

- **`prefix`** (everything before the dot) is stored in cleartext, indexed,
  and unique. It carries no real entropy — its only job is letting a lookup
  hit one indexed row instead of hashing every key in the table on every
  request. It's safe to log, safe to show in the admin list view, safe to
  put in an error message.
- **`secret`** (everything after the dot) is the actual credential. It's
  generated with `secrets.token_urlsafe()` (256 bits) and never written down
  anywhere except as `sha256(full_key)`, in the `hashed_key` column. The
  only place the full, usable key ever exists is the return value of
  `generate_api_key()` / `generate_key()` — not the database, not logs, not
  the admin, ever again.

The `_live_`/`_test_` segment in the middle reflects the key's
[environment](environments.md) — it's a visual cue, not something anything
in the package parses back out to make a decision.

## Why the hash is unsalted SHA-256

This is a deliberate choice, not an oversight, and it's worth understanding
before you assume it's wrong. Password hashing algorithms (bcrypt, PBKDF2,
argon2) exist to slow down brute-forcing a **low-entropy** secret — a
human-chosen password drawn from a small effective keyspace. They're
deliberately slow, and salted so identical passwords don't produce identical
hashes.

The secret half of an API key here is 256 bits of output from
`secrets.token_urlsafe()` — nothing like a password. There's no dictionary
to run against it, no rainbow table that helps, and no two keys will ever
collide. Salting a value that's already this random buys nothing, and a
slow, deliberately-expensive hash would only add real cost to every
authenticated request without adding real protection. A single unsalted
SHA-256 pass (`hash_key()`) is both correct here and keeps verification
cheap at scale.

## Verifying a key

```python
api_key.verify_key(raw_key)  # bool
```

Internally: `secrets.compare_digest(self.hashed_key, hash_key(raw_key))`.
`compare_digest` runs in constant time regardless of where the two strings
first differ — a plain `==` comparison returns as soon as it hits a
mismatched byte, which leaks timing information an attacker could use to
guess a hash one byte at a time. This matters even though the hash itself
isn't secret (only the raw key is) — it protects the "does this hash match
what we expect" check itself from becoming an oracle.

## What `TenantAPIKeyAuthentication`/`TenantAPIKeyAuth` actually check

Both integrations call one function,
`django_tenant_apikeys.core.authenticate_key()`, and only translate its
outcome into their framework's response. It runs this sequence and rejects
on the first failure:

1. Parse the `Authorization: Api-Key <key>` header (the adapter's job). No
   header, or a different scheme — not an error, just "didn't attempt to
   authenticate," so another authenticator gets a turn (DRF) or Ninja falls
   through to a 401 on its own.
2. **Shape check** — a key must be printable, whitespace-free, at most 128
   characters, and `<prefix>.<secret>` with a prefix that fits the column.
   Anything else is rejected without touching the database.
3. Look the row up by prefix (one indexed query; the tenant is joined in the
   same query). Unknown prefix — rejected.
4. `verify_key(raw_key)` — tampered or wrong secret, rejected, with the
   **same** response as an unknown prefix. Distinguishing "prefix exists but
   secret is wrong" from "prefix doesn't exist" would leak which prefixes are
   valid to anyone probing with guesses.
5. `is_active` — a revoked or manually deactivated key is rejected.
6. `expires_at` — an expired key is rejected.
7. **Environment** — if `TENANT_API_KEY_ALLOWED_ENVIRONMENTS` is set, the
   key's `environment` must be in it.
8. **IP allowlist** — `allowed_ips`, checked against the client IP (see
   [IP restrictions](ip-restrictions.md)); a restricted key with no known
   client IP is refused.
9. **Tenant hook** — the model's `is_tenant_allowed()` (default: `True`).
10. On success: `record_usage()` updates `last_used_at` (throttled — see
    [Key lifecycle](key-lifecycle.md#last_used_at-without-a-write-on-every-request);
    also `last_used_ip` if `TENANT_API_KEY_RECORD_IP` is on), and if the
    concrete model has a `tenant` attribute, it's attached to
    `request.tenant`.

Steps 5–9 mean a view can't accept a valid key and bypass its policies: they
happen before any of your code runs, in both frameworks.
[Scopes](scopes.md) and [rate limiting](rate-limiting.md) are separate —
scopes are a property of the view (a DRF permission / Ninja `scopes=`), rate
limiting is a DRF/Ninja throttle.

What the client sees: a key that fails to authenticate (steps 2–6) is a 401;
a valid key refused by a policy (steps 7–9) is a 403. Steps 2–4 always give
the same `"Invalid API key."`; once the secret has verified, DRF says
`"This API key has been deactivated."`, `"has expired."`, and so on (Ninja
returns a bare 401 for authentication failures). Every rejection is logged
on the `django_tenant_apikeys` logger and sent on the `api_key_rejected`
signal with its precise reason — see [Signals and logging](signals.md).

## Looking up a key without a full request

```python
from myapp.models import OrganizationAPIKey

api_key = OrganizationAPIKey.objects.get_from_key(raw_key)  # indexed prefix lookup
api_key.verify_key(raw_key)  # you still need to call this yourself
```

`get_from_key()` only does the indexed prefix lookup — it doesn't verify the
secret or check `is_active`/`expires_at`. Useful outside a request/response
cycle (a script, a management command), where you want the lookup and the
verification as separate, explicit steps rather than the framework
integration's all-in-one `authenticate()`.

`TenantAPIKeyManager.get_usable_keys()` is the other manager method —
active, unexpired keys only, for anything that needs to iterate keys that
could currently authenticate (an audit script, say).

## Async views

`TenantAPIKeyAuthentication.authenticate()` is synchronous, matching DRF's
own authentication classes, which don't have first-class async support
either. Wrap the lookup in `sync_to_async` if you're calling it from async
code directly.

## Next

- [Multi-tenancy](multi-tenancy.md) — how `request.tenant` gets set, and
  what isolation the package does and doesn't guarantee.
- [Key lifecycle](key-lifecycle.md) — rotation, revocation, expiration.
- [Security](security.md) — the full threat-model writeup, including what's
  explicitly out of scope.
