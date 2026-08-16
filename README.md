# django-tenant-apikeys

Pluggable multi-tenant API key authentication for Django, with first-class
support for [Django REST Framework](https://www.django-rest-framework.org/)
and [Django Ninja](https://django-ninja.dev/).

- **Bring your own tenant model.** Subclass one abstract model and point it
  at whatever `Organization`, `Account`, or `Workspace` model your project
  already has.
- **Secure by construction.** Keys are generated with `secrets`, stored only
  as a SHA-256 hash, and verified with a constant-time comparison. The raw
  key is shown to the caller exactly once, at creation time, and is not
  recoverable afterwards — not even by you.
- **Scope-based permissions.** Grant keys fine-grained scopes
  (`"orders:read"`), namespaced wildcards (`"orders:*"`), or full access
  (`"*"`).
- **Framework-agnostic core.** The model and its methods don't depend on DRF
  or Ninja at all — `authentication.py` and `permissions.py` are thin,
  optional adapters on top of it.

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [How keys work](#how-keys-work)
- [Django REST Framework integration](#django-rest-framework-integration)
- [Django Ninja integration](#django-ninja-integration)
- [Scopes](#scopes)
- [Admin integration](#admin-integration)
- [Settings reference](#settings-reference)
- [API reference](#api-reference)
- [Security notes](#security-notes)
- [Running the tests](#running-the-tests)
- [Contributing](#contributing)
- [License](#license)

## Installation

```bash
pip install django-tenant-apikeys[drf]
```

Extras are additive and optional:

| Extra  | Installs                    | Needed for                          |
|--------|------------------------------|--------------------------------------|
| `drf`  | `djangorestframework>=3.14` | `TenantAPIKeyAuthentication`, `HasAPIKeyScope` |
| `ninja`| `django-ninja>=1.0`         | The Ninja recipe below              |

Installing neither extra still gives you `AbstractTenantAPIKey`,
`generate_api_key`, `hash_key`, and `get_api_key_model` — everything needed
to build your own integration.

## Quick start

### 1. Define your concrete key model

`AbstractTenantAPIKey` is abstract on purpose: every project's tenant model
is different, so you link the two yourself.

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

The `tenant` field name is significant: both `TenantAPIKeyAuthentication`
and the Django Ninja recipe below look for an attribute literally named
`tenant` and, if present, attach it to the request as `request.tenant`. Call
it something else and that convenience is simply skipped — everything else
still works.

### 2. Configure settings

```python
# settings.py
INSTALLED_APPS = [
    ...
    "django_tenant_apikeys",  # only needed for the admin integration
    "rest_framework",         # if using the DRF integration
    "myapp",
]

TENANT_API_KEY_MODEL = "myapp.OrganizationAPIKey"
```

### 3. Migrate

```bash
python manage.py makemigrations myapp
python manage.py migrate
```

### 4. Issue a key

```python
from myapp.models import Organization, OrganizationAPIKey

org = Organization.objects.get(name="Acme Inc.")

instance, raw_key = OrganizationAPIKey.generate_key(
    name="CI deploy key",
    tenant=org,
    scopes=["deployments:write"],
)

print(raw_key)
# tak_live_3f9a2c1d.k7pQ2m1vXyN0...  <- show this to the user now; it is
#                                        never stored and can't be shown again
```

`instance` is already saved. Only `instance.hashed_key` (its SHA-256 digest)
is persisted — capture `raw_key` here or it's gone for good.

## How keys work

A generated key looks like:

```
tak_live_3f9a2c1d.Xk7pQ2m1vYzN0hT8sR4uWjLdEaFbGcHiJk
└──┬──┘ └───┬────┘ └────────────────┬────────────────┘
 prefix  secret_prefix              secret
└──────────┬──────────┘
   stored in `prefix` column (indexed, unique, cleartext)
```

* `generate_api_key(prefix="tak")` returns `(full_key, key_prefix, hashed_key)`.
* `key_prefix` (`tak_live_3f9a2c1d`) is stored in cleartext in the `prefix`
  column. It carries no meaningful secrecy on its own — it exists purely so
  a request can be matched to a row with a single indexed `WHERE prefix = ?`
  lookup, instead of hashing and comparing against every row in the table.
* `hashed_key` is `sha256(full_key)`, stored in the `hashed_key` column.
* The **only** place `full_key` (the actual secret) ever exists is the
  return value of `generate_api_key()` / `AbstractTenantAPIKey.generate_key()`.
  Nothing in this library writes it to the database, logs, or the admin.

## Django REST Framework integration

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

Or wire it globally:

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "django_tenant_apikeys.authentication.TenantAPIKeyAuthentication",
    ],
}
```

Callers authenticate with:

```
Authorization: Api-Key tak_live_3f9a2c1d.Xk7pQ2m1vYzN0hT8sR4uWjLdEaFbGcHiJk
```

`TenantAPIKeyAuthentication.authenticate()`:

* Returns `None` if there's no `Authorization` header, or it doesn't use the
  `Api-Key` scheme — deferring to any other configured authenticator.
* Raises `rest_framework.exceptions.AuthenticationFailed` (HTTP 401) if the
  scheme matches but the key is missing, malformed, unknown, tampered with,
  inactive, or expired.
* On success, returns `(None, api_key_instance)`. The first element is
  `None` rather than a Django `User`, because an API key authenticates a
  tenant/integration, not a human — `request.user` stays anonymous and
  `request.auth` holds the key.

Multiple key models in one project? Subclass instead of relying on the
setting:

```python
class PartnerAPIKeyAuthentication(TenantAPIKeyAuthentication):
    model = PartnerAPIKey
```

### Scoped permissions

`HasAPIKeyScope` reads a `required_scopes` list off the view and checks it
against `request.auth.has_scope(...)`:

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["orders:read", "orders:write"]  # ALL must be granted
```

A view without a `required_scopes` attribute (or an empty one) is open to
any successfully authenticated key.

## Django Ninja integration

There's no dedicated Ninja module shipped in this package — Ninja's
[`APIKeyHeader`](https://django-ninja.dev/guides/authentication/) auth
classes are simple enough that one lives comfortably in your own project,
built directly on the same `AbstractTenantAPIKey` methods DRF uses:

```python
# myapp/auth.py
from django.utils import timezone
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

        if hasattr(api_key, "tenant"):
            request.tenant = api_key.tenant
        return api_key
```

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

`get_api_key_model()` (and every method on the model) works identically
here — only the HTTP-layer glue differs between frameworks.

## Scopes

`scopes` is a plain JSON list of strings. `has_scope()` supports three
forms, checked in this order:

```python
key.scopes = ["orders:read"]
key.has_scope("orders:read")   # True  (exact match)
key.has_scope("orders:write")  # False

key.scopes = ["*"]
key.has_scope("anything:at:all")  # True (global wildcard)

key.scopes = ["orders:*"]
key.has_scope("orders:read")   # True  (namespaced wildcard)
key.has_scope("orders:write")  # True
key.has_scope("billing:read")  # False (different namespace)
key.has_scope("orders")        # False (wildcard requires the "orders:" prefix)
```

## Admin integration

```python
# myapp/admin.py
from django.contrib import admin
from django_tenant_apikeys.admin import TenantAPIKeyAdmin
from myapp.models import OrganizationAPIKey


@admin.register(OrganizationAPIKey)
class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
    pass
```

`TenantAPIKeyAdmin`:

* Sets `readonly_fields = ("prefix", "hashed_key", "created_at")`, so the
  hash can be inspected (e.g. to confirm a key exists) but never edited.
* Generates the prefix/hash pair itself on creation and shows the one-time
  raw key in a dismissible admin message — it is never written to a form
  field, so it can't round-trip back into the database or appear in the
  change view afterwards.
* Lists a `masked_key` column (`tak_live_3f9a2c1d.••••••••••••`) instead of
  any secret material, so list views stay safe to screen-share.

Add your own `list_display`, `fieldsets`, etc. as usual — `TenantAPIKeyAdmin`
is a normal `ModelAdmin` subclass.

## Settings reference

| Setting                | Required | Description                                                              |
|-------------------------|:--------:|---------------------------------------------------------------------------|
| `TENANT_API_KEY_MODEL`  | Yes\*    | `"app_label.ModelName"` string pointing at your concrete key model. Read by `get_api_key_model()` / `TenantAPIKeyAuthentication.get_model()`. |

\* Only required if you use the default model resolution. Subclassing
`TenantAPIKeyAuthentication` with an explicit `model` attribute, or calling
`get_api_key_model()` never at all, makes it optional.

## API reference

### `django_tenant_apikeys.models`

* `generate_api_key(prefix: str = "tak") -> tuple[str, str, str]` — returns
  `(full_key, key_prefix, hashed_key)`.
* `hash_key(raw_key: str) -> str` — SHA-256 hex digest of `raw_key`.
* `get_api_key_model() -> type[AbstractTenantAPIKey]` — resolves
  `settings.TENANT_API_KEY_MODEL`; raises `ImproperlyConfigured` if unset or
  invalid.
* `AbstractTenantAPIKey` — abstract model with fields `name`, `prefix`,
  `hashed_key`, `scopes`, `is_active`, `created_at`, `expires_at`, and:
  * `generate_key(cls, *, prefix="tak", **kwargs) -> tuple[instance, raw_key]`
  * `verify_key(self, raw_key: str) -> bool`
  * `has_scope(self, required_scope: str) -> bool`
  * `is_expired` / `is_valid` properties
* `TenantAPIKeyManager` (`.objects`) — adds `get_from_key(raw_key)` (indexed
  lookup by prefix; still call `verify_key()` on the result) and
  `get_usable_keys()` (active and unexpired).

### `django_tenant_apikeys.authentication` (requires `[drf]`)

* `TenantAPIKeyAuthentication` — DRF `BaseAuthentication` subclass described
  above.

### `django_tenant_apikeys.permissions` (requires `[drf]`)

* `HasAPIKeyScope` — DRF `BasePermission` subclass described above.

### `django_tenant_apikeys.admin`

* `TenantAPIKeyAdmin` — `ModelAdmin` base class described above.

## Security notes

* **Hashing is unsalted SHA-256, deliberately.** The input already carries
  256 bits of entropy from `secrets.token_urlsafe`, so it isn't vulnerable
  to dictionary or rainbow-table attacks the way a low-entropy user
  password would be. Salting a value that's already high-entropy adds
  operational cost without a corresponding security gain here.
* **Comparison is constant-time.** `verify_key()` uses
  `secrets.compare_digest`, not `==`, so response timing can't be used to
  narrow down a guessed key byte by byte.
* **The raw key is never persisted, logged, or displayed twice.** Store it
  yourself (e.g. show it once in your UI, or hand it back from an API
  response) the moment `generate_key()` returns it — this library cannot
  recover it for you afterwards.
* **Deactivate, don't just delete.** Setting `is_active=False` revokes a key
  immediately while preserving an audit trail; `TenantAPIKeyAuthentication`
  rejects inactive keys with the same `AuthenticationFailed` used for
  invalid ones, so revoked keys don't leak information about their own
  existence.

## Running the tests

```bash
git clone https://github.com/stackadnan/django-tenant-apikeys
cd django-tenant-apikeys
pip install -e ".[dev]"
pytest --cov=django_tenant_apikeys --cov-report=term-missing
```

The suite runs against an in-memory SQLite database defined in
`tests/settings.py`, with `tests/models.py` providing concrete subclasses of
`AbstractTenantAPIKey` (`AbstractTenantAPIKey` itself is abstract and can't
be instantiated or queried directly).

## Contributing

Issues and pull requests are welcome. Please include tests for any behavior
change, and run `ruff check .`, `mypy django_tenant_apikeys`, and `pytest`
before opening a PR — these are exactly what CI runs on every push.

## License

[MIT](LICENSE)
