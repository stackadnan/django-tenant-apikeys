# django-tenant-apikeys vs djangorestframework-api-key: which one do you need

Both packages generate Django API keys with a prefix + hashed-secret shape,
both let you subclass an abstract model to attach your own relation, and
both show up in the same search results. But they solve different
problems, and picking the wrong one means either fighting the library or
rebuilding half of it yourself. This page is a factual comparison, not a
sales pitch — [djangorestframework-api-key](https://github.com/florimondmanca/djangorestframework-api-key)
is a solid, more mature project; it's just built for a narrower job.

## The core difference: permission gate vs authentication backend

This is the distinction that decides which one you want, and it's stated
directly in djangorestframework-api-key's own docs: it ships a **permission
class** (`HasAPIKey`), not an authentication class, and it says explicitly
that *"this package is NOT meant for authentication. You should NOT use
this package to identify individual users, either directly or
indirectly."* It's designed to sit alongside your existing auth (or no
auth at all) as a yes/no gate: "does this request carry a valid key,"
nothing more. It doesn't tell your view *which* key or *which* tenant made
the request.

[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
ships an **authentication class** (`TenantAPIKeyAuthentication`). It
identifies the caller — `request.auth` is the actual key instance — and if
your concrete model has a `tenant` relation, it attaches it to
`request.tenant` automatically. If your API's authorization model is "this
request belongs to *this* tenant, scoped to *this* permission," you need
that identification step; a permission-only gate can't give it to you
without you writing the lookup yourself in every view.

## Model fields, side by side

| Field | djangorestframework-api-key | django-tenant-apikeys |
|---|---|---|
| Public lookup value | `prefix` (8 chars) | `prefix` (up to 32 chars, includes a `_live_` marker) |
| Secret storage | hashed via Django's pluggable password hasher framework, with automatic rehashing when the preferred hasher changes | unsalted SHA-256 hex digest (the key material already has 256 bits of entropy, so salting doesn't add anything) |
| Revocation | `revoked` (boolean) — docs note this "cannot be undone" | `is_active` (boolean) — a toggle, can be flipped back on |
| Expiration | `expiry_date` | `expires_at` |
| Scopes/permissions per key | not built in | `scopes` (JSON list), with exact, `namespace:*`, and global `*` wildcard matching via `has_scope()` |
| Usage tracking | not built in | `last_used_at`, updated by a throttled `record_usage()` |
| Tenant/owner relation | supported by subclassing `AbstractAPIKey` (their own docs show an `OrganizationAPIKey` example) | supported by subclassing `AbstractTenantAPIKey`, and the auth class attaches it to `request.tenant` automatically |
| Framework support | Django REST Framework only | framework-agnostic core; DRF classes included, plus a documented Django Ninja recipe |

The subclassing pattern for adding a tenant relation is actually the same
shape in both — that part isn't a differentiator. What differs is what
happens *after* the key is verified.

## When to pick djangorestframework-api-key

- You need a simple "is this a legitimate server, block anonymous
  traffic" gate — e.g. blocking scrapers or unauthenticated clients from a
  public-ish endpoint, without needing to know which caller it was.
- You're already authenticating users/services another way (session,
  JWT, mTLS) and just want an additional API-key check layered on top.
- You don't need per-key scopes or per-key usage tracking.

## When to pick django-tenant-apikeys

- The API key **is** the identity — there's no other auth mechanism, and
  a view needs to know which tenant/organization is calling.
- Different keys belonging to the same tenant need different permissions
  (a read-only partner integration vs. your own backend's key).
- You want to know when a key was last used, without hand-rolling a
  throttled write path.
- You want the same core to work from a Django Ninja auth callable, not
  just DRF.

## Can you use both?

There's nothing stopping you from running djangorestframework-api-key's
`HasAPIKey` as a coarse "block requests with no key at all" gate in front
of views that also use `TenantAPIKeyAuthentication` for the actual identity
— but in practice this is redundant: `TenantAPIKeyAuthentication` already
rejects missing/invalid/expired/revoked keys on its own, so stacking the
two doesn't buy you anything unless you're migrating between them
incrementally.

## Try it

- `pip install django-tenant-apikeys[drf]`
- Full quickstart and API reference: the
  [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working end-to-end project: [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
- See also: [Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication)
  and [Scoping API keys per tenant in Django REST Framework](https://github.com/stackadnan/django-tenant-apikeys/wiki/Scoping-API-keys-per-tenant-in-Django-REST-Framework)
