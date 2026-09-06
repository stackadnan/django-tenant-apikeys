# Testing

## Running the project's own test suite

```bash
git clone https://github.com/stackadnan/django-tenant-apikeys
cd django-tenant-apikeys
pip install -e ".[dev]"
pytest --cov=django_tenant_apikeys --cov-report=term-missing
```

The suite runs against an in-memory SQLite database (`tests/settings.py`),
with concrete subclasses of `AbstractTenantAPIKey` defined in
`tests/models.py` — the abstract model itself can't be instantiated or
queried directly, so something concrete has to stand in for it. CI also
runs the same suite against PostgreSQL
(`pytest --ds=tests.settings_postgres`), and against the full supported
Python/Django matrix — see
[`.github/workflows/test.yml`](https://github.com/stackadnan/django-tenant-apikeys/blob/main/.github/workflows/test.yml).

These are the exact three commands CI runs on every push and PR:

```bash
pytest --cov=django_tenant_apikeys --cov-report=term-missing
ruff check .
mypy django_tenant_apikeys
```

Coverage is enforced at 100% (`fail_under = 100` in `pyproject.toml`). If
you're contributing a change that adds a branch, it needs a test that
exercises it — no line is excluded without a `# pragma: no cover` and a
reason in a comment.

## Testing your own authentication/permission setup

An authentication backend is a security boundary, not just a feature — a
bug in one doesn't just misbehave, it can silently let the wrong request
through. Testing one thoroughly looks different from testing a normal view:
you're less interested in the happy path and more interested in proving
every rejection path actually rejects. The patterns below come straight
from how this package tests itself, in
[`tests/test_authentication.py`](https://github.com/stackadnan/django-tenant-apikeys/blob/main/tests/test_authentication.py)
and
[`tests/test_drf_policy_integration.py`](https://github.com/stackadnan/django-tenant-apikeys/blob/main/tests/test_drf_policy_integration.py).

### Calling `authenticate()` directly, without routing

```python
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

_factory = APIRequestFactory()

def build_request(auth_header: str | None = None) -> Request:
    extra = {"HTTP_AUTHORIZATION": auth_header} if auth_header is not None else {}
    return Request(_factory.get("/", **extra))
```

`APIRequestFactory` builds a bare `HttpRequest`; wrapping it in DRF's
`Request` makes `get_authorization_header()` and the rest of DRF's
request-parsing available. This skips routing and views entirely — a
failure can only mean the authentication class itself is wrong, not
something upstream of it.

### Testing a full permission chain without URL routing

For a policy chain (IP restriction, rate limit, scope — see
[How the policies interact](django-rest-framework.md#how-the-policies-interact)),
`APIView.as_view()` can be called directly on a built request, without
registering a URL at all:

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAllowedIP, WithinRateLimit, HasAPIKeyScope]
    required_scopes = ["orders:read"]

    def get(self, request):
        return Response({"ok": True})


def call(raw_key, remote_addr="203.0.113.10"):
    request = _factory.get("/", HTTP_AUTHORIZATION=f"Api-Key {raw_key}", REMOTE_ADDR=remote_addr)
    return OrdersView.as_view()(request)
```

This exercises DRF's actual `authenticate()` → `check_permissions()` flow —
the real dispatch order — while still avoiding `urls.py` and a test client.

### Testing a Django Ninja view the same way

`ninja.testing.TestClient` runs a real `NinjaAPI` operation, including
authentication and whatever inline checks the view performs, without a
running server:

```python
from ninja.testing import TestClient

client = TestClient(api)
response = client.get("/orders", headers={"Authorization": f"Api-Key {raw_key}"})
response.status_code
```

### Standing in for an abstract model

`AbstractTenantAPIKey` can't be tested directly. Define a small concrete
model in your own test suite — this package's is `tests/models.py`:

```python
class TenantAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(Tenant, related_name="api_keys", on_delete=models.CASCADE)
```

If you're testing behavior that depends on whether a `tenant` relation
exists at all (like `request.tenant` attachment), define a second concrete
model with no `tenant` field — this package's `UnlinkedAPIKey` exists
specifically to prove `request.tenant` is never set when there's nothing
to attach.

### Enumerate rejection paths, not just the happy path

A representative (not exhaustive) list of what's worth a dedicated test,
one assertion each, one cause each:

- no `Authorization` header → not an error, `None` (so another authenticator
  gets a turn)
- wrong scheme → also `None`
- an unrecognized prefix → rejected
- a real prefix, tampered/wrong secret → rejected, with the **same**
  message as an unrecognized prefix (see [Security](security.md))
- `is_active=False` → rejected, distinct message from an invalid key
- `expires_at` in the past → rejected, distinct message again
- `expires_at=None` → succeeds — proves "no expiry" isn't accidentally
  treated as "already expired"
- IP outside `allowed_ips` → rejected, and never reaches the rate limiter
  or scope check
- rate limit exceeded → 429, and never reaches the scope check
- missing required scope → rejected, only after IP and rate limit pass

### Testing side effects, not just return values

`record_usage()` doesn't show up in `authenticate()`'s return value — check
the database after the fact, and `refresh_from_db()` first, since it writes
via a targeted `.update()` call rather than `instance.save()`:

```python
def test_successful_authentication_records_usage(tenant, api_key):
    instance, raw_key = api_key
    request = build_request(f"Api-Key {raw_key}")
    TenantAPIKeyAuthentication().authenticate(request)

    instance.refresh_from_db()
    assert instance.last_used_at is not None
```

### Testing configuration errors with `override_settings`

```python
def test_raises_when_unset() -> None:
    with override_settings(TENANT_API_KEY_MODEL=None):
        with pytest.raises(ImproperlyConfigured, match="not set"):
            get_api_key_model()
```

Scoped to one test — restored automatically on exit, so a broken setting in
one test can't leak into the next.

## Next

- [Security](security.md) — what every one of these rejection paths is
  actually defending against.
- [API reference](api-reference.md) — the full signature list for
  everything referenced above.
