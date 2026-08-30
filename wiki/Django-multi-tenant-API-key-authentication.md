# Django multi-tenant API key authentication

If you're building a Django API that multiple customers or partners call
programmatically — not end users logging in through a browser, but other
systems authenticating with a token — you eventually hit a gap: Django and
Django REST Framework give you `TokenAuthentication` and session auth, both
built around a single `User`. Neither one has an opinion about a *tenant*
owning the key, and neither one gives you per-key scopes, expiration, or
revocation out of the box.

This page explains what multi-tenant API key authentication actually
requires, and how [django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
implements it.

## What "multi-tenant" changes about API keys

In a single-tenant setup, one API key usually just stands in for "this is a
valid caller." In a multi-tenant SaaS, a key has to answer three questions
at once:

1. **Which tenant does this request belong to?** — every query after
   authentication needs to be scoped to that tenant, not the whole table.
2. **What is this specific key allowed to do?** — a partner's read-only
   integration key and your own internal automation key shouldn't have the
   same access, even if they belong to the same tenant.
3. **Can this key be revoked or rotated without affecting the tenant's other
   keys?** — a single shared secret per tenant fails this immediately.

A generic `TokenAuthentication` table (one row per `User`, one permanent
token) answers none of these well. You end up bolting on a `tenant_id`
column and a homemade scopes field to a library that wasn't designed for it.

## The model: prefix + secret, per-tenant by subclassing

`AbstractTenantAPIKey` is an abstract Django model. You subclass it and add
your own tenant relation:

```python
from django_tenant_apikeys.models import AbstractTenantAPIKey

class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(
        "myapp.Organization",
        related_name="api_keys",
        on_delete=models.CASCADE,
    )
```

Every key is generated as `<prefix>_live_<random>.{secret}` — the part
before the dot (`key_prefix`) is a cleartext, indexed lookup value with no
real entropy; the part after the dot is 256 bits of randomness that's
**only ever stored as a SHA-256 hash**:

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="Acme production key",
    tenant=acme,
    scopes=["orders:read"],
)
# raw_key is your only chance to see the secret -- store it, show it once,
# it isn't recoverable from `instance` afterwards.
```

This is the same shape Stripe and GitHub use for their own API keys: a
lookup succeeds or fails in one indexed query on `prefix`, and comparing
the secret is a constant-time `secrets.compare_digest` check
(`verify_key()`), so a database leak alone doesn't hand out working keys.

## Per-key scopes, not per-tenant

Scopes live on the key itself, not the tenant, so one tenant can issue keys
with different permissions to different integrations:

```python
key.scopes = ["orders:read", "orders:write"]
key.has_scope("orders:read")   # True -- exact match
key.has_scope("orders:*")      # also True -- namespaced wildcard
key.scopes = ["*"]
key.has_scope("anything:here") # True -- global wildcard
```

## Expiration and revocation

`is_active` (a plain boolean) revokes a key immediately without deleting
its audit trail. `expires_at` is optional — leave it blank for a key that
never expires, or set it for a time-boxed integration. `is_valid` combines
both:

```python
key.is_valid  # is_active and not is_expired
```

## Knowing when a key was last used

`last_used_at` is updated automatically by `record_usage()` every time a
key authenticates successfully. It's throttled by `LAST_USED_THRESHOLD`
(5 minutes by default) so a hot endpoint doesn't turn into a database write
on every single request — if the key was already marked used more recently
than the threshold, `record_usage()` is a no-op.

## Wiring it into Django REST Framework

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["orders:read"]

    def get(self, request):
        request.tenant  # the OrganizationAPIKey's tenant, attached automatically
```

`TenantAPIKeyAuthentication` parses `Authorization: Api-Key <key>`, verifies
the secret, checks `is_active`/`expires_at`, calls `record_usage()`, and —
if your concrete model has a `tenant` relation — attaches it to
`request.tenant`. `HasAPIKeyScope` then checks the view's `required_scopes`
against `request.auth.has_scope(...)`. No `required_scopes` means any
authenticated key is allowed through.

## Not tied to DRF

The model, key generation, and hashing live in `django_tenant_apikeys.models`
with no DRF import at all — `TENANT_API_KEY_MODEL` and `get_api_key_model()`
work from a plain view or a
[Django Ninja](https://github.com/stackadnan/django-tenant-apikeys#django-ninja-integration)
auth callable just as well.

## Try it

- `pip install django-tenant-apikeys[drf]`
- Full quickstart and API reference: the
  [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working end-to-end project: [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
