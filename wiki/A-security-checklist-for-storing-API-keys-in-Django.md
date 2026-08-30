# A security checklist for storing API keys in Django

Every point on this checklist is a decision
[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
had to make one way or the other — this page lays them out as a general
checklist, whether you're using this package or building your own. Each
item links back to the earlier page in this series that covers it in
depth.

## Generation

- **Use `secrets`, never `random`.** Python's `random` module is a
  Mersenne Twister — predictable enough to be reconstructed from output,
  not safe for anything security-sensitive. `generate_api_key()` uses
  `secrets.token_hex()` and `secrets.token_urlsafe()`, which pull from the
  OS's cryptographically secure random source.
- **Generate enough entropy.** This package uses 256 bits for the secret
  portion — matching the output size of the SHA-256 hash it's stored as.
  Less than that and you're trading real security margin for a
  marginally shorter string.

## Storage

- **Never store the raw key — only a hash.** If your database is ever
  read (a backup leak, a misconfigured replica, an injection bug), a
  stored raw key hands over full access immediately. A hash doesn't.
- **Don't reach for a slow, salted password hasher for this.** bcrypt,
  PBKDF2, and argon2 exist to slow down brute-forcing a *low-entropy*
  secret — a human-chosen password from a small effective keyspace. A
  256-bit random token has no such weakness to defend against; salting
  and deliberately slow hashing add cost on every single request without
  adding real protection. `hash_key()` uses a single unsalted SHA-256
  pass for exactly this reason — verifying a request stays cheap at
  scale, and the "unsalted" part is safe *specifically because* the input
  already has full entropy, which would not be true for a password.
- **Split into a public prefix and a secret.** Storing one opaque blob
  means finding a match requires scanning and hashing every stored key
  per request. Splitting a cleartext, indexed `prefix` from the hashed
  `secret` turns lookup into one indexed query, and the prefix carries no
  real entropy, so exposing it (in logs, in the admin list view) costs
  you nothing.

## Verification

- **Compare hashes in constant time.** A plain `==` on two strings returns
  as soon as it finds a mismatched byte, which leaks timing information
  an attacker can use to guess a hash byte-by-byte. `verify_key()` uses
  `secrets.compare_digest()`, which always takes the same time regardless
  of where the strings differ.
- **Look up by prefix, then verify.** `get_from_key()`'s indexed lookup on
  `prefix`, followed by `verify_key()` on just that one row, keeps
  authentication to a single query plus one constant-time comparison — no
  matter how many keys exist in the table.

## Display

- **Show the raw key exactly once, at creation.** Covered in depth in
  [One-time secret reveal in Django admin](https://github.com/stackadnan/django-tenant-apikeys/wiki/One%E2%80%90time-secret-reveal-in-Django-admin:-the-pattern-behind-save_model) —
  the short version is that if it can be shown again later, it was
  retrievable, which means it wasn't really hashed for anything that
  matters.
- **Mask it everywhere else.** List views, logs, error messages — none of
  them should render anything derived from the secret. `masked_key()`
  shows the prefix plus a fixed run of bullet characters, never the hash.

## Transport and handling

- **HTTPS, always.** A key hashed correctly at rest is still a plaintext
  bearer credential in transit — TLS is what protects it on the wire, and
  nothing about hashing at rest substitutes for that.
- **Headers, not query strings.** A key in a URL ends up in server access
  logs, browser history, and `Referer` headers sent to third parties on
  the next hop. `Authorization: Api-Key <key>` keeps it out of all three.
- **Never log the raw key.** Log the `prefix` if you need to identify
  which key was involved in an incident — it's designed to be safe to
  log; the secret half never should be.

## Lifecycle

- **Support expiration.** `expires_at`/`is_expired` for keys that should
  stop working on a known schedule.
- **Support immediate, reversible revocation, separate from expiration.**
  `is_active` for "stop this key right now," distinct from a time-based
  plan. See [Rotating and expiring API keys](https://github.com/stackadnan/django-tenant-apikeys/wiki/Rotating-and-expiring-API-keys-in-Django-without-breaking-existing-clients)
  for why both matter and how they differ in practice.
- **Know when a key was last used.** A key nobody's used in months is a
  liability sitting around for no benefit — `last_used_at` (see
  [Throttled last_used_at tracking](https://github.com/stackadnan/django-tenant-apikeys/wiki/Throttled-last_used_at-tracking:-avoiding-a-DB-write-on-every-authenticated-request))
  is what lets you find and retire those.

## Scope

- **Don't grant more access than a key needs.** An all-or-nothing key
  means every integration you hand one to can do everything your API can
  do. Per-key `scopes` (see [Scoping API keys per tenant](https://github.com/stackadnan/django-tenant-apikeys/wiki/Scoping-API-keys-per-tenant-in-Django-REST-Framework))
  let a read-only integration actually be read-only.

## Testing

- **Test every rejection path, not just the happy path.** A security
  boundary that's only tested for the case where it lets you in hasn't
  really been tested. See
  [Testing a custom DRF authentication backend](https://github.com/stackadnan/django-tenant-apikeys/wiki/Testing-a-custom-DRF-authentication-backend-with-pytest%E2%80%90django)
  for what that looks like in practice.

## The rest of this series

1. [Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication)
2. [Scoping API keys per tenant in Django REST Framework](https://github.com/stackadnan/django-tenant-apikeys/wiki/Scoping-API-keys-per-tenant-in-Django-REST-Framework)
3. [django-tenant-apikeys vs djangorestframework-api-key: which one do you need](https://github.com/stackadnan/django-tenant-apikeys/wiki/django%E2%80%90tenant%E2%80%90apikeys-vs-djangorestframework%E2%80%90api%E2%80%90key:-which-one-do-you-need)
4. [Rotating and expiring API keys without breaking existing clients](https://github.com/stackadnan/django-tenant-apikeys/wiki/Rotating-and-expiring-API-keys-in-Django-without-breaking-existing-clients)
5. [One-time secret reveal in Django admin](https://github.com/stackadnan/django-tenant-apikeys/wiki/One%E2%80%90time-secret-reveal-in-Django-admin:-the-pattern-behind-save_model)
6. [Django Ninja API key auth without DRF](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-Ninja---API-key-auth-without-DRF)
7. [Testing a custom DRF authentication backend with pytest-django](https://github.com/stackadnan/django-tenant-apikeys/wiki/Testing-a-custom-DRF-authentication-backend-with-pytest%E2%80%90django)
8. [Throttled last_used_at tracking](https://github.com/stackadnan/django-tenant-apikeys/wiki/Throttled-last_used_at-tracking:-avoiding-a-DB-write-on-every-authenticated-request)
9. [Multi-tenant Django patterns: shared-schema vs schema-per-tenant, and where API keys fit](https://github.com/stackadnan/django-tenant-apikeys/wiki/Multi%E2%80%90tenant-Django-patterns:-shared%E2%80%90schema-vs-schema%E2%80%90per%E2%80%90tenant,-and-where-API-keys-fit)
10. This page

## Try it

- Full quickstart and API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working end-to-end project: [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
