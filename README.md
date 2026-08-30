# django-tenant-apikeys

[![PyPI version](https://img.shields.io/pypi/v/django-tenant-apikeys.svg)](https://pypi.org/project/django-tenant-apikeys/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-tenant-apikeys.svg)](https://pypi.org/project/django-tenant-apikeys/)
[![Tests](https://github.com/stackadnan/django-tenant-apikeys/actions/workflows/test.yml/badge.svg)](https://github.com/stackadnan/django-tenant-apikeys/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/pypi/l/django-tenant-apikeys.svg)](LICENSE)
[![Latest on Django Packages](https://img.shields.io/badge/Django_Packages-django--tenant--apikeys-8c3c26.svg)](https://djangopackages.org/packages/p/django-tenant-apikeys/)

Multi-tenant API key authentication for Django. Issue a key per tenant, hash
it before it ever touches the database, and gate access with scopes instead
of an all-or-nothing flag. Works with Django REST Framework out of the box,
and with Django Ninja via a short recipe below.

If you've ever built API key auth for a SaaS product, you've probably
written this same code three or four times: generate a random token, hash
it, store the hash, look it up on every request, and figure out how to show
the raw key to the user exactly once. `django-tenant-apikeys` is that code,
written once, tested properly, and wired up to whatever tenant model your
project already has.

- **Bring your own tenant model.** Subclass one abstract model and point it
  at whatever `Organization`, `Account`, or `Workspace` model you already
  have. No schema opinions beyond that.
- **Nothing sensitive is stored.** Keys are generated with `secrets`, kept
  only as a SHA-256 hash, and checked with a constant-time comparison. The
  raw key exists for one moment — right after creation — and then it's gone,
  even from us.
- **Scopes, not just on/off.** Grant a key `"orders:read"`, a whole
  namespace with `"orders:*"`, or everything with `"*"`.
- **Small, framework-agnostic core.** The model doesn't know DRF or Ninja
  exist. `authentication.py` and `permissions.py` are optional adapters on
  top of it, so you can build your own integration if neither fits.

**Want to see it run before reading further?**
[`examples/simple_saas/`](examples/simple_saas/) is a minimal Django + DRF
project with the whole flow wired up — clone the repo, `pip install -r
requirements.txt`, `python manage.py migrate && python manage.py
create_demo_key`, and you have a real tenant-scoped API key and a working
`curl` command in about a minute.

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Example project](#example-project)
- [How keys work](#how-keys-work)
- [Django REST Framework integration](#django-rest-framework-integration)
- [Django Ninja integration](#django-ninja-integration)
- [Scopes](#scopes)
- [Admin integration](#admin-integration)
- [How this compares to other options](#how-this-compares-to-other-options)
- [Settings reference](#settings-reference)
- [API reference](#api-reference)
- [Security notes](#security-notes)
- [FAQ](#faq)
- [Running the tests](#running-the-tests)
- [Contributing](#contributing)
- [License](#license)

## Installation

```bash
pip install django-tenant-apikeys[drf]
```

Extras are additive:

| Extra   | Installs                    | Needed for                                     |
|---------|------------------------------|-------------------------------------------------|
| `drf`   | `djangorestframework>=3.14` | `TenantAPIKeyAuthentication`, `HasAPIKeyScope`   |
| `ninja` | `django-ninja>=1.0`          | The Ninja recipe below                          |

You don't have to pick either. Installing the bare package still gives you
`AbstractTenantAPIKey`, `generate_api_key`, `hash_key`, and
`get_api_key_model` — enough to wire up your own auth layer if you're not
on DRF or Ninja.

## Quick start

### 1. Define your concrete key model

`AbstractTenantAPIKey` ships abstract on purpose. Every project's tenant
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

That field has to be named `tenant`. Both `TenantAPIKeyAuthentication` and
the Ninja recipe below check for an attribute with that exact name and, if
it exists, attach it to the request as `request.tenant`. Name it something
else and you just lose that one convenience — everything else still works
fine.

### 2. Point Django at it

```python
# settings.py
INSTALLED_APPS = [
    ...
    "django_tenant_apikeys",  # only needed for the admin integration
    "rest_framework",         # if you're using the DRF integration
    "myapp",
]

TENANT_API_KEY_MODEL = "myapp.OrganizationAPIKey"
```

### 3. Migrate as usual

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
# tak_live_3f9a2c1d.k7pQ2m1vXyN0...
# show this to the user right now — it's never stored, and can't be
# shown again once you look away
```

`instance` is already saved by the time you get it back. What lands in the
database is `instance.hashed_key`, the SHA-256 digest — not `raw_key`. Copy
the raw key out of that print statement and put it wherever your app needs
to hand it to the user, because this is the only chance you get.

## Example project

[`examples/simple_saas/`](examples/simple_saas/) runs the steps above as an
actual project instead of a code snippet: an `Organization` tenant, an
`OrganizationAPIKey`, and one protected view (`WhoAmIView`) that reports back
whatever the library resolved from the request — which tenant, which key,
which scopes.

```bash
cd examples/simple_saas
pip install -r requirements.txt
python manage.py migrate
python manage.py create_demo_key   # creates a tenant, issues a key, prints a curl command
python manage.py runserver         # in another terminal
```

Run the `curl` command it prints and you'll get the tenant back in the
response. Its own [README](examples/simple_saas/README.md) also walks
through the failure cases — no header, a garbage key, the wrong scope — so
you can see what each one actually returns.

## How keys work

A generated key looks like this:

```
tak_live_3f9a2c1d.Xk7pQ2m1vYzN0hT8sR4uWjLdEaFbGcHiJk
└──┬──┘ └───┬────┘ └────────────────┬────────────────┘
 prefix  secret_prefix              secret
└──────────┬──────────┘
   stored in `prefix` column (indexed, unique, cleartext)
```

`generate_api_key(prefix="tak")` builds that and returns
`(full_key, key_prefix, hashed_key)`.

The part before the dot — `tak_live_3f9a2c1d` — is stored in the `prefix`
column, in plain text, and it's fine that it is. It doesn't carry enough
entropy to matter on its own; its only job is letting a lookup hit a unique
index instead of hashing every row in the table on every request.

The part after the dot is the actual secret. It never gets written down
anywhere except as `sha256(full_key)`, in the `hashed_key` column. The one
and only place the full, usable key exists is the return value of
`generate_api_key()` — logs, the admin, the database, none of them ever see
it.

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

Or skip the per-view wiring and set it globally:

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

A few things worth knowing about what `authenticate()` actually does:

- No `Authorization` header, or one that isn't using the `Api-Key` scheme?
  It returns `None` and gets out of the way, so any other authenticator you
  have configured gets a turn.
- Scheme matches but the key is missing, malformed, unrecognized, tampered
  with, deactivated, or expired? It raises `AuthenticationFailed` — a plain
  401, same as DRF's built-in authenticators.
- On success it returns `(None, api_key_instance)`. That `None` where a
  Django `User` would normally sit is intentional — an API key authenticates
  an integration, not a person, so `request.user` stays anonymous and
  `request.auth` is where the key instance actually lives.

Running more than one kind of key in the same project? Subclass instead of
juggling settings:

```python
class PartnerAPIKeyAuthentication(TenantAPIKeyAuthentication):
    model = PartnerAPIKey
```

### Scoped permissions

`HasAPIKeyScope` reads `required_scopes` off the view and checks each entry
against `request.auth.has_scope(...)`:

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["orders:read", "orders:write"]  # all of these, not any
```

No `required_scopes` on the view, or an empty list? Then any authenticated
key gets in — the check is opt-in per view.

## Django Ninja integration

There's no dedicated Ninja module in this package, and honestly there
doesn't need to be — Ninja's
[`APIKeyHeader`](https://django-ninja.dev/guides/authentication/) is small
enough to write directly against the same model methods DRF uses:

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

`get_api_key_model()`, `verify_key()`, `has_scope()` — all of it works the
same regardless of which framework is calling it. Only the header-parsing
glue changes.

## Scopes

`scopes` is just a JSON list of strings on the key. `has_scope()` checks it
three ways, in order:

```python
key.scopes = ["orders:read"]
key.has_scope("orders:read")   # True  — exact match
key.has_scope("orders:write")  # False

key.scopes = ["*"]
key.has_scope("anything:at:all")  # True — global wildcard

key.scopes = ["orders:*"]
key.has_scope("orders:read")   # True  — namespaced wildcard
key.has_scope("orders:write")  # True
key.has_scope("billing:read")  # False — different namespace
key.has_scope("orders")        # False — wildcard needs the "orders:" prefix
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

That gets you a list view with a masked key column
(`tak_live_3f9a2c1d.••••••••••••`) instead of anything secret, and a
create flow that shows the raw key exactly once, in a dismissible admin
message, right after you save. It's never written to a form field, so it
can't come back later in the change view no matter who's looking. `prefix`,
`hashed_key`, and `created_at` are read-only for the same reason — there's
nothing useful an admin user could safely do by editing them.

It's a normal `ModelAdmin` underneath, so `list_display`, `fieldsets`,
custom permissions — all of that layers on top the way you'd expect.

## How this compares to other options

The most established alternative in the Django ecosystem is
[`djangorestframework-api-key`](https://florimondmanca.github.io/djangorestframework-api-key/),
and it's a solid, battle-tested package. If all you need is a key that's
either active or not, it's the safer, more established pick.

`django-tenant-apikeys` exists for a narrower, specific shape of problem:
you have tenants, and a key belongs to one of them. The `tenant` attachment
on `request.tenant` and the scope system (`"orders:*"`-style wildcards, not
just a boolean) are built around that use case rather than added on top of
a more generic one. If you're not multi-tenant, or you don't need
per-key permissions, you probably don't need this package — and that's a
fine reason to use something else instead.

## Settings reference

| Setting                | Required | Description                                                              |
|-------------------------|:--------:|---------------------------------------------------------------------------|
| `TENANT_API_KEY_MODEL`  | Yes\*    | `"app_label.ModelName"` string pointing at your concrete key model. Read by `get_api_key_model()` / `TenantAPIKeyAuthentication.get_model()`. |

\* Only if you rely on the default model resolution. Subclass
`TenantAPIKeyAuthentication` with an explicit `model` attribute, or don't
call `get_api_key_model()` at all, and you can skip this setting entirely.

## API reference

### `django_tenant_apikeys.models`

- `generate_api_key(prefix: str = "tak") -> tuple[str, str, str]` — returns
  `(full_key, key_prefix, hashed_key)`.
- `hash_key(raw_key: str) -> str` — SHA-256 hex digest of `raw_key`.
- `get_api_key_model() -> type[AbstractTenantAPIKey]` — resolves
  `settings.TENANT_API_KEY_MODEL`; raises `ImproperlyConfigured` if it's
  unset or invalid.
- `AbstractTenantAPIKey` — abstract model with fields `name`, `prefix`,
  `hashed_key`, `scopes`, `is_active`, `created_at`, `expires_at`,
  `last_used_at`, plus:
  - `generate_key(cls, *, prefix="tak", **kwargs) -> tuple[instance, raw_key]`
  - `verify_key(self, raw_key: str) -> bool`
  - `has_scope(self, required_scope: str) -> bool`
  - `record_usage(self) -> None` — updates `last_used_at`, throttled by
    `LAST_USED_THRESHOLD` (5 minutes by default) so a hot endpoint isn't a
    write on every request. `TenantAPIKeyAuthentication` calls this on every
    successful authentication; call it yourself from a custom integration.
  - `is_expired` / `is_valid` properties
- `TenantAPIKeyManager` (`.objects`) — `get_from_key(raw_key)` for an
  indexed prefix lookup (still call `verify_key()` on what it returns),
  and `get_usable_keys()` for active, unexpired keys only.

### `django_tenant_apikeys.authentication` (needs `[drf]`)

- `TenantAPIKeyAuthentication` — the DRF `BaseAuthentication` subclass
  described above.

### `django_tenant_apikeys.permissions` (needs `[drf]`)

- `HasAPIKeyScope` — the DRF `BasePermission` subclass described above.

### `django_tenant_apikeys.admin`

- `TenantAPIKeyAdmin` — the `ModelAdmin` base class described above.

## Security notes

**The hash is unsalted SHA-256, and that's deliberate, not an oversight.**
The input already carries 256 bits of entropy from `secrets.token_urlsafe`
— it's nothing like a low-entropy human password, so it isn't exposed to
dictionary or rainbow-table attacks the way a password hash would be.
Salting a value that's already this random buys you nothing here.

**Comparisons run in constant time.** `verify_key()` uses
`secrets.compare_digest` instead of `==`, so an attacker can't use response
timing to work out a key one byte at a time.

**The raw key can't be recovered, by design.** Once `generate_key()`
returns it, that's the only copy that will ever exist. If your app loses
it before showing it to the user, the fix is issuing a new key — not
digging through the database.

**Revoke by deactivating, not deleting.** `is_active=False` shuts a key off
immediately while keeping the audit trail intact, and
`TenantAPIKeyAuthentication` rejects a deactivated key with the exact same
error it uses for an invalid one — so a revoked key doesn't leak the fact
that it used to be valid.

**This library doesn't rate-limit anything.** It verifies a presented key;
it has no opinion on how many times someone gets to guess wrong. Pair it
with a DRF throttle class if brute-force protection matters for your API.

## FAQ

**Is this production-ready?**
The core is small, has 100% test coverage, and is type-checked with mypy
in strict mode. That said, it's a young package (`v0.1.0`) without much of
a track record yet — read the code before you bet a production auth path
on it, same as you should with any new dependency.

**Do I need Django REST Framework to use this?**
No. The model, hashing, and scope logic have zero DRF dependency. The
`[drf]` extra only adds `TenantAPIKeyAuthentication` and `HasAPIKeyScope`
on top. Plain Django views, or Ninja via the recipe above, both work
without it.

**How do I rotate a key?**
There's no built-in `rotate()` yet — issue a new key with
`Model.generate_key(...)`, update whatever's using the old one, then set
`is_active=False` on the old row once the rollover is done.

**Can a key have more than one tenant?**
Not out of the box — `tenant` is a single `ForeignKey`. If you need a key
shared across several tenants, model that relationship yourself; the
library doesn't assume anything about how `tenant` is defined beyond its
name.

**Async views?**
`TenantAPIKeyAuthentication.authenticate()` is synchronous, matching DRF's
own authentication classes, which don't have first-class async support
either. Wrap the lookup in `sync_to_async` if you're calling it from async
code directly.

## Running the tests

```bash
git clone https://github.com/stackadnan/django-tenant-apikeys
cd django-tenant-apikeys
pip install -e ".[dev]"
pytest --cov=django_tenant_apikeys --cov-report=term-missing
```

The suite runs against an in-memory SQLite database (`tests/settings.py`),
with concrete subclasses of `AbstractTenantAPIKey` defined in
`tests/models.py` — the abstract model itself can't be instantiated or
queried directly, so something concrete has to stand in for it.

## Contributing

Issues and pull requests are welcome. If you're changing behavior, add a
test for it, and run `ruff check .`, `mypy django_tenant_apikeys`, and
`pytest` before opening the PR — that's exactly what CI checks on every
push, so you'll see the same result either way.

## License

[MIT](LICENSE)
