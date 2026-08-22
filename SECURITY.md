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

In scope: key generation, hashing, verification, scope checks, and the
`authentication.py` / `permissions.py` / `admin.py` integrations in this
repository.

Out of scope:

- Brute-force protection on failed authentication attempts. This library
  verifies a presented key; it doesn't throttle guesses. Pair
  `TenantAPIKeyAuthentication` with a DRF throttle class if that matters
  for your deployment.
- How a consuming project configures `TENANT_API_KEY_MODEL`, stores keys
  client-side, or transmits them (e.g. logging the `Authorization` header).
