# simple_saas — a minimal django-tenant-apikeys demo

The smallest possible Django + DRF project showing the whole flow:

```
Organization (tenant)
      │
      ▼
OrganizationAPIKey.generate_key()  ──►  raw key shown once
      │
      ▼
Authorization: Api-Key <raw key>  ──►  TenantAPIKeyAuthentication
      │
      ▼
request.auth = the key, request.tenant = the Organization
      │
      ▼
HasAPIKeyScope checks required_scopes  ──►  view runs with correct tenant context
```

Two apps: `organizations` (the `Organization` tenant model + the concrete
`OrganizationAPIKey`) and one view, `WhoAmIView`, that just reports back what
the library resolved from the request.

## Run it

```bash
cd examples/simple_saas
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt

python manage.py migrate
python manage.py create_demo_key
```

That last command creates an `Organization` named "Acme Inc.", issues it a
key scoped to `whoami:read`, and prints the raw key along with a ready-to-run
`curl` command. Start the server in another terminal:

```bash
python manage.py runserver
```

...and run the `curl` command the previous step printed. You'll get back:

```json
{
  "tenant": "Acme Inc.",
  "key_name": "demo key",
  "key_prefix": "tak_live_...",
  "scopes": ["whoami:read"]
}
```

Change or remove `--org` to create a second tenant with its own key, and
notice each key only ever resolves its own `tenant` — that's the isolation
this package provides: nothing in `WhoAmIView` looked up which organization
the request belonged to, `request.tenant` was already the right one.

Try dropping the `Authorization` header, using a garbage key, or a key with
the wrong scope — each fails with a 401 or 403 rather than a stack trace.

## Rotating and revoking the demo key

The `tenant_api_key_rotate` and `tenant_api_key_revoke` management commands
work here unchanged -- they only need `TENANT_API_KEY_MODEL`, which this
project's `settings.py` already sets:

```bash
python manage.py tenant_api_key_rotate <prefix>          # prints a new raw key, revokes the old one
python manage.py tenant_api_key_revoke <prefix> --reason="testing"
```

Use the prefix printed by `create_demo_key` (the part before the dot).
After rotating, the old `curl` command starts returning 401; the new one
printed by the rotate command works in its place.

## What this is (and isn't)

This is a demonstration of the library's request/response flow, not a
template for a real SaaS backend — there's no user accounts, no signup flow,
no per-tenant data model beyond the key itself. See the
[main README](../../README.md) for the full API reference and the security
notes worth reading before using this in something real.
