# Django API key rate limiting

A key can cap how many requests it's allowed to make per second, minute,
hour, or day.

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="Production API",
    tenant=org,
    rate_limit=1000,
    rate_limit_window="minute",
)
```

Leave `rate_limit` unset (the default) for no limit — the same behavior
every key had before this field existed. `rate_limit_window` defaults to
`"minute"` and is only meaningful once `rate_limit` is set; the valid
values are `"second"`, `"minute"`, `"hour"`, `"day"` (also available as
`RateLimitWindow.SECOND` / `.MINUTE` / `.HOUR` / `.DAY`).

## Checking the limit

```python
from django_tenant_apikeys.ratelimit import check_rate_limit

result = check_rate_limit(api_key)
result.allowed       # bool
result.limit          # the configured rate_limit, or None if unset
result.remaining      # requests left in the current window
result.reset_at        # Unix timestamp the window resets at
result.retry_after     # seconds until reset -- only set when allowed is False
```

Calling `check_rate_limit()` **records** a request against the key's
counter and reports whether it's still within the limit — it's not a
read-only check. Call it once per request you actually want counted. If
`rate_limit` isn't set, it always returns `allowed=True` with every other
field `None`.

## What happens when the limit is exceeded

### Django REST Framework

```python
from django_tenant_apikeys.permissions import HasAPIKeyScope, WithinRateLimit

class OrdersView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [WithinRateLimit, HasAPIKeyScope]
    required_scopes = ["orders:read"]
```

Once the limit is hit, `WithinRateLimit` raises DRF's own `Throttled` — a
429 response with a `Retry-After` header — instead of returning `False`
(which would produce DRF's default 403). It also sets
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` on the
response, whether the request was allowed or not, via `view.headers` — the
same mechanism DRF itself uses for headers like `Allow`.

### Django Ninja

```python
from django_tenant_apikeys.ratelimit import check_rate_limit

@api.get("/orders")
def list_orders(request):
    result = check_rate_limit(request.auth)
    if not result.allowed:
        return 429, {"detail": "rate limit exceeded", "retry_after": result.retry_after}
    ...
```

See [Django Ninja](django-ninja.md) for the full view, composed with IP and
scope checks.

## How the default backend counts requests

`CacheRateLimitBackend` is a **fixed-window counter** stored in Django's
cache framework — `CACHES["default"]`, or whichever alias
`TENANT_API_KEY_RATE_LIMIT_CACHE` names.

It uses `cache.add()` (set-if-absent) to seed a window's counter and
`cache.incr()` (increment) to count each request, instead of a
get-then-set round trip:

```python
count = cache.get(key)   # NOT what this backend does
count += 1
cache.set(key, count)
```

That pattern races: two concurrent requests can both read the same starting
value and both write back `count + 1`, undercounting by one every time two
requests overlap. `add()` + `incr()` avoids it **only if the cache backend
implements them atomically**. Django's base `incr()` is itself a
read-then-write, and only some backends override it — see the table below.

### Consistency depends on the cache backend

| Cache backend | `add()`/`incr()` | Effect on the limit |
|---|---|---|
| Redis, Memcached | atomic on the server | exact, shared across processes |
| `LocMemCache` | atomic within a process (lock) | per-process: each worker counts separately |
| `DatabaseCache` | `incr()` is get-then-set | concurrent requests can be undercounted — the limit can be exceeded. `RuntimeWarning` |
| `FileBasedCache` | neither is atomic | same as above. `RuntimeWarning` |
| `DummyCache` | stores nothing | **the limit is never enforced.** `RuntimeWarning` |

`CacheRateLimitBackend` emits a `RuntimeWarning` when constructed on any of
the last three, so a limit that can't hold doesn't fail silently.

- **LocMemCache** (Django's default if `CACHES` isn't configured) is
  **per-process**. `add()`/`incr()` are thread-safe within one process, but
  each worker process (gunicorn, uWSGI, ...) has its own memory — multiple
  workers each enforce the limit independently rather than sharing one
  count. Fine for local development or a genuinely single-process
  deployment; not a real limit across workers.
- **Memcached, or a shared Redis** (via `django-redis` or similar), makes
  the exact same code correct across processes, because both backends
  implement `add`/`incr` atomically on the server, not just in Django's
  process. No package changes needed — point `CACHES["default"]` (or
  whatever `TENANT_API_KEY_RATE_LIMIT_CACHE` names) at one of them.

### Fixed window, not sliding

Being a fixed window rather than a sliding one, a key can burst up to
roughly 2x its limit across a window boundary — a full window's quota right
before it rolls over, then another full window's quota right after. A
sliding window would avoid that, at the cost of storing a timestamp per
request instead of a single counter — real complexity this default doesn't
carry. If that trade-off doesn't work for your use case, see the custom
backend section below.

## Tenant isolation

The cache key `check_rate_limit()` builds includes both the concrete
model's class name and the key's primary key:

```python
f"tenant_api_key_ratelimit:{type(api_key).__name__}:{api_key.pk}"
```

Two tenants with identically-configured keys (same `rate_limit`, even the
same `name`) never share a counter — each key row has its own primary key,
and each key's usage only ever affects its own count. The class name guards
against a narrower edge case: two *different* concrete
`AbstractTenantAPIKey` subclasses in the same project (say, an
`OrganizationAPIKey` and a `PartnerAPIKey`) whose primary keys happen to
collide numerically, which would otherwise share a cache key and a counter
that belongs to a different model's row entirely.

## A custom backend

`RateLimitBackend` is a `Protocol` — anything with a matching `hit()` method
works:

```python
class RateLimitBackend(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult: ...
```

Point `TENANT_API_KEY_RATE_LIMIT_BACKEND` at a dotted path to your own
class (constructed with no arguments) to replace `CacheRateLimitBackend`
entirely:

```python
# settings.py
TENANT_API_KEY_RATE_LIMIT_BACKEND = "myapp.ratelimit.SlidingWindowRedisBackend"
```

```python
# myapp/ratelimit.py
from django_tenant_apikeys.ratelimit import RateLimitResult

class SlidingWindowRedisBackend:
    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        ...
```

This is the seam for a Redis-native sliding-window implementation, or
anything else the default cache-backed counter doesn't give you — nothing
in `check_rate_limit()`, `WithinRateLimit`, or the Ninja integration needs
to change to use it.

## Next

- [IP restrictions](ip-restrictions.md) — the check that runs immediately
  before rate limiting in the recommended DRF/Ninja order.
- [Configuration](configuration.md) — `TENANT_API_KEY_RATE_LIMIT_CACHE` and
  `TENANT_API_KEY_RATE_LIMIT_BACKEND` in the full settings reference.
- [Security](security.md) — what rate limiting does and doesn't protect
  against (it isn't brute-force protection on the authentication step
  itself).
