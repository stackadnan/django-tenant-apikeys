# Multi-tenant Django patterns: shared-schema vs schema-per-tenant, and where API keys fit

"Multi-tenant" isn't one architecture — it's a spectrum, and where you land
on it changes what "authenticate this API key" actually has to do. This
page covers the two dominant Django patterns and where
[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
fits naturally versus where you'd need to write glue code.

## Shared-schema: one table, filtered by a tenant column

Every tenant's rows live in the same tables, in the same database,
distinguished by a `tenant_id` foreign key. It's the simplest thing that
works: one Django project, one connection, migrations run once. The cost
is discipline — every query touching tenant data needs the tenant filter
applied, every time, and forgetting it once is a data leak between
customers, not a crash you'd notice in testing.

This is the architecture `AbstractTenantAPIKey` is built around. You
subclass it, add a `tenant` foreign key, and that's the entire integration:

```python
class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(Organization, related_name="api_keys", on_delete=models.CASCADE)
```

`TenantAPIKeyAuthentication` resolves the key and its tenant in the same
query path, attaches `request.tenant`, and your views filter everything
else by it — the same shape you'd already use for `request.user` in a
single-tenant app, just one hop further.

## Schema-per-tenant: isolated schemas, routed before your code runs

The other end of the spectrum — used by libraries like
[django-tenants](https://django-tenants.readthedocs.io/) — gives each
tenant its own PostgreSQL schema. Tables in `SHARED_APPS` (like the tenant
directory itself) live in a `public` schema everyone can see; tables in
`TENANT_APPS` are duplicated per schema and completely isolated from each
other at the database level. Instead of a `WHERE tenant_id = ...` you
might forget, isolation is enforced by which schema the connection's
`search_path` is pointed at for the duration of the request — a stronger
guarantee, at the cost of more moving parts (schema-aware migrations,
routing middleware, no cross-tenant joins).

The routing question this raises: **how does the request know which
schema to use before any of your view code runs?** In django-tenants,
that's typically resolved by hostname — a `Domain` model in the shared
`public` schema maps `acme.example.com` to the Acme tenant, and
`TenantMainMiddleware` sets the schema before the view is called, based on
the incoming request's domain.

## Where a header-based API key doesn't fit that model cleanly

Hostname-based routing assumes the tenant is knowable from *where the
request came in* — a subdomain, a custom domain. An API key doesn't work
that way: it arrives as a header value on a request that could hit any
domain your API answers on. To resolve a tenant from a key, you have to
look the key up in a table *before* you know which schema to search — but
in a schema-per-tenant setup, that's exactly the kind of lookup schema
isolation is designed to prevent you from doing blindly across tenants.

The resolution is the same one django-tenants already uses for the tenant
directory itself: put the API key model (and whatever it needs to resolve
a tenant) in `SHARED_APPS`, in the public schema, rather than in
`TENANT_APPS`. That makes the key lookup a normal shared-schema query — the
same shape `AbstractTenantAPIKey` already assumes — and the tenant it
resolves to tells you *which* per-tenant schema to switch into for the
rest of the request, rather than the schema having been decided for you
already by the hostname.

**This isn't a tested or built-in integration** — django-tenant-apikeys has
no knowledge of django-tenants, `search_path`, or schema switching at all,
and combining the two hasn't been verified end-to-end. If you're doing
this, the shape would be: subclass `TenantAPIKeyAuthentication`, call
`super().authenticate_credentials(...)` to resolve the key and its tenant
as normal (from the shared schema), then explicitly switch schema context
yourself (e.g. via django-tenants' `connection.set_tenant(...)`) before
returning — glue code you'd write and test for your specific setup, not
something this package does for you.

## Which one should you actually use

Shared-schema first, unless you have a specific reason not to. Reach for
schema-per-tenant when you have a hard requirement — regulatory data
isolation, a customer who insists on physically separate storage, or a per
tenant backup/restore/deletion story that's much easier when it's "drop
this schema" instead of "delete every row matching this tenant_id across
forty tables." Absent one of those, shared-schema is easier to reason
about, easier to deploy, and — not incidentally — the architecture this
package, and `examples/simple_saas/`, are built around.

## Try it

- Full quickstart and API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working shared-schema example project: [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
- See also: [Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication)
