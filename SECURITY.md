# Security Policy

## Supported versions

This project is pre-1.0. Only the latest release on PyPI is supported —
upgrade before filing a report.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's
private reporting form instead:

https://github.com/stackadnan/django-tenant-apikeys/security/advisories/new

Include the version you're on, a minimal reproduction, and the impact as
you see it. Expect an initial response within a few days. If the report is
confirmed, a fix will be prepared and released before any public disclosure.

## Scope

In scope: key generation, hashing, verification, scope checks, IP/CIDR
allowlisting, rate limiting, and the `authentication.py` / `permissions.py`
/ `ninja.py` / `admin.py` / `ip.py` / `ratelimit.py` integrations in this
repository.

Out of scope:

- Brute-force protection on failed authentication attempts. This library
  verifies a presented key; it doesn't throttle guesses against the
  authentication endpoint itself. `rate_limit` caps usage of a key that has
  *already* verified successfully — it runs after `verify_key()`, not
  before it. Pair `TenantAPIKeyAuthentication`/`TenantAPIKeyAuth` with a
  DRF throttle class (or your reverse proxy) if guessing protection at the
  authentication step matters for your deployment.
- Rate-limit accuracy beyond what the configured Django cache provides.
  The default backend is exact only on a cache whose `add()`/`incr()` are
  atomic and shared across workers (Memcached, a shared Redis).
  LocMemCache is per-process; DatabaseCache and FileBasedCache can lose
  increments under concurrency; DummyCache enforces nothing (the library
  emits a `RuntimeWarning` for all three). Choosing the cache is a
  deployment decision this library can't make for you.
- Verifying that the proxy setup behind `TENANT_API_KEY_TRUSTED_PROXY_HEADER`
  is what you think it is. With the setting on, the client IP is the
  `TENANT_API_KEY_TRUSTED_PROXY_COUNT`-th entry from the right of that
  header (default: the rightmost). That's only correct if that many
  trusted proxies sit in front of Django and the header can't reach it any
  other way.
- How a consuming project configures `TENANT_API_KEY_MODEL`, stores keys
  client-side, or transmits them (e.g. logging the `Authorization` header).
