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

## IP restrictions and environments

Enforced during authentication itself — there is nothing to add to
`permission_classes`. A key with `allowed_ips` set is refused from any other
address (403), and, if you set `TENANT_API_KEY_ALLOWED_ENVIRONMENTS`, so is
a key from an environment that isn't listed. A view can't accept such a key
and forget to check, which is the point. See
[IP restrictions](ip-restrictions.md) (including trusted-proxy
configuration) and [Environments](environments.md).

`HasAllowedIP` still exists and still works, but it now only repeats a check
authentication has already made; it's deprecated and can be dropped from
`permission_classes`.

## Rate limiting

A key's `rate_limit` is enforced by a normal DRF throttle. Set it once for
every view:

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "django_tenant_apikeys.authentication.TenantAPIKeyAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "django_tenant_apikeys.throttling.TenantAPIKeyThrottle",
    ],
}
```

or per view with `throttle_classes = [TenantAPIKeyThrottle]`. DRF answers
429 with `Retry-After`; the throttle also sets `X-RateLimit-*` headers. A key
with no `rate_limit`, and a request not authenticated by an API key, are
never throttled. `WithinRateLimit` (a permission class doing a throttle's
job) still works, is deprecated, and shouldn't be combined with the throttle
or requests are counted twice.

Unlike IP and environment, rate limiting is applied through DRF's own
throttling settings rather than inside authentication, because it's an
availability control DRF already has a global switch for. Full detail,
including cache backends: [Rate limiting](rate-limiting.md).

## How a request is handled

```
Authentication  (shape → lookup → secret → active → expiry
                 → environment → IP allowlist → tenant hook → usage)
      ↓  401 if the key fails to authenticate, 403 if a policy refuses it
Permissions     (HasAPIKeyScope)
      ↓  403
Throttles       (TenantAPIKeyThrottle)
      ↓  429
Your view
```

Everything security-relevant except scopes and the throttle happens in
authentication, before your view or any permission class runs. Scopes stay a
per-view permission because *what a view needs* is a property of the view.

## Next

- [Django Ninja](django-ninja.md) — the same enforcement, through Ninja's
  own auth and throttle hooks.
- [Multi-tenancy](multi-tenancy.md) — how `request.tenant` gets resolved.
- [Testing](testing.md) — testing a DRF authentication/permission chain
  without spinning up real URL routing.
