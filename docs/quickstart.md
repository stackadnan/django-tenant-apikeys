# Quickstart

This walks through issuing and verifying your first tenant-scoped API key,
end to end. It assumes you've already run
`pip install django-tenant-apikeys[drf]` — see [Installation](installation.md)
if not.

## 1. Define your concrete key model

`AbstractTenantAPIKey` ships abstract on purpose — every project's tenant
model looks different, so you decide how the two connect:

```python
# myapp/models.py
from django.db import models
from django_tenant_apikeys.models import AbstractTenantAPIKey


class Organization(models.Model):
    name = models.CharField(max_length=100)


class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(
        Organization,
        related_name="api_keys",
        on_delete=models.CASCADE,
    )
```

The field has to be named `tenant`. Both `TenantAPIKeyAuthentication` and
`TenantAPIKeyAuth` (Ninja) check for an attribute with that exact name and,
if it exists, attach it to the request as `request.tenant`. Name it
something else and you just lose that one convenience — everything else
still works. See [Multi-tenancy](multi-tenancy.md) for how tenant
resolution actually works.

## 2. Point Django at it

```python
# settings.py
INSTALLED_APPS = [
    ...
    "django_tenant_apikeys",
    "rest_framework",
    "myapp",
]

TENANT_API_KEY_MODEL = "myapp.OrganizationAPIKey"
```

`TENANT_API_KEY_MODEL` is how every generic piece of the package —
`get_api_key_model()`, `TenantAPIKeyAuthentication`, `TenantAPIKeyAuth`, the
management commands — finds your concrete model without hardcoding an
import. See [Configuration](configuration.md) for the full settings
reference.

## 3. Migrate as usual

```bash
python manage.py makemigrations myapp
python manage.py migrate
```

## 4. Issue a key

```python
from myapp.models import Organization, OrganizationAPIKey

org = Organization.objects.get(name="Acme Inc.")

instance, raw_key = OrganizationAPIKey.generate_key(
    name="CI deploy key",
    tenant=org,
    scopes=["deployments:write"],
)

print(raw_key)
# tak_live_3f9a2c1d.k7pQ2m1vXyN0...
# show this to the user right now -- it's never stored, and can't be
# shown again once you look away
```

`instance` is already saved by the time you get it back. What lands in the
database is `instance.hashed_key`, a SHA-256 digest — not `raw_key`. Copy the
raw key out of that print statement and hand it to whoever needs it, because
this is the only chance you get. See [Authentication](authentication.md) for
why the package works this way.

## 5. Authenticate a request

```python
# myapp/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from django_tenant_apikeys.authentication import TenantAPIKeyAuthentication
from django_tenant_apikeys.permissions import HasAPIKeyScope


class DeploymentsView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["deployments:write"]

    def post(self, request):
        # request.auth is the authenticated OrganizationAPIKey instance
        # request.tenant is request.auth.tenant, attached automatically
        request.tenant.deployments.create(...)
        return Response(status=201)
```

A client calls it with:

```
Authorization: Api-Key tak_live_3f9a2c1d.k7pQ2m1vXyN0...
```

Using Django Ninja instead? See [Django Ninja](django-ninja.md) — the
underlying model and hashing are identical, only the integration code
differs.

## Next steps

- [Scopes](scopes.md) — designing a scope taxonomy for more than one
  permission level per tenant.
- [Environments](environments.md), [IP restrictions](ip-restrictions.md),
  [Rate limiting](rate-limiting.md) — the optional per-key policies added in
  0.4.0.
- [Key lifecycle](key-lifecycle.md) — rotating and revoking keys without
  breaking clients.
- A full runnable version of everything above:
  [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas).
