# Installation

```bash
pip install django-tenant-apikeys[drf]
```

The base package has zero framework dependencies beyond Django itself.
Extras are additive — install whichever your project actually uses:

| Extra   | Installs                     | Needed for                                     |
|---------|-------------------------------|-------------------------------------------------|
| `drf`   | `djangorestframework>=3.14`   | `TenantAPIKeyAuthentication`, `HasAPIKeyScope`, `HasAllowedIP`, `WithinRateLimit` |
| `ninja` | `django-ninja>=1.0`            | `TenantAPIKeyAuth`                              |

Installing the bare package (no extras) still gives you
`AbstractTenantAPIKey`, `generate_api_key()`, `hash_key()`, and
`get_api_key_model()` — enough to wire up your own authentication layer if
you're not on DRF or Ninja.

## Supported versions

- Python 3.10, 3.11, 3.12, 3.13, 3.14
- Django 4.2, 5.2 and 6.1, on the Python versions each supports (tested in
  CI; other 4.x/5.x/6.x releases are likely to work but aren't part of the
  test matrix)

## Add it to your project

```python
# settings.py
INSTALLED_APPS = [
    ...
    "django_tenant_apikeys",  # needed for the admin integration and management commands
    "rest_framework",         # if you're using the DRF integration
    "myapp",
]
```

`django_tenant_apikeys` only needs to be in `INSTALLED_APPS` for the admin
integration and the `tenant_api_key_revoke`/`tenant_api_key_rotate`
management commands — Django only discovers either from an installed app.
The model, hashing, and authentication logic work without it, since
`AbstractTenantAPIKey` is abstract and ships no migrations of its own; your
concrete subclass's app is what actually gets migrated.

Continue to [Quickstart](quickstart.md) to define your key model and issue
your first key.

## Installing from source (contributing)

```bash
git clone https://github.com/stackadnan/django-tenant-apikeys
cd django-tenant-apikeys
python -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

The `dev` extra pulls in everything needed to run and check the project —
see [Testing](testing.md) for what that includes and which commands CI runs.
