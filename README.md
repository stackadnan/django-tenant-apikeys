# django-tenant-apikeys

[![PyPI version](https://img.shields.io/pypi/v/django-tenant-apikeys.svg)](https://pypi.org/project/django-tenant-apikeys/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-tenant-apikeys.svg)](https://pypi.org/project/django-tenant-apikeys/)
[![Tests](https://github.com/stackadnan/django-tenant-apikeys/actions/workflows/test.yml/badge.svg)](https://github.com/stackadnan/django-tenant-apikeys/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/pypi/l/django-tenant-apikeys.svg)](LICENSE)
[![Latest on Django Packages](https://img.shields.io/badge/Django_Packages-django--tenant--apikeys-8c3c26.svg)](https://djangopackages.org/packages/p/django-tenant-apikeys/)
[![Documentation](https://img.shields.io/badge/docs-stackadnan.github.io-blue)](https://stackadnan.github.io/django-tenant-apikeys/)

<p align="center">
  <img src="https://raw.githubusercontent.com/stackadnan/django-tenant-apikeys/main/docs/images/banner.png" alt="django-tenant-apikeys" width="900">
</p>

<p align="center">
  Multi-tenant API key authentication for Django
</p>

Issue a key per tenant, hash it before it ever touches the database, gate
access with scopes instead of an all-or-nothing flag, restrict it by IP,
rate-limit it, and rotate or revoke it later without touching your own
code. First-class **Django REST Framework** and **Django Ninja** support.

If you've built API key auth for a SaaS product before, you've probably
written this same code three or four times: generate a random token, hash
it, store the hash, look it up on every request, and figure out how to show
the raw key to the user exactly once — then bolt on a tenant relation, a
scopes field, and an IP allowlist by hand. `django-tenant-apikeys` is that
code, written once and tested against every rejection path, not just the
happy one.

- **Bring your own tenant model.** Subclass one abstract model, add a
  `tenant` foreign key, and `request.tenant` is resolved automatically on
  every authenticated request.
- **Nothing sensitive is stored.** Keys are `secrets`-generated, kept only
  as a SHA-256 hash, checked with a constant-time comparison, and shown to
  you exactly once.
- **Scopes, not just on/off.** `"orders:read"`, a whole namespace with
  `"orders:*"`, or everything with `"*"`.
- **Per-key IP allowlists and rate limits.** IPv4/IPv6, CIDR networks, and
  a configurable per-key request limit — both optional, both opt-in.
- **A real lifecycle.** `rotate()` issues a replacement and revokes the
  original in one call; `revoke()`/`reactivate()` manage access directly.
- **Small, framework-agnostic core.** The model doesn't know DRF or Ninja
  exist. Everything framework-specific is an optional adapter on top.

## Install

```bash
pip install django-tenant-apikeys[drf]
```

```python
# myapp/models.py
class OrganizationAPIKey(AbstractTenantAPIKey):
    tenant = models.ForeignKey(Organization, related_name="api_keys", on_delete=models.CASCADE)
```

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="CI deploy key",
    tenant=org,
    scopes=["deployments:write"],
)
print(raw_key)  # tak_live_3f9a2c1d.k7pQ2m1v... -- shown once, never stored
```

```python
# myapp/views.py
class DeploymentsView(APIView):
    authentication_classes = [TenantAPIKeyAuthentication]
    permission_classes = [HasAPIKeyScope]
    required_scopes = ["deployments:write"]

    def post(self, request):
        request.tenant.deployments.create(...)  # attached automatically
```

Full walkthrough: **[Quickstart](https://stackadnan.github.io/django-tenant-apikeys/quickstart/)**.
A complete runnable project lives in
[`examples/simple_saas/`](examples/simple_saas/) — clone the repo, run
`python manage.py create_demo_key`, and you have a real tenant-scoped key
and a working `curl` command in about a minute.

## Documentation

Full documentation, including configuration, IP restrictions, rate
limiting, the Django Ninja integration, and the complete API reference, is
at **[stackadnan.github.io/django-tenant-apikeys](https://stackadnan.github.io/django-tenant-apikeys/)**.

| | |
|---|---|
| [Installation](https://stackadnan.github.io/django-tenant-apikeys/installation/) · [Quickstart](https://stackadnan.github.io/django-tenant-apikeys/quickstart/) · [Configuration](https://stackadnan.github.io/django-tenant-apikeys/configuration/) | Getting started |
| [Authentication](https://stackadnan.github.io/django-tenant-apikeys/authentication/) · [Multi-tenancy](https://stackadnan.github.io/django-tenant-apikeys/multi-tenancy/) · [Scopes](https://stackadnan.github.io/django-tenant-apikeys/scopes/) · [Key lifecycle](https://stackadnan.github.io/django-tenant-apikeys/key-lifecycle/) | Core concepts |
| [Environments](https://stackadnan.github.io/django-tenant-apikeys/environments/) · [IP restrictions](https://stackadnan.github.io/django-tenant-apikeys/ip-restrictions/) · [Rate limiting](https://stackadnan.github.io/django-tenant-apikeys/rate-limiting/) · [Metadata](https://stackadnan.github.io/django-tenant-apikeys/metadata/) | Per-key policies |
| [Django REST Framework](https://stackadnan.github.io/django-tenant-apikeys/django-rest-framework/) · [Django Ninja](https://stackadnan.github.io/django-tenant-apikeys/django-ninja/) | Framework integrations |
| [Admin](https://stackadnan.github.io/django-tenant-apikeys/admin/) · [Management commands](https://stackadnan.github.io/django-tenant-apikeys/management-commands/) · [Security](https://stackadnan.github.io/django-tenant-apikeys/security/) · [Testing](https://stackadnan.github.io/django-tenant-apikeys/testing/) · [Troubleshooting](https://stackadnan.github.io/django-tenant-apikeys/troubleshooting/) | Operating it |
| [API reference](https://stackadnan.github.io/django-tenant-apikeys/api-reference/) | Reference |

The [wiki](https://github.com/stackadnan/django-tenant-apikeys/wiki) has a
few longer standalone articles — a factual comparison against
`djangorestframework-api-key`, shared-schema vs. schema-per-tenant
multi-tenancy, and a general API-key security checklist — that go deeper
than the reference docs on those specific topics.

## Supported versions

- Python 3.10, 3.11, 3.12, 3.13, 3.14
- Django 4.2 and 5.2 (tested in CI; other 4.x/5.x releases are likely to
  work but aren't part of the test matrix)
- Django REST Framework ≥ 3.14 and/or django-ninja ≥ 1.0, both optional

## Development

```bash
git clone https://github.com/stackadnan/django-tenant-apikeys
cd django-tenant-apikeys
pip install -e ".[dev]"
pytest --cov=django_tenant_apikeys --cov-report=term-missing   # 100% coverage enforced
ruff check .
mypy django_tenant_apikeys
```

Those three commands are exactly what CI runs on every push and PR — see
[CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow, and
[Testing](https://stackadnan.github.io/django-tenant-apikeys/testing/) for
running against PostgreSQL and testing your own authentication code.

## License

[MIT](LICENSE)
