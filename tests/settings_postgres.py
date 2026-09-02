"""Same test settings, against PostgreSQL instead of SQLite.

Used only by the CI Postgres job -- the point isn't to make the runtime
package depend on PostgreSQL (it doesn't; there's no database-specific code
anywhere in django_tenant_apikeys), it's to prove the library actually
works against a production-grade relational database, not just SQLite's
more forgiving defaults.
"""

from __future__ import annotations

import os

from .settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "django_tenant_apikeys_test"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}
