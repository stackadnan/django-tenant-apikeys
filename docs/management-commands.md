# Management commands

```bash
python manage.py tenant_api_key_revoke <prefix> [--reason "why"]
python manage.py tenant_api_key_rotate <prefix>
```

Both require `django_tenant_apikeys` in `INSTALLED_APPS` (Django only
discovers management commands from installed apps), and both resolve the
concrete model generically via `TENANT_API_KEY_MODEL` — neither needs to
know what fields your concrete model adds beyond what `AbstractTenantAPIKey`
already defines.

## `tenant_api_key_revoke`

```bash
python manage.py tenant_api_key_revoke tak_live_3f9a2c1d --reason "compromised"
```

Looks the key up by its **prefix** — the part before the dot, never the raw
secret, which isn't stored anywhere to look up by. Calls
[`revoke()`](key-lifecycle.md#revoke-a-key-immediately) with the given
reason (optional). Raises `CommandError` with a clear message if no key
matches the prefix.

## `tenant_api_key_rotate`

```bash
python manage.py tenant_api_key_rotate tak_live_3f9a2c1d
```

Same prefix lookup, then calls
[`rotate()`](key-lifecycle.md#rotating-a-key-without-downtime) — prints the
new key's prefix and its raw secret once, the same way the admin and
`generate_key()` do. Raises `CommandError` (not a traceback) if the key is
already inactive or expired, since `rotate()` itself refuses that case.

## No `tenant_api_key_create`

Deliberately absent. Creating a key needs whatever fields your concrete
model requires — at minimum a `tenant` — and this package can't know that
generically without either hardcoding an assumption or degrading into an
awkward `--field=value` interface for every possible field, including ones
this package doesn't even define.

Write your own command instead, against your own schema — it's a handful
of lines. See
[`examples/simple_saas/organizations/management/commands/create_demo_key.py`](https://github.com/stackadnan/django-tenant-apikeys/blob/main/examples/simple_saas/organizations/management/commands/create_demo_key.py)
for a working example to copy from.

## Next

- [Key lifecycle](key-lifecycle.md) — the same operations from Python code,
  including the grace-period rotation pattern these commands don't
  implement on their own.
- [Admin](admin.md) — the same operations from the Django admin.
