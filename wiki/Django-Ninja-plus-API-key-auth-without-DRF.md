# Django Ninja + API key auth without DRF

[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
doesn't ship a dedicated Django Ninja module, and that's a deliberate
choice, not a gap: the model layer (`get_api_key_model()`, `verify_key()`,
`has_scope()`, `record_usage()`) has zero DRF imports, so wiring it into
Ninja is a ~30-line auth class using the same methods DRF's
`TenantAPIKeyAuthentication` calls internally. This page expands the
recipe from the README with the reasoning behind each part.

## The auth class

```python
# myapp/auth.py
from ninja.security import APIKeyHeader

from django_tenant_apikeys.models import get_api_key_model


class TenantAPIKeyAuth(APIKeyHeader):
    param_name = "Authorization"
    openapi_scheme = "apikey"

    def authenticate(self, request, key):
        if not key or not key.startswith("Api-Key "):
            return None
        raw_key = key.removeprefix("Api-Key ").strip()

        model = get_api_key_model()
        key_prefix, _sep, _secret = raw_key.partition(".")
        try:
            api_key = model.objects.get(prefix=key_prefix)
        except model.DoesNotExist:
            return None

        if not api_key.verify_key(raw_key):
            return None
        if not api_key.is_active or api_key.is_expired:
            return None

        api_key.record_usage()
        if hasattr(api_key, "tenant"):
            request.tenant = api_key.tenant
        return api_key
```

## Where this differs from the DRF backend

Ninja's `APIKeyHeader.authenticate()` has a different contract than DRF's
`BaseAuthentication.authenticate()`, and the recipe follows Ninja's rules,
not DRF's:

- **Return value, not a tuple.** DRF's authentication classes return
  `(user, auth)` or raise `AuthenticationFailed`. Ninja's just returns the
  authenticated object (here, the API key instance) on success, or `None`
  on failure — Ninja turns `None` into a generic 401 itself.
- **No differentiated error messages.** DRF's version raises distinct
  `AuthenticationFailed("Invalid API key.")`,
  `"This API key has been deactivated."`, `"This API key has expired."`
  depending on which check failed. Ninja's contract doesn't give you that
  same hook — every failure here just falls through to `return None` and
  becomes the same generic 401. If you want distinct error bodies, you'd
  need to raise Ninja's `HttpError` yourself instead of returning `None`,
  trading the simplicity above for more detail.
- **`request.auth`, not `request.auth` via DRF's request wrapper.** Ninja
  attaches whatever `authenticate()` returns to `request.auth` the same
  way, so `request.auth.has_scope(...)` works identically in a view body —
  but there's no Ninja equivalent of DRF's `permission_classes`, so scope
  enforcement is manual per endpoint rather than declarative.

## Enforcing scopes without `HasAPIKeyScope`

There's no Ninja counterpart to DRF's `HasAPIKeyScope` permission class —
Ninja doesn't have a permission-class concept in the same shape. You check
`has_scope()` directly in the view body and return the response yourself:

```python
# myapp/api.py
from ninja import NinjaAPI
from myapp.auth import TenantAPIKeyAuth

api = NinjaAPI(auth=TenantAPIKeyAuth())


@api.post("/deployments")
def create_deployment(request):
    if not request.auth.has_scope("deployments:write"):
        return 403, {"detail": "missing required scope"}
    request.tenant.deployments.create(...)
    return {"status": "ok"}
```

If you have several endpoints that all need the same scope check, a small
decorator wrapping this pattern is reasonable — there just isn't one built
into the package, since it would be Ninja-specific and the core stays
framework-agnostic on purpose.

## OpenAPI docs

`openapi_scheme = "apikey"` on the auth class is what makes Ninja's
auto-generated `/api/docs` show the `Authorization` header as an API-key
field in its interactive schema, rather than leaving callers to guess the
header format from source. It doesn't change runtime behaviour at all —
only the generated schema.

## Why `get_api_key_model()` instead of importing your model directly

The recipe resolves the model via `get_api_key_model()` (which reads
`settings.TENANT_API_KEY_MODEL`) instead of `from myapp.models import
OrganizationAPIKey`. Either works, but going through the setting means the
same `auth.py` keeps working if you ever rename the concrete model or move
it to a different app — same reason the DRF backend does it this way.

## Try it

- Full quickstart and API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working end-to-end project (uses DRF, but every method called above works identically from Ninja): [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
- See also: [Scoping API keys per tenant in Django REST Framework](https://github.com/stackadnan/django-tenant-apikeys/wiki/Scoping-API-keys-per-tenant-in-Django-REST-Framework) — the same `has_scope()` design, from the DRF side
