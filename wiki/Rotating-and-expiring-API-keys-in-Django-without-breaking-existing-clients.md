# Rotating and expiring API keys in Django without breaking existing clients

The naive way to "rotate" an API key is to regenerate the secret on the
existing row and hand the new value to the client. That's not rotation,
it's an outage — every request signed with the old key starts failing the
instant you save, and there's no window for the client to update. This
page covers the overlap pattern that avoids that, using
[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)'
actual fields: `expires_at`, `is_active`, `is_expired`, `is_valid`, and
`last_used_at`.

There's no dedicated `rotate_key()` helper in the package today — what
follows is a pattern built from the primitives that exist, not a single
method call. (If you want one, that's a reasonable thing to open an issue
for.)

## Why in-place regeneration breaks clients

A key's `hashed_key` is only ever set once, at creation, from
`generate_key()`. There's no supported way to "re-roll the secret on the
same row" without also invalidating whatever the client currently has
configured — and even if there were, you'd still have the same problem:
one moment the old value works, the next it doesn't, with no notice to the
holder.

## The pattern: issue new, expire old, don't revoke old immediately

Rotation that doesn't break anyone has three steps, and the point of all
three is that there's a window where **both keys work**.

**1. Issue the replacement key immediately, tied to the same tenant:**

```python
new_instance, new_raw_key = OrganizationAPIKey.generate_key(
    name=f"{old_instance.name} (rotated)",
    tenant=old_instance.tenant,
    scopes=old_instance.scopes,
)
```

Hand `new_raw_key` to the client now — same as at initial creation, it's
your only chance to show it.

**2. Give the old key a grace-period expiry instead of deactivating it on the spot:**

```python
from datetime import timedelta
from django.utils import timezone

old_instance.expires_at = timezone.now() + timedelta(days=30)
old_instance.save(update_fields=["expires_at"])
```

The old key keeps working — `is_valid` stays `True` — until that date.
The client has 30 days (pick whatever fits your relationship with them) to
switch over on their own schedule instead of on yours.

**3. Use `last_used_at` to know when it's actually safe to cut it off early:**

```python
if old_instance.last_used_at is None or old_instance.last_used_at < some_cutoff:
    old_instance.is_active = False
    old_instance.save(update_fields=["is_active"])
```

Once the old key's `last_used_at` stops advancing, the client has migrated
— you don't have to wait out the full grace period to retire it, and you
don't have to guess. This is the practical payoff of `record_usage()`
existing at all: rotation becomes something you can verify instead of
something you just wait out.

## Compromised key: skip the grace period

The overlap pattern above is for planned rotation. If a key has leaked,
don't give it a grace period — flip `is_active` off immediately:

```python
compromised_instance.is_active = False
compromised_instance.save(update_fields=["is_active"])
```

`is_active=False` is checked before `expires_at` in
`TenantAPIKeyAuthentication.authenticate_credentials()`, so it takes effect
on the very next request, unlike expiry which is time-based. Issue the
replacement key the same way as step 1 above, but skip step 2 entirely.

## Expiry vs. revocation: they're not the same lever

- **`expires_at`** is a plan — a known, in-advance point where a key
  should stop working. `is_expired` is computed from it, not stored.
- **`is_active`** is a switch — immediate, and reversible (flip it back to
  `True` if you revoked the wrong key by mistake; you can't "un-expire" a
  key past its `expires_at` the same way, since that's just a timestamp
  comparison against `timezone.now()`).
- **`is_valid`** is `is_active and not is_expired` — the single check most
  application code actually wants, rather than testing both separately.

Rotation with a grace period uses `expires_at` because it's a planned,
future event. Killing a compromised key uses `is_active` because it needs
to be immediate.

## A note on the one-time-reveal admin flow

If you're rotating a key through Django admin rather than a script, the
new key's raw secret is shown exactly once, in the warning message right
after you save — same as creating any other key. Screenshot or copy it
immediately; there's no "view secret" action afterwards, by design (only
the hash is ever stored).

## Try it

- Full API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working end-to-end project: [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
- See also: [Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication)
