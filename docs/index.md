# django-tenant-apikeys

**Multi-tenant API key authentication for Django.**

`django-tenant-apikeys` is a Django library for issuing API keys that belong
to a tenant — an organization, account, or workspace — rather than to a
single `User`. It covers the part of Django API key authentication that
`TokenAuthentication` and session auth don't: a key is generated once, shown
once, stored as a hash, resolved to its tenant on every request, and can
carry its own scopes, IP restrictions, and rate limit, independent of every
other key that tenant has issued.

It ships a small framework-agnostic core plus first-class integrations for
**Django REST Framework** and **Django Ninja**.

## Who this is for

You're building a Django API that other systems call programmatically —
partner integrations, internal services, customer-facing automation — and
more than one tenant uses your API. If a single tenant issues more than one
key (a read-only reporting integration and a full-access internal key, say),
or if you need to know *which* tenant and *which* key made a request without
writing that lookup yourself in every view, this is the shape of problem the
package solves.

If you're not multi-tenant, or a permission-only gate ("does this request
carry a valid key at all") is enough for you, a narrower package like
[djangorestframework-api-key](https://florimondmanca.github.io/djangorestframework-api-key/)
is probably a better fit — see the comparison in the
[wiki](https://github.com/stackadnan/django-tenant-apikeys/wiki/django%E2%80%90tenant%E2%80%90apikeys-vs-djangorestframework%E2%80%90api%E2%80%90key:-which-one-do-you-need)
if you're deciding between the two.

## What it actually does

- **Generates and verifies keys.** A key is `secrets`-generated, split into
  a cleartext `prefix` (for an indexed lookup) and a secret (stored only as
  a SHA-256 hash). See [Authentication](authentication.md).
- **Resolves the tenant automatically.** Subclass one abstract model, add a
  `tenant` foreign key, and both the DRF and Ninja integrations attach it to
  `request.tenant` on every authenticated request. See
  [Multi-tenancy](multi-tenancy.md).
- **Scopes access per key**, not per tenant, with exact, namespaced
  (`orders:*`), and global (`*`) wildcard matching. See [Scopes](scopes.md).
- **Restricts a key by IP or CIDR network** (IPv4 and IPv6). See
  [IP restrictions](ip-restrictions.md).
- **Rate-limits a key** per second/minute/hour/day, backed by Django's cache
  framework. See [Rate limiting](rate-limiting.md).
- **Tags a key with an environment** (production/staging/development/test)
  and arbitrary JSON metadata your application defines. See
  [Environments](environments.md) and [Metadata](metadata.md).
- **Handles the full lifecycle** — rotation, revocation, expiration, and
  throttled last-used tracking. See [Key lifecycle](key-lifecycle.md).

## 30 seconds

```python
# myapp/models.py
from django.db import models
from django_tenant_apikeys.models import AbstractTenantAPIKey


class Organization(models.Model):
    name = models.CharField(max_length=100)


class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(
        Organization, related_name="api_keys", on_delete=models.CASCADE
    )
```

```python
# settings.py
TENANT_API_KEY_MODEL = "myapp.OrganizationAPIKey"
```

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="CI deploy key",
    tenant=org,
    scopes=["deployments:write"],
)
print(raw_key)  # tak_live_3f9a2c1d.k7pQ2m1v... -- shown once, never stored
```

```python
# myapp/views.py (Django REST Framework)
from rest_framework.views import APIView
from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication
from django_tenant_apikeys.permissions import HasAPIKeyScope


class DeploymentsView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["deployments:write"]

    def post(self, request):
        request.tenant.deployments.create(...)  # attached automatically
```

That's the whole shape of it. Everything else in these docs is what to do
once you need more than the basics — scoped API keys across several
integrations, IP allowlists, per-key rate limits, or wiring the same key
model into Django Ninja instead of (or alongside) DRF.

## Where to go next

- New to the package? Start with [Installation](installation.md) and
  [Quickstart](quickstart.md).
- Already have keys authenticating and want to add policies? See
  [Environments](environments.md), [IP restrictions](ip-restrictions.md),
  and [Rate limiting](rate-limiting.md).
- Wiring this into an existing DRF or Ninja project? Jump straight to
  [Django REST Framework](django-rest-framework.md) or
  [Django Ninja](django-ninja.md).
- Deciding whether to trust this in production? Read
  [Security](security.md) first.
- Looking for a specific class or function? [API reference](api-reference.md).

A complete runnable project lives in
[`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
in the repository — clone it, run `python manage.py create_demo_key`, and
you have a real tenant-scoped key and a working `curl` command in about a
minute.
