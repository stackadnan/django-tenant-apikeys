# Django API key security

What this package actually does to keep a key safe, the reasoning behind
each decision, and — just as important — what it explicitly does not
protect against. Read this before betting a production auth path on it,
same as you should with any new dependency. See also
[SECURITY.md](https://github.com/stackadnan/django-tenant-apikeys/blob/main/SECURITY.md)
in the repository for how to report a vulnerability.

## Generation

Keys are generated with `secrets.token_hex()`/`secrets.token_urlsafe()` —
Python's cryptographically secure random source, not `random` (a Mersenne
Twister, predictable enough to be reconstructed from its own output, and
never appropriate for anything security-sensitive). The secret portion
carries 256 bits of entropy.

## Storage: unsalted SHA-256, deliberately

The hash is a single, unsalted SHA-256 pass (`hash_key()`), and that's a
decision, not an oversight. Salted, deliberately-slow password hashers
(bcrypt, PBKDF2, argon2) exist to slow down brute-forcing a **low-entropy**
secret — a human-chosen password drawn from a small effective keyspace. The
secret half of an API key here already has 256 bits of entropy from
`secrets.token_urlsafe()`. There's no dictionary or rainbow-table attack
that applies to it, so salting buys nothing, and a deliberately slow hash
would only add real cost to every authenticated request without adding
real protection.

**The raw key can't be recovered, by design.** Once `generate_key()`
returns it, that's the only copy that will ever exist — not in the
database, not in logs, not in the admin, ever again. If your app loses it
before showing it to the user, the fix is issuing a new key
([Key lifecycle](key-lifecycle.md)), not digging through the database.

The `prefix`/`secret` split (see [Authentication](authentication.md)) means
the cleartext `prefix` column carries no real entropy on its own — logging
it, showing it in the admin, or including it in an error message costs
nothing, since it's not the credential.

## Verification: constant time, indexed lookup

`verify_key()` uses `secrets.compare_digest()` rather than `==`. A plain
string comparison returns as soon as it hits a mismatched byte, which leaks
timing information an attacker could use to guess a hash one byte at a
time; `compare_digest()` always takes the same time regardless of where the
strings differ.

Lookup is prefix-indexed, then verified: one indexed query on `prefix`,
then one constant-time comparison on that single row — not a scan-and-hash
over every key in the table, no matter how many keys exist.

An unrecognized prefix and a recognized prefix with a wrong/tampered secret
produce the **exact same rejection** (`"Invalid API key."`, a 401).
Distinguishing "this prefix doesn't exist" from "this prefix exists but the
secret is wrong" in the response would let an attacker enumerate which
prefixes are real.

## Lifecycle: revocation, expiration, rotation

`revoke()` sets the same `is_active` flag authentication already checks —
there's no second enforcement path that could fall out of sync with it, and
`revoked_at`/`revoked_reason` are audit metadata only; nothing about an
authentication response distinguishes "revoked" from "invalid" from
"expired," so a caller probing with guessed keys can't learn anything about
a key's history from how it fails. `rotate()` refuses to run on an
already-inactive or expired key, and wraps issuing the replacement +
revoking the original in one `transaction.atomic()` block, so a rotation
can't half-complete. Full detail: [Key lifecycle](key-lifecycle.md).

## IP restrictions: don't trust a spoofable header by default

`get_client_ip()` reads `REMOTE_ADDR` — the actual TCP connection's source
address — unless `TENANT_API_KEY_TRUSTED_PROXY_HEADER` explicitly opts into
trusting a specific header instead. This is unset by default on purpose:
`X-Forwarded-For` and headers like it are ordinary request headers that any
client can set to whatever they want. Turning the setting on without an
actual trusted reverse proxy stripping client-supplied copies of that
header first would let any caller claim their own "IP" and walk straight
through an `allowed_ips` restriction. See
[IP restrictions](ip-restrictions.md#trusting-a-proxy-header) for the exact
mechanics and its single-hop limitation.

## Rate limiting is not brute-force protection

`rate_limit` caps how often a **valid, already-resolved** key can be used —
`check_rate_limit()` runs after `verify_key()` has already succeeded. It
says nothing about how many wrong keys someone can try against your
authentication endpoint. Pair `TenantAPIKeyAuthentication`/`TenantAPIKeyAuth`
with a DRF throttle class scoped to unauthenticated requests, or your
reverse proxy / WAF, if guessing protection at the authentication step
itself matters for your deployment. See
[SECURITY.md's scope section](https://github.com/stackadnan/django-tenant-apikeys/blob/main/SECURITY.md#scope)
for what's explicitly out of scope for this project.

Rate-limit state also can't leak between keys or tenants — see
[Rate limiting: tenant isolation](rate-limiting.md#tenant-isolation) — and
its default backend's consistency is bounded by whichever Django cache
backend it's pointed at; see
[Rate limiting: how the default backend counts requests](rate-limiting.md#how-the-default-backend-counts-requests)
for the concurrency and multi-process detail.

## Tenant isolation

A key resolves to exactly one tenant, in the same query that verifies it —
there's no code path where authenticating with tenant A's key attaches
tenant B's `request.tenant`. What this package does *not* do: filter your
other querysets for you. `request.tenant` being set correctly is the
guarantee; applying it to every other query in your view is still your
application's responsibility. See
[Multi-tenancy: what isolation the package gives you, and what it doesn't](multi-tenancy.md#what-isolation-the-package-gives-you-and-what-it-doesnt).

## Transport and handling — outside this package's control, but worth stating

- **HTTPS, always.** A key hashed correctly at rest is still a plaintext
  bearer credential in transit. TLS protects it on the wire; nothing about
  hashing at rest substitutes for that.
- **Headers, not query strings.** A key in a URL ends up in server access
  logs, browser history, and `Referer` headers sent to third parties.
  `Authorization: Api-Key <key>` keeps it out of all three — this is the
  scheme both `TenantAPIKeyAuthentication` and `TenantAPIKeyAuth` parse.
- **Never log the raw key.** Log the `prefix` if you need to identify which
  key was involved in an incident — it's designed to be safe to log; the
  secret half never should be.

## What this library does not protect against

Stated plainly, matching
[SECURITY.md's scope section](https://github.com/stackadnan/django-tenant-apikeys/blob/main/SECURITY.md#scope):

- Brute-force guessing against the authentication endpoint itself — see
  "Rate limiting is not brute-force protection" above.
- How a consuming project configures `TENANT_API_KEY_MODEL`, stores keys
  client-side, or transmits them elsewhere in the stack (e.g. accidentally
  logging the `Authorization` header in middleware you wrote).
- Automatic queryset filtering by tenant — see "Tenant isolation" above.
- A multi-hop trusted-proxy chain for IP resolution — see
  [IP restrictions](ip-restrictions.md#trusting-a-proxy-header).
- Cross-process rate-limit consistency with the default cache backend — see
  [Rate limiting](rate-limiting.md#how-the-default-backend-counts-requests).

## Reporting a vulnerability

Don't open a public issue. Use GitHub's private reporting form:
<https://github.com/stackadnan/django-tenant-apikeys/security/advisories/new>.
Full policy: [SECURITY.md](https://github.com/stackadnan/django-tenant-apikeys/blob/main/SECURITY.md).

## Next

- [Testing](testing.md) — how the package's own test suite proves every
  rejection path, not just the happy path.
- [Authentication](authentication.md) — the full mechanics referenced
  throughout this page.
