# Scoping API keys per tenant in Django REST Framework

Authenticating a request tells you *who* is calling. Scoping tells you
*what they're allowed to do* — and in a multi-tenant API, that has to be
decided per key, not per tenant. A tenant might issue a read-only key to a
reporting integration and a full read-write key to their own backend, and
both keys belong to the same tenant. This page covers how
[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
models that with `scopes` and `HasAPIKeyScope`, and some patterns for using
them well. If you haven't seen the basics of the key model yet, start with
[Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication).

## Scopes live on the key, not the tenant

`AbstractTenantAPIKey.scopes` is a plain `JSONField`, a list of strings:

```python
key.scopes = ["orders:read", "orders:write", "customers:read"]
```

There's no separate scopes table, no join, no migration needed to add a new
scope string — a scope is just a string your application code agrees to
check for. That's a deliberate simplicity trade-off: it means you design
your own scope taxonomy (`orders:read`, `billing:write`, whatever maps to
your domain) rather than the package imposing one.

## Checking a scope: exact, namespaced, and global wildcards

`has_scope()` supports three matching modes:

```python
key.scopes = ["orders:read"]
key.has_scope("orders:read")     # True  -- exact match
key.has_scope("orders:write")    # False -- not granted

key.scopes = ["orders:*"]
key.has_scope("orders:read")     # True  -- namespaced wildcard
key.has_scope("orders:write")    # True
key.has_scope("customers:read")  # False -- different namespace

key.scopes = ["*"]
key.has_scope("anything:here")   # True  -- global wildcard, use sparingly
```

The namespaced wildcard (`"orders:*"`) is the useful middle ground: it lets
a tenant issue a key scoped to an entire resource without you having to
enumerate every action on it. Reserve the global `"*"` for a tenant's own
internal/admin key, not for anything issued to a third party.

## Enforcing scopes on a view

`HasAPIKeyScope` is a DRF permission class that reads `required_scopes` off
the view and checks every one of them against the authenticated key:

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

It requires **all** listed scopes (`all(api_key.has_scope(s) for s in
required_scopes)`), so if a view needs two scopes at once:

```python
required_scopes = ["orders:read", "customers:read"]
```

...a key needs both — one or the other isn't enough. If you need
"either/or" semantics instead, that's not built in; write a small custom
permission class that calls `has_scope()` yourself with `any(...)`.

An empty or missing `required_scopes` means **any authenticated key** is
allowed through — `HasAPIKeyScope` only blocks on scopes it's told to
check, it doesn't require you to declare them everywhere. That also means
it's not a substitute for `TenantAPIKeyAuthentication`: `HasAPIKeyScope`
returns `False` outright if `request.auth` isn't an API key instance at
all, so the two are meant to be paired, not used alone.

## Scoping per-viewset action

`required_scopes` is just a class attribute, so with a DRF `ViewSet` you
can vary it per action by overriding `get_permissions()`:

```python
class OrdersViewSet(viewsets.ModelViewSet):
    authentication_classes = [TenantAPIKeyAuthentication]

    def get_permissions(self):
        self.required_scopes = (
            ["orders:write"] if self.action in ("create", "update", "partial_update", "destroy")
            else ["orders:read"]
        )
        return [HasAPIKeyScope()]
```

## Designing scopes so they age well

A few practical rules that hold up as an API grows:

- **Namespace by resource, not by endpoint.** `orders:read` survives you
  adding a new endpoint that also reads orders; `list-orders:read` doesn't.
- **Don't scope what you don't enforce yet.** An unused scope string in a
  key's `scopes` list that no view checks is a false sense of security —
  keep the taxonomy driven by actual `required_scopes` in your views.
- **Treat `["*"]` as a privileged, rare grant.** Since it satisfies every
  `has_scope()` check, audit which keys actually have it the same way
  you'd audit superuser accounts.
- **Scopes don't replace `is_active`/`expires_at`.** A key with the right
  scope but `is_active=False` is still rejected at the authentication
  step, before `HasAPIKeyScope` is even consulted — revoking a key is
  still the fast path for "this integration should stop working now,"
  scopes are for "this integration should only do X."

## Try it

- `pip install django-tenant-apikeys[drf]`
- Full API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working end-to-end project: [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
