# Django REST Framework API key authentication

```bash
pip install django-tenant-apikeys[drf]
```

## Authenticating requests

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

Or wire it globally instead of per view:

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "django_tenant_apikeys.authentication.TenantAPIKeyAuthentication",
    ],
}
```

Clients send:

```
Authorization: Api-Key tak_live_3f9a2c1d.Xk7pQ2m1vYzN0hT8sR4uWjLdEaFbGcHiJk
```

A few things worth knowing about `authenticate()`:

- No `Authorization` header, or a scheme other than `Api-Key`? It returns
  `None` and gets out of the way, so any other authenticator you have
  configured gets a turn.
- Scheme matches but the key is missing, malformed, unrecognized, tampered
  with, deactivated, or expired? It raises `AuthenticationFailed` — a plain
  401, same as DRF's built-in authenticators. See
  [Authentication](authentication.md#what-tenantapikeyauthenticationtenantapikeyauth-actually-check)
  for the exact check order and messages.
- On success it returns `(None, api_key_instance)`. The `None` where a
  Django `User` would normally sit is intentional — an API key
  authenticates an integration, not a person, so `request.user` stays
  anonymous and `request.auth` is where the key instance actually lives.

Running more than one kind of key in the same project? Subclass instead of
juggling settings:

```python
class PartnerAPIKeyAuthentication(TenantAPIKeyAuthentication):
    model = PartnerAPIKey
```

## Scope checks

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["orders:read", "orders:write"]  # all of these, not any
```

Full detail, including per-action scopes on a `ViewSet`: [Scopes](scopes.md).

## IP restrictions

```python
from django_tenant_apikeys.permissions import HasAllowedIP

class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAllowedIP, HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

Full detail, including trusted-proxy-header configuration:
[IP restrictions](ip-restrictions.md).

## Rate limiting

```python
from django_tenant_apikeys.permissions import WithinRateLimit

class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [WithinRateLimit, HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

Full detail, including how the default backend counts requests and its
multi-process limitations: [Rate limiting](rate-limiting.md).

## How the policies interact

Combine all three (or any subset) in `permission_classes`, in this order:

```python
permission_classes = [HasAllowedIP, WithinRateLimit, HasAPIKeyScope]
```

DRF checks `permission_classes` in list order, and stops at the first one
that denies the request — so the order you list them in is the order they
actually run in:

```
Authentication (extract, verify, active/expired, resolve tenant)
      ↓
IP restriction   (HasAllowedIP)
      ↓
Rate limit       (WithinRateLimit)
      ↓
Scope            (HasAPIKeyScope)
      ↓
Your view
```

A request from a disallowed IP never reaches the rate limiter or the scope
check. A request over its rate limit never reaches the scope check, but
*does* still count against — and gets rejected by — the rate limiter even
if it would've failed the scope check anyway, since the rate limiter runs
first.

`TenantAPIKeyAuthentication` itself hasn't changed shape for any of this —
it still only extracts the key, verifies it, checks
`is_active`/`expires_at`, and resolves `request.tenant`. IP, rate limit, and
scope are separate, independently testable permission classes layered on
top, not folded into authentication. None of them are required — a
`permission_classes = [HasAPIKeyScope]` view from before these existed
still behaves exactly as it did.

## Next

- [Django Ninja](django-ninja.md) — the same policies, without DRF's
  permission-class system.
- [Multi-tenancy](multi-tenancy.md) — how `request.tenant` gets resolved.
- [Testing](testing.md) — testing a DRF authentication/permission chain
  without spinning up real URL routing.
