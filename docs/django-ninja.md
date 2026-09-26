# Django Ninja API key authentication

```bash
pip install django-tenant-apikeys[ninja]
```

## Authenticating requests

```python
# myapp/api.py
from ninja import NinjaAPI

from django_tenant_apikeys.ninja import TenantAPIKeyAuth, TenantAPIKeyThrottle

api = NinjaAPI(auth=TenantAPIKeyAuth(), throttle=[TenantAPIKeyThrottle()])


@api.post("/deployments", auth=TenantAPIKeyAuth(scopes=["deployments:write"]))
def create_deployment(request):
    request.tenant.deployments.create(...)
    return {"status": "ok"}
```

`TenantAPIKeyAuth` is a Ninja `APIKeyHeader` implementation and a thin
adapter over the same `authenticate_key()` function the DRF backend uses, so
both frameworks enforce identical rules: an unknown, tampered, inactive, or
expired key never falls through as anonymous access, `allowed_ips` and
`TENANT_API_KEY_ALLOWED_ENVIRONMENTS` are enforced during authentication,
`record_usage()` runs on every success, and `request.tenant` is attached
(if the resolved model has a `tenant` attribute).

How failure surfaces:

- A key that fails to authenticate → `authenticate()` returns `None` and
  Ninja answers a generic 401.
- A valid key refused by a policy (environment, IP, tenant) or missing a
  required scope → `HttpError(403)` with a message.

That's the same 401/403 split the DRF backend makes. See
[Authentication](authentication.md#what-tenantapikeyauthenticationtenantapikeyauth-actually-check)
for the exact check order.

Multiple key models in one project? Subclass and set `model`, same as the
DRF class:

```python
class PartnerAPIKeyAuth(TenantAPIKeyAuth):
    model = PartnerAPIKey
```

`openapi_scheme = "apikey"` on the class is what makes Ninja's
auto-generated `/api/docs` show the `Authorization` header as an API-key
field in its interactive schema — it doesn't change runtime behavior.

## Scopes

Pass them to the auth instance; the key must have **all** of them:

```python
@api.get("/orders", auth=TenantAPIKeyAuth(scopes=["orders:read"]))
def list_orders(request):
    return request.tenant.orders.all()
```

For a check that depends on the request, call `request.auth.has_scope(...)`
yourself. See [Scopes](scopes.md).

## Rate limiting

`TenantAPIKeyThrottle` is a Ninja throttle (needs `django-ninja >= 1.2`).
Put it on the `NinjaAPI` or a router and it covers every operation beneath
it; Ninja answers 429 with `Retry-After`. See
[Rate limiting](rate-limiting.md).

## IP restrictions

Nothing to add: `allowed_ips` is enforced during authentication. See
[IP restrictions](ip-restrictions.md).

## Why `get_api_key_model()` instead of importing your model directly

`TenantAPIKeyAuth.get_model()` resolves the model via
`settings.TENANT_API_KEY_MODEL` by default, the same as the DRF class.
Either that or a direct import works, but going through the setting means
the same auth class keeps working if you ever rename the concrete model or
move it to a different app.

## Next

- [Django REST Framework](django-rest-framework.md) — the same core,
  through DRF's authentication, permission and throttle classes.
- [Scopes](scopes.md), [IP restrictions](ip-restrictions.md),
  [Rate limiting](rate-limiting.md) — the individual policies referenced
  above, in depth.
