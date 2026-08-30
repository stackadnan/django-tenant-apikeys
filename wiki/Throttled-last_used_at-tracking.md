# Throttled `last_used_at` tracking: avoiding a DB write on every authenticated request

Knowing when an API key was last used is useful — it's how you tell a
tenant "this integration key hasn't been touched in 90 days, are you still
using it," and it's how [rotation](https://github.com/stackadnan/django-tenant-apikeys/wiki/Rotating-and-expiring-API-keys-in-Django-without-breaking-existing-clients)
becomes something you can verify instead of just wait out. The obvious
implementation — update a timestamp on every authenticated request — is
also a trap: on a hot endpoint, "record usage" turns into "one extra
database write per request, forever." This page covers how
[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)'s
`record_usage()` avoids that.

## The method

```python
LAST_USED_THRESHOLD: ClassVar[timedelta] = timedelta(minutes=5)

def record_usage(self) -> None:
    now = timezone.now()
    if self.last_used_at is not None and now - self.last_used_at < self.LAST_USED_THRESHOLD:
        return
    type(self).objects.filter(pk=self.pk).update(last_used_at=now)
    self.last_used_at = now
```

Two ideas doing the work here, and they're independent of each other.

## Throttling: skip the write entirely, don't just batch it

If the key was already marked used within the last `LAST_USED_THRESHOLD`
(5 minutes by default), `record_usage()` returns immediately — no query at
all, not even a cheap one. On an endpoint handling a request a second from
one key, this turns roughly 300 potential writes over 5 minutes into 1.
The trade-off is precision: `last_used_at` answers "was this key used
recently," not "what was the exact timestamp of the last request." For its
actual purpose — deciding whether a key is still in active use — that's
the right trade-off. If you need an exact per-request audit trail, that's
a different problem (a separate log/event table), not what this field is
for.

## A targeted `UPDATE`, not `save()`

When the write does happen, it goes through the manager
(`type(self).objects.filter(pk=self.pk).update(last_used_at=now)`), not
`self.save()`. `.update()` issues a single-column `UPDATE ... SET
last_used_at = %s WHERE pk = %s` — it doesn't re-run field validation,
doesn't re-save every other column on the row, and critically, doesn't
clobber a concurrent change to some *other* field made by a different
request between when this instance was loaded and now. `self.save()` would
write back whatever was in memory for every field, which is exactly the
kind of lost-update bug that's easy to introduce by reaching for the more
familiar method.

`self.last_used_at = now` after the `.update()` call keeps the in-memory
instance consistent with what was just written, without a second query to
re-fetch it.

## Where it's called

`TenantAPIKeyAuthentication.authenticate_credentials()` calls
`api_key.record_usage()` right after the `is_active`/`expires_at` checks
pass, and before tenant attachment — so a failed authentication never
records usage, only a genuinely successful one does. The
[Django Ninja recipe](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-Ninja---API-key-auth-without-DRF)
calls it explicitly in the same spot, since Ninja doesn't share DRF's
authentication class.

## Customizing the threshold

`LAST_USED_THRESHOLD` is a plain class attribute, overridable per
subclass:

```python
class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(Organization, related_name="api_keys", on_delete=models.CASCADE)
    LAST_USED_THRESHOLD = timedelta(hours=1)
```

A coarser threshold means fewer writes but staler "last seen" data; a
finer one (even `timedelta(seconds=0)`, effectively disabling throttling)
means every request writes, trading write volume for precision. There's no
setting for this at the package level on purpose — it's a per-project,
per-model trade-off, not a global one.

## How the test suite verifies the throttle without sleeping

Testing "does nothing happen for 5 minutes" without an actual 5-minute
`sleep()` in the test suite means faking the clock, and
`tests/test_models.py` does it by writing a stale timestamp directly
through the manager rather than through `record_usage()` itself:

```python
def test_updates_once_threshold_has_elapsed(self, tenant: Tenant) -> None:
    instance, _raw_key = TenantAPIKey.generate_key(name="k", tenant=tenant)
    stale = timezone.now() - instance.LAST_USED_THRESHOLD - timedelta(seconds=1)
    TenantAPIKey.objects.filter(pk=instance.pk).update(last_used_at=stale)
    instance.refresh_from_db()

    instance.record_usage()

    assert instance.last_used_at is not None
    assert instance.last_used_at > stale
```

Backdating `last_used_at` to just past the threshold, then calling
`record_usage()` and asserting it actually moved forward, tests the exact
same code path a real 5-minutes-later request would hit — without the test
suite taking 5 minutes to run. The companion test,
`test_within_threshold_does_not_overwrite`, calls `record_usage()` twice in
a row with no backdating and asserts the timestamp is unchanged the second
time, covering the opposite branch.

## Try it

- Full test suite: [`tests/test_models.py`](https://github.com/stackadnan/django-tenant-apikeys/blob/main/tests/test_models.py)
- Full API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- See also: [Rotating and expiring API keys](https://github.com/stackadnan/django-tenant-apikeys/wiki/Rotating-and-expiring-API-keys-in-Django-without-breaking-existing-clients)
