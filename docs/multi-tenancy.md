# Multi-tenant Django API keys

Django and Django REST Framework give you `TokenAuthentication` and session
auth, both built around a single `User`. Neither has an opinion about a
*tenant* owning the key. In a multi-tenant SaaS, a key has to answer three
questions at once:

1. **Which tenant does this request belong to?** — every query after
   authentication needs to be scoped to that tenant, not the whole table.
2. **What is this specific key allowed to do?** — a partner's read-only
   integration key and your own internal automation key shouldn't have the
   same access, even if they belong to the same tenant.
3. **Can this key be revoked or rotated without affecting the tenant's other
   keys?** — a single shared secret per tenant fails this immediately.

A generic token table (one row per `User`, one permanent token) answers
none of these well. This page covers how `django-tenant-apikeys` does.

## Bring your own tenant model

`AbstractTenantAPIKey` doesn't know what a "tenant" is — it has no opinion
on your `Organization`/`Account`/`Workspace` model beyond one convention:
subclass it and add a foreign key literally named `tenant`.

```python
class Organization(models.Model):
    name = models.CharField(max_length=100)


class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(
        Organization,
        related_name="api_keys",
        on_delete=models.CASCADE,
    )
```

That's the entire integration. No mixins, no signals, no required interface
on `Organization` itself.

## How `request.tenant` gets set

Both `TenantAPIKeyAuthentication` and `TenantAPIKeyAuth` (Ninja) do the
same check after a key verifies successfully:

```python
if hasattr(api_key, "tenant"):
    request.tenant = api_key.tenant
```

`hasattr` — not a fixed list of known model names — which is why the field
has to be named exactly `tenant`. Name it something else and you lose this
one convenience (you'd read `request.auth.organization` or whatever you
called it yourself); everything else about authentication, scopes, IP
restrictions, and rate limiting still works identically, since none of them
depend on the tenant relation existing at all.

`UnlinkedAPIKey` in the test suite is a concrete model with no `tenant`
field — it exists specifically to prove `request.tenant` is never set when
there's nothing to attach.

## What isolation the package gives you, and what it doesn't

A key belongs to exactly one tenant, resolved from one row, in one query,
as part of authentication. That's the isolation guarantee: **you can't
authenticate as tenant A's key and get tenant B's `request.tenant`.**

What it does *not* do:

- **It doesn't filter your other querysets.** `request.tenant` is set;
  applying it to `Order.objects.filter(tenant=request.tenant)` in your own
  views is still your job. There's no automatic tenant-scoping middleware or
  manager here — that would mean the package guessing at your schema.
- **It doesn't stop two tenants from having a key with the same name, the
  same scopes, or the same rate limit.** Nothing about those attributes is
  tenant-specific by design — a `"name"` field is just a label, and two
  tenants issuing identically-configured keys is normal, not a collision.
  What *can't* collide is the actual authenticated identity: each key row
  belongs to one tenant, and rate-limit state (see
  [Rate limiting](rate-limiting.md#tenant-isolation)) is keyed by each key's
  own primary key, not shared across rows.
- **It doesn't support a key shared across several tenants.** `tenant` is a
  single `ForeignKey`. If you need that relationship, model it yourself —
  the package doesn't assume anything about `tenant` beyond its name and
  that it resolves to one object.

## Shared-schema vs. schema-per-tenant

Everything above assumes **shared-schema** multi-tenancy: every tenant's
rows, including the API key table, live in the same tables, distinguished
by the `tenant` foreign key. That's the simplest thing that works, and it's
the architecture `AbstractTenantAPIKey` and
[`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
are both built around.

**Schema-per-tenant** (e.g. via
[django-tenants](https://django-tenants.readthedocs.io/)) gives each tenant
an isolated PostgreSQL schema instead. This package has no built-in
awareness of that pattern, `search_path` switching, or shared-vs-tenant app
routing — combining the two is glue code you'd write and verify yourself,
not something tested here. The
[wiki has a deeper writeup](https://github.com/stackadnan/django-tenant-apikeys/wiki/Multi%E2%80%90tenant-Django-patterns:-shared%E2%80%90schema-vs-schema%E2%80%90per%E2%80%90tenant,-and-where-API-keys-fit)
of where the two approaches diverge and roughly what that glue code would
need to do, if you're evaluating the combination.

## Next

- [Authentication](authentication.md) — the full request-rejection sequence
  tenant resolution is part of.
- [Scopes](scopes.md) — per-key permissions within a tenant.
- [Security](security.md) — tenant isolation as a security property,
  alongside the rest of the threat model.
