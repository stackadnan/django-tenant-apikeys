# django-tenant-apikeys

[![PyPI version](https://img.shields.io/pypi/v/django-tenant-apikeys.svg)](https://pypi.org/project/django-tenant-apikeys/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-tenant-apikeys.svg)](https://pypi.org/project/django-tenant-apikeys/)
[![Tests](https://github.com/stackadnan/django-tenant-apikeys/actions/workflows/test.yml/badge.svg)](https://github.com/stackadnan/django-tenant-apikeys/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/pypi/l/django-tenant-apikeys.svg)](LICENSE)
[![Latest on Django Packages](https://img.shields.io/badge/Django_Packages-django--tenant--apikeys-8c3c26.svg)](https://djangopackages.org/packages/p/django-tenant-apikeys/)

<p align="center">
  <img src="https://raw.githubusercontent.com/stackadnan/django-tenant-apikeys/main/docs/images/banner.png" alt="django-tenant-apikeys" width="900">
</p>

<p align="center">
  API keys for multi-tenant Django applications
</p>

Multi-tenant API key authentication for Django. Issue a key per tenant, hash
it before it ever touches the database, gate access with scopes instead of
an all-or-nothing flag, and rotate or revoke it later without touching your
own code. Works with Django REST Framework and Django Ninja out of the box.

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
- **A real lifecycle, not just a boolean.** `rotate()` issues a replacement
  and revokes the original in one call; `revoke()`/`reactivate()` manage
  access directly. Management commands cover both from the shell.
- **Small, framework-agnostic core.** The model doesn't know DRF or Ninja
  exist. `authentication.py`, `permissions.py`, and `ninja.py` are optional
  adapters on top of it, so you can build your own integration if neither
  fits.

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
- [Environments](#environments)
- [IP restrictions](#ip-restrictions)
- [Rate limiting](#rate-limiting)
- [Metadata](#metadata)
- [How the policies interact](#how-the-policies-interact)
- [Key lifecycle: rotating and revoking keys](#key-lifecycle-rotating-and-revoking-keys)
- [Management commands](#management-commands)
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
| `ninja` | `django-ninja>=1.0`          | `TenantAPIKeyAuth`                              |

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
`TenantAPIKeyAuth` (Ninja) check for an attribute with that exact name and,
if it exists, attach it to the request as `request.tenant`. Name it
something else and you just lose that one convenience — everything else
still works fine.

### 2. Point Django at it

```python
# settings.py
INSTALLED_APPS = [
    ...
    "django_tenant_apikeys",  # needed for the admin integration and the management commands
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

```bash
pip install django-tenant-apikeys[ninja]
```

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

`TenantAPIKeyAuth` mirrors `TenantAPIKeyAuthentication`'s rules exactly: an
unknown, tampered, inactive, or expired key never falls through as
anonymous access, `record_usage()` runs on every success, and
`request.tenant` gets attached the same way. The one real difference is in
how failure surfaces — Ninja doesn't have DRF's `AuthenticationFailed` with
a specific message, so `authenticate()` just returns `None` for every
rejection reason and Ninja turns that into a 401 on its own.

There's no Ninja equivalent of `HasAPIKeyScope` — Ninja doesn't have a
permission-class system to hook into the way DRF does, so scope checks
happen inline in the view via `has_scope()`, as above. `get_api_key_model()`,
`verify_key()`, `has_scope()`, `rotate()`, `revoke()` — none of it knows or
cares which framework is calling it.

Need multiple key models, same as the DRF class supports? Subclass and set
`model`:

```python
class PartnerAPIKeyAuth(TenantAPIKeyAuth):
    model = PartnerAPIKey
```

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

## Environments

Every key belongs to an `environment`: `"production"` (the default),
`"staging"`, `"development"`, or `"test"`.

```python
from django_tenant_apikeys.models import Environment

instance, raw_key = OrganizationAPIKey.generate_key(
    name="Staging smoke tests",
    tenant=org,
    environment=Environment.TEST,
)
raw_key               # tak_test_3f9a2c1d.Xk7p...
instance.environment   # "test"
```

`generate_key()` also encodes a coarser signal into the prefix itself —
`production`/`staging` both get `_live_`, `development`/`test` both get
`_test_` — so a key is recognizable at a glance in a log line the same way
Stripe's or GitHub's are. That's a convenience, not the source of truth:
**always check `instance.environment`, never parse the prefix.** Keys
issued before 0.4.0 have no `environment` column to read, so they default
to `"production"` — the same access level they've always had, just now
named explicitly.

## IP restrictions

`allowed_ips` restricts a key to specific IPs and/or CIDR networks (IPv4 or
IPv6). Leave it empty (the default) for no restriction — every key created
before 0.4.0 behaves this way and keeps working unchanged.

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="Office network only",
    tenant=org,
    allowed_ips=["203.0.113.10", "203.0.113.0/24", "2001:db8::/32"],
)
```

`generate_key()` parses every entry with the standard library's
`ipaddress` module up front and raises `ValueError` immediately on
anything that isn't a valid address or network — no custom parsing, no
silently-ignored typo.

**DRF** — add `HasAllowedIP` to `permission_classes`, alongside
`HasAPIKeyScope`:

```python
from django_tenant_apikeys.permissions import HasAllowedIP, HasAPIKeyScope

class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAllowedIP, HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

A request from outside `allowed_ips` gets a 403.

**Django Ninja** — there's no permission-class system to hook into, so
check inline, the same way scopes already are:

```python
from django_tenant_apikeys.ip import get_client_ip

@api.get("/orders")
def list_orders(request):
    if not request.auth.is_ip_allowed(get_client_ip(request)):
        return 403, {"detail": "IP not allowed"}
    ...
```

**How the client IP is determined matters.** `get_client_ip()` reads
`REMOTE_ADDR` — the actual TCP connection's source address — and nothing
else, unless you explicitly opt in to trusting a proxy header via
`TENANT_API_KEY_TRUSTED_PROXY_HEADER` (see
[Settings reference](#settings-reference)). `X-Forwarded-For` and similar
headers are ordinary request headers that any client can set to whatever
they want; trusting one by default would let an attacker bypass an IP
allowlist just by sending a fake header. Only turn this on if you know a
reverse proxy you control is the one setting (and stripping any
client-supplied copy of) that header before Django ever sees the request.

## Rate limiting

`rate_limit` (an integer) and `rate_limit_window` (one of `"second"`,
`"minute"`, `"hour"`, `"day"`; defaults to `"minute"`) cap how many requests
a key can make. Leave `rate_limit` unset (the default) for no limit — same
as every key created before 0.4.0.

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="Production API",
    tenant=org,
    rate_limit=1000,
    rate_limit_window="minute",
)
```

**DRF** — add `WithinRateLimit` to `permission_classes`:

```python
from django_tenant_apikeys.permissions import HasAPIKeyScope, WithinRateLimit

class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [WithinRateLimit, HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

Once the limit is hit, this raises DRF's `Throttled` — a 429 with a
`Retry-After` header — instead of the usual 403, and sets
`X-RateLimit-Limit`/`X-RateLimit-Remaining`/`X-RateLimit-Reset` on the
response either way (allowed or not), the same mechanism DRF itself uses
for headers like `Allow`.

**Django Ninja** — again, inline:

```python
from django_tenant_apikeys.ratelimit import check_rate_limit

@api.get("/orders")
def list_orders(request):
    result = check_rate_limit(request.auth)
    if not result.allowed:
        return 429, {"detail": "rate limit exceeded", "retry_after": result.retry_after}
    ...
```

**How limits are counted.** The default backend (`CacheRateLimitBackend`)
is a fixed-window counter stored in Django's cache framework
(`CACHES["default"]`, or whichever alias `TENANT_API_KEY_RATE_LIMIT_CACHE`
names). It uses `cache.add()` and `cache.incr()` — both atomic on any real
cache backend — rather than a get-then-set round trip, so concurrent
requests against the same key can't race each other into an undercount.
That said, it's only as consistent as the cache backend behind it:

- **LocMemCache** (Django's default with no `CACHES` configured) is
  per-process. Multiple worker processes (gunicorn, uWSGI, ...) each
  enforce the limit independently rather than sharing one count — fine for
  local development or a single-process deployment, not a real limit
  across workers.
- **Memcached or a shared Redis** (via `django-redis` or similar) makes the
  same code correct across processes, since both backends implement
  `add`/`incr` atomically server-side. No package changes needed — point
  `CACHES["default"]` at one of them.
- Being a *fixed* window rather than a sliding one, a key can burst up to
  roughly 2x its limit across a window boundary (a full window's quota
  right before it rolls over, then another full window's quota right
  after). A sliding window would avoid that, at the cost of storing a
  timestamp per request instead of one counter — more than this default
  needs to carry.

Need something else — Redis with a sliding window, a distributed rate
limiter, whatever your infrastructure already runs? Point
`TENANT_API_KEY_RATE_LIMIT_BACKEND` at your own class implementing the
`RateLimitBackend` protocol (one method: `hit(key, limit, window_seconds)`)
instead of writing a custom permission class from scratch.

## Metadata

`metadata` is a `JSONField` (default `{}`) for whatever your application
wants to attach to a key. This library never reads it — it's pure storage.

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="Billing service key",
    tenant=org,
    metadata={"service": "billing", "owner": "payments-team"},
)
instance.metadata["service"]  # "billing"
```

## How the policies interact

Every check below runs in this order, and each one only runs if everything
before it already passed:

```
Authentication (extract, verify, active/expired, resolve tenant)
      ↓
IP restriction   (HasAllowedIP / is_ip_allowed())
      ↓
Rate limit       (WithinRateLimit / check_rate_limit())
      ↓
Scope            (HasAPIKeyScope / has_scope())
      ↓
Your view
```

Authentication (`TenantAPIKeyAuthentication`/`TenantAPIKeyAuth`) hasn't
changed shape for this release — it still only extracts the key, verifies
it, checks `is_active`/`expires_at`, and resolves `request.tenant`. IP,
rate limit, and scope are separate, independently testable checks layered
on top, not folded into it. For DRF that's `permission_classes`, checked in
list order — `[HasAllowedIP, WithinRateLimit, HasAPIKeyScope]` gets you the
order above. Django Ninja has no equivalent chain, so all three (scope
included) are ordinary `if` statements inline in your view, checked in
whatever order you write them.

## Key lifecycle: rotating and revoking keys

**Revoke** a key immediately, permanently:

```python
api_key.revoke(reason="compromised")   # reason is optional, stored on the row
api_key.is_active   # False
```

This sets the same `is_active` flag `TenantAPIKeyAuthentication` already
checks on every request — there's no separate "revoked" gate to fall out of
sync with. `revoked_at` and `revoked_reason` are audit metadata; nothing
reads them to decide whether the key still works. `reactivate()` undoes it:

```python
api_key.reactivate()
api_key.is_active   # True again -- but is_expired is independent, so a key
                     # whose expires_at has already passed stays unusable
```

**Rotate** a key to replace it without downtime:

```python
new_key, raw_key = api_key.rotate()
```

This creates a new row with the same tenant, scopes, expiration,
environment, rate limit, allowed IPs, and metadata as the original
(override any of them with keyword arguments, e.g.
`api_key.rotate(scopes=["orders:*"])`), revokes the original with
`reason="rotated"`, and returns the new instance and its raw key — the only
time you'll see it, exactly like `generate_key()`. The old row isn't
deleted, so it stays visible for audit history; it just can't authenticate
anymore. Rotating an already-inactive or expired key raises `ValueError`
rather than silently handing out working access from something that was
deliberately shut off.

```python
old_key, raw_key = OrganizationAPIKey.generate_key(name="k", tenant=org)
new_key, new_raw_key = old_key.rotate()

old_key.is_valid   # False
new_key.is_valid   # True
new_key.tenant == old_key.tenant   # True
```

## Management commands

```bash
python manage.py tenant_api_key_revoke <prefix> [--reason "why"]
python manage.py tenant_api_key_rotate <prefix>
```

Both resolve the model via `TENANT_API_KEY_MODEL` and look a key up by its
prefix (the part before the dot — never the raw secret, which isn't
stored), so neither needs to know what fields your concrete model adds.
`tenant_api_key_rotate` prints the new raw key once, the same way the admin
and `generate_key()` do.

There's deliberately no `tenant_api_key_create`: creating a key needs
whatever fields your concrete model requires — at minimum a `tenant` — and
this package can't know that generically without either hardcoding an
assumption or degrading into an awkward `--field=value` interface. Copy the
pattern in
[`examples/simple_saas/organizations/management/commands/create_demo_key.py`](examples/simple_saas/organizations/management/commands/create_demo_key.py)
into your own project instead; it's a normal Django management command
written against your own schema.

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
(`tak_live_3f9a2c1d.••••••••••••`) instead of anything secret, an
**environment** column, a **Status** column (`Active` / `Revoked` /
`Inactive` / `Expired` — `Revoked` only shows once `revoke()` has actually
run, so it's distinct from someone just unchecking the "active" box), and a
**Revoke selected API keys** bulk action. `list_filter` includes
`is_active`, `environment`, `created_at`, and `expires_at`. Key creation
shows the raw key exactly once, in a dismissible admin message, right after
you save. It's never written to a form field, so it can't come back later
in the change view no matter who's looking. `prefix`, `hashed_key`,
`created_at`, `last_used_at`, `revoked_at`, and `revoked_reason` are all
read-only for the same reason — there's nothing useful an admin user could
safely do by editing them directly. `rate_limit`, `rate_limit_window`,
`allowed_ips`, and `metadata` are ordinary editable fields on the change
form, same as `scopes`.

It's a normal `ModelAdmin` underneath, so `list_display`, `fieldsets`,
custom permissions — all of that layers on top the way you'd expect. The
example project's `OrganizationAPIKeyAdmin` adds a `tenant` filter this way:

```python
@admin.register(OrganizationAPIKey)
class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
    list_filter = TenantAPIKeyAdmin.list_filter + ("tenant",)
```

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

| Setting                                  | Required | Description                                                              |
|--------------------------------------------|:--------:|---------------------------------------------------------------------------|
| `TENANT_API_KEY_MODEL`                    | Yes\*    | `"app_label.ModelName"` string pointing at your concrete key model. Read by `get_api_key_model()` / `TenantAPIKeyAuthentication.get_model()`. |
| `TENANT_API_KEY_TRUSTED_PROXY_HEADER`     | No       | A `request.META` key (e.g. `"HTTP_X_FORWARDED_FOR"`) to trust for the client IP instead of `REMOTE_ADDR`. Unset by default — see [IP restrictions](#ip-restrictions) for why this has to be opt-in. |
| `TENANT_API_KEY_RATE_LIMIT_CACHE`         | No       | Cache alias (from `CACHES`) `CacheRateLimitBackend` counts requests in. Defaults to `"default"`. |
| `TENANT_API_KEY_RATE_LIMIT_BACKEND`       | No       | Dotted path to a `RateLimitBackend` class to use instead of `CacheRateLimitBackend`. See [Rate limiting](#rate-limiting). |

\* Only if you rely on the default model resolution. Subclass
`TenantAPIKeyAuthentication` with an explicit `model` attribute, or don't
call `get_api_key_model()` at all, and you can skip this setting entirely.

## API reference

### `django_tenant_apikeys.models`

- `generate_api_key(prefix: str = "tak", *, environment: str = "production") -> tuple[str, str, str]`
  — returns `(full_key, key_prefix, hashed_key)`. Raises `ValueError` for an
  unknown `environment`.
- `hash_key(raw_key: str) -> str` — SHA-256 hex digest of `raw_key`.
- `get_api_key_model() -> type[AbstractTenantAPIKey]` — resolves
  `settings.TENANT_API_KEY_MODEL`; raises `ImproperlyConfigured` if it's
  unset or invalid.
- `Environment` — `TextChoices`: `PRODUCTION` (default), `STAGING`,
  `DEVELOPMENT`, `TEST`.
- `RateLimitWindow` — `TextChoices`: `SECOND`, `MINUTE` (default), `HOUR`, `DAY`.
- `AbstractTenantAPIKey` — abstract model with fields `name`, `prefix`,
  `hashed_key`, `scopes`, `environment`, `rate_limit`, `rate_limit_window`,
  `allowed_ips`, `metadata`, `is_active`, `created_at`, `expires_at`,
  `last_used_at`, `revoked_at`, `revoked_reason`, plus:
  - `generate_key(cls, *, prefix="tak", **kwargs) -> tuple[instance, raw_key]`
    — raises `ValueError` if `scopes` or `allowed_ips` is passed and isn't a
    list of non-empty strings (each `allowed_ips` entry must also parse as
    an IP or CIDR network), if `rate_limit` is passed and isn't a positive
    integer, or if `rate_limit_window`/`environment` isn't a valid choice.
  - `verify_key(self, raw_key: str) -> bool`
  - `has_scope(self, required_scope: str) -> bool`
  - `is_ip_allowed(self, client_ip: str) -> bool` — True if `allowed_ips` is
    empty or covers `client_ip`.
  - `record_usage(self) -> None` — updates `last_used_at`, throttled by
    `LAST_USED_THRESHOLD` (5 minutes by default) so a hot endpoint isn't a
    write on every request. `TenantAPIKeyAuthentication` and
    `TenantAPIKeyAuth` both call this on every successful authentication;
    call it yourself from a custom integration.
  - `revoke(self, *, reason="") -> None` / `reactivate(self) -> None`
  - `rotate(self, *, prefix="tak", **overrides) -> tuple[instance, raw_key]`
  - `is_expired` / `is_valid` properties
- `TenantAPIKeyManager` (`.objects`) — `get_from_key(raw_key)` for an
  indexed prefix lookup (still call `verify_key()` on what it returns),
  and `get_usable_keys()` for active, unexpired keys only.

### `django_tenant_apikeys.ip`

- `get_client_ip(request) -> str` — described in
  [IP restrictions](#ip-restrictions). No optional dependency required.

### `django_tenant_apikeys.ratelimit`

- `check_rate_limit(api_key) -> RateLimitResult` — records one request and
  checks it against `api_key.rate_limit`. `RateLimitResult` has `allowed`,
  `limit`, `remaining`, `reset_at` (Unix timestamp), and `retry_after`
  (seconds; only set when `allowed` is False) — the last four are all
  `None` if `api_key.rate_limit` is unset.
- `RateLimitBackend` — the protocol a custom backend implements: one method,
  `hit(key: str, limit: int, window_seconds: int) -> RateLimitResult`.
- `CacheRateLimitBackend` — the default backend, described in
  [Rate limiting](#rate-limiting).
- `get_rate_limit_backend() -> RateLimitBackend` — resolves
  `TENANT_API_KEY_RATE_LIMIT_BACKEND`, defaulting to `CacheRateLimitBackend`.
  No optional dependency required.

### `django_tenant_apikeys.authentication` (needs `[drf]`)

- `TenantAPIKeyAuthentication` — the DRF `BaseAuthentication` subclass
  described above.

### `django_tenant_apikeys.permissions` (needs `[drf]`)

- `HasAPIKeyScope` — the DRF `BasePermission` subclass described above.
- `HasAllowedIP` — enforces `allowed_ips`. Described in
  [IP restrictions](#ip-restrictions).
- `WithinRateLimit` — enforces `rate_limit`, raising `Throttled` (429) once
  exceeded. Described in [Rate limiting](#rate-limiting).

### `django_tenant_apikeys.ninja` (needs `[ninja]`)

- `TenantAPIKeyAuth` — the Ninja `APIKeyHeader` subclass described above.

### `django_tenant_apikeys.admin`

- `TenantAPIKeyAdmin` — the `ModelAdmin` base class described above.

### Management commands

- `tenant_api_key_revoke <prefix> [--reason TEXT]`
- `tenant_api_key_rotate <prefix>`

Both described above. Require `django_tenant_apikeys` in `INSTALLED_APPS`.

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

**Revocation deactivates, it never deletes.** `revoke()` sets the same
`is_active` flag authentication already checks — there's no second
enforcement path to keep in sync — and `TenantAPIKeyAuthentication` /
`TenantAPIKeyAuth` reject a revoked key with the exact same outcome as an
unknown or expired one. `revoked_at` and `revoked_reason` are audit
metadata only; nothing about an authentication response distinguishes
"revoked" from "invalid" from "expired," so a caller probing with guessed
keys can't learn anything about a key's history from how it fails.

**Rotation can't accidentally resurrect a dead key.** `rotate()` refuses to
run on a key that's already inactive or expired, and both operations that
make up a rotation (creating the new row, revoking the old one) happen
inside a single `transaction.atomic()` block.

**Rate limiting doesn't replace a real brute-force defense.** `rate_limit`
caps how often a *valid, resolved* key can be used — it runs after
`verify_key()` has already succeeded. It says nothing about how many wrong
keys someone can try; pair this with a DRF throttle class (or your
reverse proxy) if guessing protection at the authentication step itself
matters for your API.

**Client IPs are never trusted from a spoofable header by default.**
`get_client_ip()` reads `REMOTE_ADDR` unless
`TENANT_API_KEY_TRUSTED_PROXY_HEADER` explicitly opts into a specific
header — see [IP restrictions](#ip-restrictions). Turning that setting on
without an actual trusted reverse proxy stripping client-supplied copies
of that header first would let any caller set their own "IP" and bypass
`allowed_ips` entirely.

**Rate-limit state can't leak between keys or tenants.** Each key's
counter is keyed by its concrete model name and primary key, so two keys —
even identical-looking ones on two different tenants — never share a
counter. See [Rate limiting](#rate-limiting) for the default backend's
consistency characteristics (in short: correct under concurrency within one
process; per-process, not global, unless you configure a shared cache like
Memcached or Redis).

## FAQ

**Is this production-ready?**
The core is small, has 100% test coverage (including against PostgreSQL in
CI, not just SQLite), and is type-checked with mypy in strict mode. That
said, it's still a young package without much of a track record yet — read
the code before you bet a production auth path on it, same as you should
with any new dependency.

**Do I need Django REST Framework to use this?**
No. The model, hashing, scope, and lifecycle logic have zero DRF
dependency. The `[drf]` extra only adds `TenantAPIKeyAuthentication` and
`HasAPIKeyScope` on top. Plain Django views, or Ninja via `[ninja]`, both
work without it.

**How do I rotate a key?**
`old_key.rotate()`, or `python manage.py tenant_api_key_rotate <prefix>`
from the shell. Either returns/prints the new raw key once and revokes the
old row (kept, not deleted) with `reason="rotated"`. See
[Key lifecycle](#key-lifecycle-rotating-and-revoking-keys) above.

**How do I revoke a compromised key right now?**
`api_key.revoke(reason="compromised")`, the **Revoke selected API keys**
admin action, or `python manage.py tenant_api_key_revoke <prefix> --reason
compromised`. All three go through the same `is_active` flag
authentication already checks, so there's no delay or cache to worry
about — the very next request with that key fails.

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

**Does rate limiting need Redis?**
No — the default `CacheRateLimitBackend` works with whatever's in
`CACHES["default"]`, including Django's built-in LocMemCache. It's correct
under concurrent requests *within one process*; running multiple worker
processes needs a shared cache (Memcached, or Redis via `django-redis`) for
the limit to actually be shared across them. See
[Rate limiting](#rate-limiting) for the full explanation, and
`TENANT_API_KEY_RATE_LIMIT_BACKEND` if you want to plug in something else
entirely (e.g. a future Redis-native sliding-window implementation).

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
queried directly, so something concrete has to stand in for it. CI also
runs the same suite against PostgreSQL (`tests/settings_postgres.py`) —
`psycopg` isn't part of the `dev` extra, since nothing in the package
itself needs it, so `pip install "psycopg[binary]"` first if you want to
run that locally: `pytest --ds=tests.settings_postgres`.

## Contributing

Issues and pull requests are welcome. If you're changing behavior, add a
test for it, and run `ruff check .`, `mypy django_tenant_apikeys`, and
`pytest` before opening the PR — that's exactly what CI checks on every
push, so you'll see the same result either way.

## License

[MIT](LICENSE)
