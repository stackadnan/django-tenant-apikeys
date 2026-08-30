# Testing a custom DRF authentication backend with pytest-django

An authentication backend is a security boundary, not just a feature — a
bug in one doesn't just misbehave, it can silently let the wrong request
through. Testing one thoroughly looks different from testing a normal
view: you're less interested in the happy path and more interested in
proving every rejection path actually rejects. This page walks through how
[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
tests `TenantAPIKeyAuthentication` in `tests/test_authentication.py`, as a
worked example for testing your own custom DRF authentication class.

## Calling `authenticate()` directly instead of hitting a view

The tests don't spin up a URL and a view — they build a request and call
the authentication class directly:

```python
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

_factory = APIRequestFactory()

def build_request(auth_header: str | None = None) -> Request:
    extra = {"HTTP_AUTHORIZATION": auth_header} if auth_header is not None else {}
    return Request(_factory.get("/", **extra))
```

`APIRequestFactory` builds a bare Django `HttpRequest`; wrapping it in DRF's
`Request` is what makes `get_authorization_header()` and the rest of DRF's
request-parsing available. This skips routing, views, and any other
authentication/permission classes entirely — a failure can only mean the
authentication class itself is wrong, not something upstream of it.

## Standing in for an abstract model

`AbstractTenantAPIKey` is abstract — it can't be queried or migrated on
its own, so it can't be tested directly. The test suite defines two
concrete stand-ins in `tests/models.py`:

```python
class TenantAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(Tenant, related_name="api_keys", on_delete=models.CASCADE)

class UnlinkedAPIKey(AbstractTenantAPIKey):
    """No tenant relation at all."""
```

Two concrete models, not one, because there are two branches to prove:
`TenantAPIKeyAuthentication` attaches `request.tenant` *if* the concrete
model has a `tenant` attribute, and does nothing otherwise. Testing only
`TenantAPIKey` would leave that `hasattr()` branch completely unexercised.
If you're testing your own abstract base model, the same pattern applies:
a small `tests/models.py` (or `testapp/models.py`) with the concrete
model(s) your test suite actually needs, registered via
`DJANGO_SETTINGS_MODULE = "tests.settings"` in `pyproject.toml`'s
`[tool.pytest.ini_options]`.

## Fixtures that mirror the API's own return shape

```python
@pytest.fixture
def api_key(tenant: Tenant) -> tuple[TenantAPIKey, str]:
    return TenantAPIKey.generate_key(name="test key", tenant=tenant, scopes=["*"])
```

The fixture returns exactly what `generate_key()` returns — `(instance,
raw_key)` — rather than unpacking it into two separate fixtures. Every
test that needs a key destructures the tuple itself
(`instance, raw_key = api_key`), which keeps the fixture reusable for
tests that need the instance, the raw key, or both.

`pytestmark = pytest.mark.django_db` at module level means every test
function gets database access without repeating the marker on each one.

## Enumerate the rejection paths, not just the happy path

The bulk of the test class is failure modes, each isolated to one cause:

- no `Authorization` header at all → `None` (not an error — just "didn't
  attempt to authenticate," so other schemes get a chance)
- wrong scheme (`Bearer ...`) → also `None`, same reasoning
- `Api-Key` with nothing after it → `AuthenticationFailed`
- a key with a space in it → `AuthenticationFailed`
- non-UTF-8 bytes in the header → `AuthenticationFailed`, not a raw
  `UnicodeDecodeError` leaking out
- an unrecognized prefix → `AuthenticationFailed("Invalid API key.")`
- a real prefix with a tampered/wrong secret → the same generic
  `"Invalid API key."` message as an unrecognized prefix (deliberately —
  distinguishing "prefix exists but secret is wrong" from "prefix doesn't
  exist" in the error message would leak which prefixes are valid)
- `is_active=False` → `"deactivated"`, a distinct message from invalid
- `expires_at` in the past → `"expired"`, distinct again
- `expires_at=None` → succeeds, proving "no expiry" isn't accidentally
  treated as "already expired"

Each of these is one test, one assertion, one cause — when one fails later
after a refactor, the test name tells you exactly which check broke
without needing to read the traceback.

## Testing side effects, not just the return value

`record_usage()` doesn't show up in `authenticate()`'s return value at
all, so proving it actually ran means checking the database after the
fact:

```python
def test_successful_authentication_records_usage(self, tenant, api_key):
    instance, raw_key = api_key
    assert instance.last_used_at is None

    request = build_request(f"Api-Key {raw_key}")
    TenantAPIKeyAuthentication().authenticate(request)

    instance.refresh_from_db()
    assert instance.last_used_at is not None
```

`refresh_from_db()` matters here — `record_usage()` updates the row via a
targeted `.update()` call, not `instance.save()`, so the in-memory
`instance` used to build the request wouldn't reflect the change without
re-fetching. The matching negative test
(`test_failed_authentication_does_not_record_usage`) checks the same field
stays `None` when authentication fails, proving the two branches don't
both write.

## Testing a lower-level method directly

`authenticate_credentials()` is what `authenticate()` delegates to after
parsing the header. Testing it directly, without going through header
parsing at all, isolates one more layer:

```python
def test_without_request_skips_tenant_attachment(self, api_key):
    instance, raw_key = api_key
    user, returned_key = TenantAPIKeyAuthentication().authenticate_credentials(raw_key)
    assert user is None
    assert returned_key.pk == instance.pk
```

This also documents a real API detail: `authenticate_credentials()`'s
`request` parameter is optional, and tenant attachment is simply skipped
when it's `None` — useful if you ever want to verify a raw key outside of
a request/response cycle at all (a management command, say).

## Testing configuration errors with `override_settings`

`get_api_key_model()` reads `settings.TENANT_API_KEY_MODEL` and raises
`ImproperlyConfigured` for three distinct misconfigurations — unset, not a
dotted path, or pointing at a model that doesn't exist:

```python
def test_raises_when_unset(self) -> None:
    with override_settings(TENANT_API_KEY_MODEL=None):
        with pytest.raises(ImproperlyConfigured, match="not set"):
            get_api_key_model()
```

`override_settings` as a context manager keeps the bad setting scoped to
one test — it's restored automatically on exit, so there's no risk of one
test's broken setting leaking into the next.

## Try it

- Full test suite: [`tests/test_authentication.py`](https://github.com/stackadnan/django-tenant-apikeys/blob/main/tests/test_authentication.py)
- Full API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- See also: [Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication)
