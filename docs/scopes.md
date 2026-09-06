# Scoped API keys

Authenticating a request tells you *who* is calling. Scopes tell you *what
they're allowed to do* — and in a multi-tenant API, that's decided per key,
not per tenant. A tenant might issue a read-only key to a reporting
integration and a full read-write key to their own backend; both keys
belong to the same tenant but should not be able to do the same things.

## Scopes live on the key

`scopes` is a plain `JSONField` — a list of strings:

```python
key.scopes = ["orders:read", "orders:write", "customers:read"]
```

There's no separate scopes table, no join, no migration needed to add a new
scope string. A scope is just a string your application code agrees to
check for. That's a deliberate simplicity trade-off: you design your own
scope taxonomy (`orders:read`, `billing:write`, whatever maps to your
domain) rather than the package imposing one.

## Checking a scope

`has_scope()` supports three matching modes:

```python
key.scopes = ["orders:read"]
key.has_scope("orders:read")     # True  -- exact match
key.has_scope("orders:write")    # False -- not granted

key.scopes = ["orders:*"]
key.has_scope("orders:read")     # True  -- namespaced wildcard
key.has_scope("orders:write")    # True
key.has_scope("customers:read")  # False -- different namespace
key.has_scope("orders")          # False -- wildcard needs the "orders:" prefix

key.scopes = ["*"]
key.has_scope("anything:here")   # True  -- global wildcard, use sparingly
```

The namespaced wildcard (`"orders:*"`) is the useful middle ground — it lets
a tenant issue a key scoped to an entire resource without you having to
enumerate every action on it up front. Reserve the global `"*"` for a
tenant's own internal/admin key, not for anything issued to a third party.

## Enforcing scopes

### Django REST Framework

`HasAPIKeyScope` reads `required_scopes` off the view and requires **all**
of them:

```python
class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

```python
required_scopes = ["orders:read", "customers:read"]  # needs both, not either
```

An empty or missing `required_scopes` means **any authenticated key** is
allowed through — `HasAPIKeyScope` only blocks on scopes it's told to
check. It also returns `False` outright if `request.auth` isn't an API key
instance at all, so it's meant to be paired with
`TenantAPIKeyAuthentication`, not used alone.

Need "either/or" instead of "all of"? That's not built in — write a small
custom permission class that calls `has_scope()` yourself with `any(...)`.

Varying the required scope per action on a `ViewSet`:

```python
class OrdersViewSet(viewsets.ModelViewSet):
    authentication_classes = [TenantAPIKeyAuthentication]

    def get_permissions(self):
        self.required_scopes = (
            ["orders:write"]
            if self.action in ("create", "update", "partial_update", "destroy")
            else ["orders:read"]
        )
        return [HasAPIKeyScope()]
```

### Django Ninja

There's no Ninja equivalent of `HasAPIKeyScope` — Ninja doesn't have a
permission-class system to hook into. Check `has_scope()` directly in the
view body:

```python
@api.get("/orders")
def list_orders(request):
    if not request.auth.has_scope("orders:read"):
        return 403, {"detail": "missing required scope"}
    return request.tenant.orders.all()
```

See [Django Ninja](django-ninja.md) for the full integration, including how
this composes with IP and rate-limit checks.

## Designing scopes that age well

- **Namespace by resource, not by endpoint.** `orders:read` survives you
  adding a new endpoint that also reads orders; `list-orders:read` doesn't.
- **Don't scope what you don't enforce yet.** An unused scope string in a
  key's `scopes` list that no view checks is a false sense of security —
  keep the taxonomy driven by actual `required_scopes` in your views.
- **Treat `["*"]` as a privileged, rare grant** — audit which keys have it
  the same way you'd audit superuser accounts.
- **Scopes don't replace `is_active`/`expires_at`.** A key with the right
  scope but `is_active=False` is rejected at authentication, before
  `HasAPIKeyScope` is even consulted. Revoking a key is still the fast path
  for "this integration should stop entirely"; scopes are for "this
  integration should only do X." See [Key lifecycle](key-lifecycle.md).

## Next

- [Key lifecycle](key-lifecycle.md) — rotating a key without changing its
  scopes, or overriding them on rotation.
- [IP restrictions](ip-restrictions.md) and [rate limiting](rate-limiting.md)
  — the other two per-key policies, checked alongside scopes.
