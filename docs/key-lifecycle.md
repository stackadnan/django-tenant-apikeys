# API key rotation, revocation, and expiration

A key needs more than "exists" and "doesn't exist." This page covers the
four ways a key's usability changes over time: revocation, expiration,
rotation, and last-used tracking.

## Revoke a key immediately

```python
api_key.revoke(reason="compromised")   # reason is optional, stored on the row
api_key.is_active   # False
```

`revoke()` sets the same `is_active` flag `TenantAPIKeyAuthentication`
already checks on every request — there's no separate "revoked" gate that
could fall out of sync with it. `revoked_at` and `revoked_reason` are audit
metadata only; nothing reads them to decide whether the key still works.

`revoke()` is **idempotent**: revoking an already-revoked key leaves its
original `revoked_at` and `revoked_reason` untouched, so a repeated call
can't overwrite the record of why and when it was first revoked.

A caller without a valid secret always gets `"Invalid API key."`, whatever
the key's history. Once the secret verifies, the DRF backend distinguishes
`"This API key has been deactivated."` and `"This API key has expired."`
(useful to the key's legitimate holder); Django Ninja returns a bare 401 for
every failure.

`reactivate()` undoes it:

```python
api_key.reactivate()
api_key.is_active   # True again -- but is_expired is independent, so a key
                     # whose expires_at has already passed stays unusable
```

Revocation is immediate — the very next request with that key fails, no
delay or cache to invalidate.

## Expiration

```python
api_key.expires_at = timezone.now() + timedelta(days=30)
api_key.is_expired   # computed property, not stored
api_key.is_valid      # is_active and not is_expired
```

Leave `expires_at` blank (the default) for a key that never expires. Unlike
`is_active`, which is a switch you can flip back, `is_expired` is a
timestamp comparison against `timezone.now()` — you can't "un-expire" a key
past its `expires_at` the same way; you'd extend the timestamp instead.

Use `expires_at` for a planned, known-in-advance cutoff. Use `is_active`
(via `revoke()`) for "this should stop working right now." They're
different levers for different situations — see the compromised-key example
below.

## Rotating a key without downtime

```python
new_key, raw_key = api_key.rotate()
```

This creates a new row with the same tenant, scopes, expiration,
environment, rate limit, allowed IPs, and metadata as the original
(override any of them: `api_key.rotate(scopes=["orders:*"])`), revokes the
original with `reason="rotated"`, and returns the new instance and its raw
key — the only time you'll see it, same as `generate_key()`. The old row
isn't deleted, so it stays visible for audit history; it just can't
authenticate anymore. Both the insert and the revoke happen inside one
`transaction.atomic()` block.

The key is re-read under a `SELECT ... FOR UPDATE` lock first (a no-op on
SQLite), and the new row's values are copied from that fresh read — so a
stale instance, or two concurrent rotations of the same key, can't both
succeed and leave two live replacements: the second raises `ValueError`.
The new key keeps the original key's prefix (`acme_live_…` rotates to
`acme_live_…`); pass `prefix=` to change it.

```python
old_key, raw_key = OrganizationAPIKey.generate_key(name="k", tenant=org)
new_key, new_raw_key = old_key.rotate()

old_key.is_valid   # False
new_key.is_valid   # True
new_key.tenant == old_key.tenant   # True
```

Rotating an already-inactive or expired key raises `ValueError` — silently
handing out working access from a key that was deliberately (or
automatically) shut off would be the wrong default.

### Rotating with a grace period

`rotate()` revokes the old key immediately, which is right for a compromised
key but wrong if the client needs time to switch over. Pass a grace period:

```python
from datetime import timedelta

new_key, raw_key = api_key.rotate(grace_period=timedelta(days=7))
```

The old key is **not** revoked. Its `expires_at` is set to `now +
grace_period` — or left alone if it already expires sooner; a grace period
never extends a key's life — so both keys authenticate until then and the
old one stops by itself. The new key gets the old key's *original*
`expires_at`, not the grace cutoff. `grace_period` must be positive.

While the old key has a live replacement it can't be rotated again (that
would leave two live replacements): the second call raises `ValueError`.
Once the replacement is revoked or expired, rotating is allowed again.

Use `last_used_at` to see whether the client has moved: once the old key's
`last_used_at` stops advancing, you can `revoke()` it early instead of
waiting out the window.

From the command line: `manage.py tenant_api_key_rotate <prefix> --grace-days 7`.

For a **compromised** key, skip the grace period entirely — plain
`rotate()`, or `revoke()`.

### Which key replaced which

The new key's `rotated_from` points at the key it replaced (set to `NULL`,
not cascaded, if the old row is ever deleted); the reverse accessor is
`old_key.rotated_to`. The Django admin shows it.

```python
new_key.rotated_from      # the old key
old_key.rotated_to.all()  # every key issued to replace it
```

`reactivate()` on a rotated key is still allowed on purpose: undoing a
rotation that didn't deploy is a legitimate rollback (revoke the
replacement, reactivate the original). It doesn't touch `rotated_from`.

## `last_used_at` without a write on every request

```python
api_key.record_usage()  # called automatically by TenantAPIKeyAuthentication / TenantAPIKeyAuth
```

Updating a timestamp on every authenticated request sounds harmless until
the endpoint is hot — "record usage" becomes one extra database write per
request, forever. `record_usage()` avoids that with a class attribute:

```python
LAST_USED_THRESHOLD: ClassVar[timedelta] = timedelta(minutes=5)
```

If the key was already marked used within the last `LAST_USED_THRESHOLD`,
`record_usage()` returns immediately — no query at all. Once the threshold
has elapsed, it issues a single-column `UPDATE ... SET last_used_at = %s`
through the manager, not `self.save()` — a targeted update doesn't
re-validate or re-save every other field, and doesn't risk clobbering a
concurrent change to some other field made by a different request in the
meantime.

The trade-off: `last_used_at` answers "was this key used recently," not
"what was the exact timestamp of the last request." For its actual purpose
— deciding whether a key is still in active use, and confirming a rotation
cutover is safe — that's the right trade-off. If you need an exact
per-request audit trail, that's a different problem (a separate log table),
not what this field is for.

With `TENANT_API_KEY_RECORD_IP = True`, the same write also stores the
client address in `last_used_ip` (only if it's a valid IP; garbage is never
stored). A *changed* address is written immediately instead of waiting out
the threshold, so `last_used_ip` never lags a move to a new address.

Override the threshold per subclass for coarser or finer tracking:

```python
class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(Organization, related_name="api_keys", on_delete=models.CASCADE)
    LAST_USED_THRESHOLD = timedelta(hours=1)
```

There's no project-level setting for this — it's a per-model trade-off
between write volume and precision, not a global one.

## From the shell

```bash
python manage.py tenant_api_key_rotate <prefix>
python manage.py tenant_api_key_revoke <prefix> --reason "compromised"
```

See [Management commands](management-commands.md) for the full reference.

## Next

- [Security](security.md) — why revocation and rotation are structured this
  way, alongside the rest of the threat model.
- [Admin](admin.md) — the one-time secret reveal, and rotating/revoking from
  the Django admin instead of the shell.
