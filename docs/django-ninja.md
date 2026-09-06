# Django Ninja API key authentication

```bash
pip install django-tenant-apikeys[ninja]
```

## Authenticating requests

```python
# myapp/api.py
from ninja import NinjaAPI

from django_tenant_apikeys.ninja import TenantAPIKeyAuth

api = NinjaAPI(auth=TenantAPIKeyAuth())


@api.post("/deployments")
def create_deployment(request):
    if not request.auth.has_scope("deployments:write"):
        return 403, {"detail": "missing required scope"}
    request.tenant.deployments.create(...)
    return {"status": "ok"}
```

`TenantAPIKeyAuth` is a Ninja `APIKeyHeader` implementation. It mirrors
`TenantAPIKeyAuthentication`'s rejection rules exactly — an unknown,
tampered, inactive, or expired key never falls through as anonymous access
— and the same success behavior: `record_usage()` runs on every success,
and `request.tenant` is attached the same way (if the resolved model has a
`tenant` attribute).

The one real difference is in how failure surfaces. Ninja doesn't give
`authenticate()` DRF's `AuthenticationFailed`-with-a-specific-message
mechanism — every rejection reason here just returns `None`, and Ninja
turns that into a generic 401 on its own. See
[Authentication](authentication.md#what-tenantapikeyauthenticationtenantapikeyauth-actually-check)
for the exact check order both integrations share.

Multiple key models in one project? Subclass and set `model`, same as the
DRF class:

```python
class PartnerAPIKeyAuth(TenantAPIKeyAuth):
    model = PartnerAPIKey
```

`openapi_scheme = "apikey"` on the class is what makes Ninja's
auto-generated `/api/docs` show the `Authorization` header as an API-key
field in its interactive schema — it doesn't change runtime behavior.

## Scopes, IP restrictions, and rate limiting: all inline

Ninja has no `permission_classes`-style system to hook policy checks into.
Every check beyond "is this a valid key" — [scopes](scopes.md),
[IP restrictions](ip-restrictions.md), [rate limiting](rate-limiting.md) —
is an ordinary `if` statement in your view, using the same shared functions
DRF's permission classes call internally:

```python
from django.http import JsonResponse

from django_tenant_apikeys.ip import get_client_ip
from django_tenant_apikeys.ratelimit import check_rate_limit


@api.get("/orders")
def list_orders(request):
    if not request.auth.is_ip_allowed(get_client_ip(request)):
        return JsonResponse({"detail": "IP not allowed"}, status=403)

    result = check_rate_limit(request.auth)
    if not result.allowed:
        return JsonResponse(
            {"detail": "rate limit exceeded", "retry_after": result.retry_after},
            status=429,
        )

    if not request.auth.has_scope("orders:read"):
        return JsonResponse({"detail": "missing required scope"}, status=403)

    return request.tenant.orders.all()
```

Returning a real `JsonResponse` (rather than Ninja's `(status, dict)` tuple
shorthand) avoids needing to declare every possible status code up front
via `@api.get(..., response={200: ..., 403: ..., 429: ...})` — Ninja passes
an `HttpResponseBase` straight through unmodified, so this works regardless
of how the operation's `response` schema is configured.

If several endpoints repeat the same checks, wrapping this pattern in your
own decorator is reasonable. There isn't one built into the package, since
it would be Ninja-specific and the core (`is_ip_allowed()`,
`check_rate_limit()`, `has_scope()`) stays framework-agnostic on purpose —
the same reasoning `TenantAPIKeyAuth` itself follows.

## Why `get_api_key_model()` instead of importing your model directly

`TenantAPIKeyAuth.get_model()` resolves the model via
`settings.TENANT_API_KEY_MODEL` by default, the same as the DRF class.
Either that or a direct import works, but going through the setting means
the same auth class keeps working if you ever rename the concrete model or
move it to a different app.

## Next

- [Django REST Framework](django-rest-framework.md) — the same core, with a
  permission-class chain instead of inline checks.
- [Scopes](scopes.md), [IP restrictions](ip-restrictions.md),
  [Rate limiting](rate-limiting.md) — the individual policies referenced
  above, in depth.
