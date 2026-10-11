# Signals and logging

The package doesn't ship an audit table or a webhook system. It tells you
what happened — through Django signals and a logger — and you decide what to
do with that.

## Signals

All four are plain `django.dispatch.Signal`s in
`django_tenant_apikeys.signals`, sent with your concrete key model as
`sender`:

| Signal | Sent when | Keyword arguments |
|---|---|---|
| `api_key_created` | `generate_key()` (so also `rotate()`) | `api_key` |
| `api_key_revoked` | `revoke()`, once per actual revocation | `api_key`, `reason` |
| `api_key_rotated` | `rotate()`, after its transaction | `old_key`, `new_key`, `grace_period` (`None` = immediate) |
| `api_key_rejected` | authentication refuses a key, in DRF *and* Ninja | `reason`, `api_key` (or `None`), `client_ip` |
| `api_key_rate_limited` | a key's `rate_limit` is exceeded, in DRF *and* Ninja | `api_key`, `result` (a `RateLimitResult`) |

```python
from django.dispatch import receiver
from django_tenant_apikeys.signals import api_key_rate_limited, api_key_rejected, api_key_revoked


@receiver(api_key_revoked)
def audit_revocation(sender, api_key, reason, **kwargs):
    AuditEvent.objects.create(kind="key_revoked", key_prefix=api_key.prefix, detail=reason)


@receiver(api_key_rejected)
def count_rejections(sender, reason, api_key, client_ip, **kwargs):
    metrics.incr("api_key.rejected", tags={"reason": reason})


@receiver(api_key_rate_limited)
def count_throttled(sender, api_key, result, **kwargs):
    metrics.incr("api_key.rate_limited", tags={"key_prefix": api_key.prefix})
```

`reason` is a `RejectionReason` value: `malformed`, `unknown_key`,
`bad_secret`, `inactive`, `expired`, `environment`, `ip_not_allowed`,
`tenant_not_allowed`. It is precise here even though the *client* is never
told which of the first three it was.

There's no separate "key expired" event. An expired key is rejected the
same way any other invalid key is — `api_key_rejected` with
`reason="expired"` — because that's the only place expiry is actually
*detected*: at the moment a key is presented for authentication, not by a
background job scanning for keys whose `expires_at` has passed. If you need
to know about expiry before anyone presents the key again, query
`expires_at` yourself (e.g. a periodic `manage.py` command over
`YourKeyModel.objects.filter(expires_at__lt=timezone.now(), is_active=True)`);
that's an application-specific report, not something this library runs for
you.

`api_key_rate_limited` is sent once per request that's actually denied —
never for a request within the limit, and never for a key with no
`rate_limit` set, so it can't turn a hot endpoint into a signal-dispatch
cost on every call.

Things to know:

- Signals are synchronous. Inside an `atomic()` block that later rolls back,
  a receiver has already run — use `transaction.on_commit` in the receiver if
  that matters.
- A receiver that raises never breaks the operation: the error is logged on
  the `django_tenant_apikeys` logger and swallowed. (An audit hook that's
  down shouldn't turn every failed login into a 500.)
- `api_key_rejected` fires for unauthenticated traffic, so keep receivers
  cheap. There's deliberately no signal for *successful* authentication —
  that's your hot path; use `last_used_at` / `last_used_ip`.

## Logging

Logger name: `django_tenant_apikeys`. Every rejection is one `WARNING`:

```
API key rejected: reason=ip_not_allowed prefix=tak_live_3f9a2c1d client_ip='198.51.100.7'
```

- The `prefix` is logged **only once it matched a real key**. For a
  malformed or unknown key the "prefix" is attacker-supplied text (and for a
  key pasted without its `.`, could be the entire secret), so it's replaced
  with `-`.
- The secret is never logged, and neither is any part of a key that didn't
  match a row.
- `client_ip` is repr-escaped and truncated, so a hostile header value can't
  forge log lines.

A key being rate limited is also one `WARNING`:

```
API key rate limited: prefix=tak_live_3f9a2c1d limit=100/minute retry_after=37
```

And, separately, the rate-limit cache itself being unreachable (a dropped
Redis connection, a timeout) is its own `WARNING` — not a rejection or a
rate-limit event, since no limit was actually checked. See
[Rate limiting: when the cache is unreachable](rate-limiting.md#when-the-cache-is-unreachable).
