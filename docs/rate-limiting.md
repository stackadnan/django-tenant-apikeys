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

Rate limiting is a normal throttle in each framework, so the framework
answers **429 with `Retry-After`**. A key with no `rate_limit`, and a request
not authenticated by an API key, are never throttled.

### Django REST Framework

```python
# settings.py -- every view
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "django_tenant_apikeys.throttling.TenantAPIKeyThrottle",
    ],
}
```

or `throttle_classes = [TenantAPIKeyThrottle]` on a view. It also sets
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` on the
response, allowed or not, via `view.headers`.

`WithinRateLimit` (a permission class raising `Throttled`) still works but is
deprecated; don't use both or requests are counted twice.

### Django Ninja

```python
from django_tenant_apikeys.ninja import TenantAPIKeyAuth, TenantAPIKeyThrottle

api = NinjaAPI(auth=TenantAPIKeyAuth(), throttle=[TenantAPIKeyThrottle()])
```

Needs `django-ninja >= 1.2` (Ninja's throttling arrived then). Set on the
`NinjaAPI` or a router it covers every operation beneath it.

Both throttles call `check_rate_limit()`, which you can also use directly.

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
- **Memcached, or a shared Redis**, makes the exact same code correct across
  processes, because both backends implement `add`/`incr` atomically on the
  server, not just in Django's process. No package changes needed — point
  `CACHES["default"]` (or whatever `TENANT_API_KEY_RATE_LIMIT_CACHE` names)
  at one of them:

  ```python
  # settings.py -- Django's own built-in Redis cache backend (no
  # third-party cache library needed; it uses the `redis` package directly)
  CACHES = {
      "default": {
          "BACKEND": "django.core.cache.backends.redis.RedisCache",
          "LOCATION": "redis://127.0.0.1:6379/1",
      }
  }
  ```

  Redis isn't a dependency of this package, or required for any of its
  other functionality — it's only relevant if you point your own cache
  configuration at it. CI tests the Redis path in
  [`tests/test_ratelimit_redis.py`](https://github.com/stackadnan/django-tenant-apikeys/blob/main/tests/test_ratelimit_redis.py),
  skipped automatically (not failed) if no Redis is reachable.

### Fixed window, not sliding

Being a fixed window rather than a sliding one, a key can burst up to
roughly 2x its limit across a window boundary — a full window's quota right
before it rolls over, then another full window's quota right after. A
sliding window would avoid that, at the cost of storing a timestamp per
request instead of a single counter — real complexity this default doesn't
carry. If that trade-off doesn't work for your use case, see the custom
backend section below.

## When the cache is unreachable

A connection error or timeout talking to the cache (the server is down, a
network blip, ...) is not the same thing as a request exceeding its limit —
no count could even be read. `CacheRateLimitBackend.hit()` treats this as a
third outcome, distinct from both "allowed" and "limited": it logs one
`WARNING` and returns an unlimited result, so the request goes through
unmetered rather than the view raising an unhandled exception.

This is a deliberate, **fixed** policy — fail open, not configurable —
because the alternative (failing closed) would turn a transient cache
outage into an outage of every rate-limited endpoint in your project, for
every caller, which is a worse trade-off than temporarily not enforcing a
usage cap. `rate_limit` is a usage control, not the security boundary
authentication itself provides — see
[Security: rate limiting is not brute-force protection](security.md#rate-limiting-is-not-brute-force-protection).

If your deployment genuinely needs the opposite trade-off (fail closed when
the cache is down), that's a custom backend: implement `RateLimitBackend`
yourself and let the exception from your own cache calls propagate instead
of catching it.

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
- [Signals and logging](signals.md) — the `api_key_rate_limited` signal
  sent when a request is denied.
