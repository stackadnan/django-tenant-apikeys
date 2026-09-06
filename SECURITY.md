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
- Cross-process consistency of the default rate-limit backend. It's
  correct under concurrent requests within one process; multiple worker
  processes sharing a single limit requires pointing `CACHES["default"]`
  at a backend that supports atomic operations across processes
  (Memcached, a shared Redis), which is a deployment choice, not something
  this library can guarantee on its own.
- Multi-hop trusted-proxy-chain validation for `TENANT_API_KEY_TRUSTED_PROXY_HEADER`.
  It reads the first entry of a configured header, assuming a single
  trusted reverse proxy in front of Django.
- How a consuming project configures `TENANT_API_KEY_MODEL`, stores keys
  client-side, or transmits them (e.g. logging the `Authorization` header).
